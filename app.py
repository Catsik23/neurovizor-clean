from flask import Flask, render_template, request, jsonify
import time
from collections import defaultdict
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

from services.auth.app import auth_bp
from services.ai.app import ai_bp
from services.crawler.app import crawler_bp
from services.neurocard.app import neurocard_bp
from shared.logger import log_event

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY')
if not app.secret_key:
    raise RuntimeError('SECRET_KEY env var is not set')

_demo_limits = defaultdict(list)

def check_demo_limit(ip):
    now = time.time()
    window = 3600
    max_requests = 3
    _demo_limits[ip] = [ts for ts in _demo_limits[ip] if now - ts < window]
    if len(_demo_limits[ip]) >= max_requests:
        return False, 0
    _demo_limits[ip].append(now)
    return True, max_requests - len(_demo_limits[ip])

app.register_blueprint(auth_bp)
app.register_blueprint(ai_bp)
app.register_blueprint(crawler_bp)
app.register_blueprint(neurocard_bp)

@app.route('/')
def index():
    """Главная страница — лендинг с AEO-аудитом."""
    return render_template('pages/index.html')

@app.route('/demo', methods=['POST'])
def demo():
    """Демо-эндпоинт: парсит сайт, генерирует FAQ и нейро-карточку."""
    ip = request.headers.get('X-Forwarded-For', request.remote_addr) or 'unknown'
    if ',' in ip:
        ip = ip.split(',')[0].strip()
    allowed, remaining = check_demo_limit(ip)
    if not allowed:
        return jsonify({'success': False, 'message': 'Лимит демо исчерпан. Попробуйте через час или зарегистрируйтесь — первые 7 дней бесплатно.', 'remaining': 0})
    
    from shared.utils import parse_site, ai_visibility_audit
    from services.ai.app import generate_faq
    from services.neurocard.app import generate_neuro_card_static

    url = request.form.get('url', '').strip()
    if not url:
        return jsonify({'success': False, 'message': 'Введите URL сайта'})

    result = parse_site(url)
    if not result['success']:
        return jsonify(result)

    audit = ai_visibility_audit(result['text'], result.get('html', ''))
    faq = generate_faq(result['title'], result['text'], result['phones'], result['emails'])
    filename = generate_neuro_card_static(result['domain'], result['title'], result['text'], result['phones'], result['emails'], faq, None)

    # Сохраняем чанки в Supabase для векторного поиска
    demo_site_id = 'demo-' + result['domain']
    try:
        from shared.utils import chunk_text, classify_chunk_topic
        from shared.supabase import get_supabase
        
        # Удаляем старые чанки для этого домена
        get_supabase().table('knowledge_chunks').delete().eq('site_id', demo_site_id).execute()
        
        from shared.embeddings import embed_document
        chunks = chunk_text(result['text'])
        
        # Шаг 1: Все эмбеддинги в памяти
        chunk_data = []
        for chunk in chunks:
            try:
                embedding = embed_document(chunk['text'])
            except:
                embedding = None
            chunk_data.append({'chunk': chunk, 'embedding': embedding})
            print('>>> EMBEDDED ' + chunk.get('chunk_type', '?'), flush=True)
        
        # Шаг 2: Сохраняем все чанки через прямые HTTP-запросы
        import requests as req
        supabase_url = os.environ['SUPABASE_URL'] + '/rest/v1/knowledge_chunks'
        supabase_headers = {
            'apikey': os.environ['SUPABASE_KEY'],
            'Authorization': 'Bearer ' + os.environ['SUPABASE_KEY'],
            'Content-Type': 'application/json'
        }
        for item in chunk_data:
            payload = {
                'site_id': demo_site_id,
                'chunk_text': item['chunk']['text'],
                'chunk_type': item['chunk'].get('chunk_type', 'paragraph'),
                'chunk_position': item['chunk'].get('position', 0),
                'topic': classify_chunk_topic(item['chunk']['text']),
                'importance_score': 3 if classify_chunk_topic(item['chunk']['text']) in ('pricing', 'delivery', 'contacts') else 1,
                'char_count': len(item['chunk']['text']),
                'embedding': item['embedding']
            }
            resp = req.post(supabase_url, json=payload, headers=supabase_headers, timeout=10)
            if resp.status_code == 201:
                print('>>> CHUNK SAVED ' + item['chunk'].get('chunk_type', '?'), flush=True)
            else:
                print('>>> CHUNK FAILED ' + str(resp.status_code) + ': ' + resp.text[:100], flush=True)
    except Exception as e:
        print('>>> DEMO CHUNK ERROR:', str(e), flush=True)
        log_event('demo_chunk_error', error=str(e), site_id=demo_site_id)

    # Считаем количество найденных страниц
    pages_found = len(result.get('pages', []))

    return jsonify({
        'success': True, 'domain': result['domain'], 'title': result['title'],
        'pages_count': pages_found, 'ai_visibility_score': audit['score'], 'ai_visibility_details': audit['details'],
        'faq': faq, 'neuro_card_url': f'/neuro/{filename}', 'site_id': demo_site_id, 'remaining': remaining,
    })

@app.route('/admin/errors')
def admin_errors():
    if request.remote_addr not in ('127.0.0.1', '::1'):
        return jsonify({'error': 'Access denied'}), 403
    """Админ-дашборд ошибок за 24 часа."""
    from datetime import datetime as dt, timedelta
    from shared.supabase import get_supabase
    
    since = (dt.utcnow() - timedelta(hours=24)).isoformat()
    events = supabase.table('events') \
        .select('*') \
        .gte('created_at', since) \
        .order('created_at', desc=True) \
        .limit(100) \
        .execute()
    
    # Группировка по event_type
    from collections import Counter
    error_counts = Counter()
    recent = []
    for e in (events.data or []):
        etype = e.get('event_type', 'unknown')
        error_counts[etype] += 1
        if len(recent) < 20:
            recent.append(e)
    
    html = '<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Admin Errors</title>'
    html += '<style>body{font-family:monospace;background:#0a0a1a;color:#e0e0e0;padding:20px}'
    html += 'h1{color:#c084fc}table{border-collapse:collapse;width:100%}'
    html += 'th,td{border:1px solid #333;padding:8px;text-align:left}'
    html += 'th{background:#1a1a2e}.error{color:#ff4d6a}.warn{color:#ff9100}</style></head><body>'
    html += '<h1>🔴 Admin Errors (24h)</h1>'
    
    html += '<h2>By Type</h2><table><tr><th>Type</th><th>Count</th></tr>'
    for etype, count in error_counts.most_common():
        cls = 'error' if 'error' in etype.lower() or 'failed' in etype.lower() else 'warn'
        html += f'<tr><td class="{cls}">{etype}</td><td>{count}</td></tr>'
    html += '</table>'
    
    html += '<h2>Recent (20)</h2><table><tr><th>Time</th><th>Type</th><th>Data</th></tr>'
    for e in recent:
        html += f'<tr><td>{e.get("created_at","")[:19]}</td>'
        html += f'<td>{e.get("event_type","")}</td>'
        html += f'<td>{e.get("event_data",{})}</td></tr>'
    html += '</table></body></html>'
    
    return html


@app.route('/payment')
def payment():
    """Страница оплаты (заглушка)."""
    return render_template('pages/payment.html')

@app.route('/debug/embed')
def debug_embed():
    import os
    try:
        from shared.embeddings import embed_document
        r1 = len(embed_document("test1"))
        r2 = len(embed_document("test2"))
        return jsonify({"first": r1, "second": r2, "offline": os.environ.get("HF_HUB_OFFLINE")})
    except Exception as e:
        return jsonify({"error": str(e), "type": type(e).__name__}), 500

@app.route('/test-embed')
def test_embed():
    import os
    result = {
        'HF_HUB_OFFLINE': os.environ.get('HF_HUB_OFFLINE'),
        'TRANSFORMERS_OFFLINE': os.environ.get('TRANSFORMERS_OFFLINE'),
    }
    try:
        from shared.embeddings import embed_document
        emb = embed_document('test')
        result['embedding_len'] = len(emb)
        result['status'] = 'ok'
    except Exception as e:
        result['error'] = str(e)
    return jsonify(result)

@app.route('/health')
def health():
    try:
        from shared.ai_client import get_model
        get_model()
        return 'ready'
    except:
        return 'loading', 503

# === ПРОГРЕВ МОДЕЛИ ПРИ СТАРТЕ ===
print(">>> Preloading embedding model...", flush=True)
import time as _time
_t0 = _time.time()
from shared.embeddings import embed_document
_ = embed_document("model warmup")
print(f">>> Model ready in {_time.time()-_t0:.1f}s", flush=True)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
