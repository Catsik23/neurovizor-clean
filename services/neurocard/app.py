from flask import Blueprint, render_template, request, jsonify, send_from_directory
import re, sys, os, requests, html as html_module, json as json_module, time, time

from shared.supabase import get_supabase
from shared.logger import log_event
from shared.ai_client import ask_yandexgpt
from shared.semantic_router import detect_intent

neurocard_bp = Blueprint('neurocard', __name__)
STATIC_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'static', 'neurocards')
os.makedirs(STATIC_DIR, exist_ok=True)
_cache = {}

# Адаптивные промпты
PROMPTS = {
    'shop': 'Ты — ИИ-ассистент Нейровизора, консультант интернет-магазина. Отвечай на HTML: <ul><li>списки</li></ul>, эмодзи 📦 💰, <b>цены</b>. Если в информации есть ссылки — используй их: <a href="URL">Название раздела</a>. Предлагай оформить заказ.',
    'service': 'Ты — ИИ-ассистент Нейровизора, администратор. Отвечай на HTML: эмодзи 📅, <b>время</b>. Предлагай запись на услуги. Уточняй удобное время. Если есть ссылки — используй их.',
    'food': 'Ты — ИИ-ассистент Нейровизора, официант. Отвечай на HTML: эмодзи 🍽️, <ul><li>блюда с ценами</li></ul>. Если есть ссылки на меню — используй их.',
    'b2b': 'Ты — ИИ-ассистент Нейровизора, менеджер по продажам. Отвечай на HTML: эмодзи 💼, <b>решения</b>. Предлагай демо или консультацию. Если есть ссылки — используй их.',
    'general': 'Ты — ИИ-ассистент Нейровизора. Отвечай на HTML: эмодзи 📞, <ul><li>списки</li></ul>. Если есть ссылки — <a href="URL">Название</a>. Предлагай связаться с менеджером.'
}


def generate_neuro_card_static(domain, title, text, phones, emails, faq, site_id):
    safe_name = re.sub(r'[^a-z0-9\-]', '', domain.replace('.', '-'))[:30]
    filepath = os.path.join(STATIC_DIR, f"{safe_name}.html")
    faq_html = ''.join(f'<div class="faq-item"><h3>{html_module.escape(i["q"])}</h3><p>{html_module.escape(i["a"])}</p></div>' for i in faq)
    contact = (f'<p><strong>Телефон:</strong> {html_module.escape(phones[0])}</p>' if phones else '') + (f'<p><strong>Email:</strong> {html_module.escape(emails[0])}</p>' if emails else '')
    html = f'<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8"><title>{html_module.escape(title)}</title><style>body{{font-family:Arial;max-width:800px;margin:0 auto;padding:20px;background:#f9fafb;color:#111}}h1{{font-size:2rem}}h2{{font-size:1.5rem;margin-top:30px}}.faq-item{{background:#fff;padding:15px;margin:10px 0;border-radius:10px}}.faq-item h3{{color:#7c3aed}}.contact{{background:#eef2ff;padding:15px;border-radius:10px;margin:20px 0}}</style></head><body><h1>{html_module.escape(title)}</h1><div class="contact">{contact or '<p>Контакты на сайте</p>'}</div><h2>FAQ</h2>{faq_html}<p style="margin-top:40px;color:#888">Нейро-карточка сайта {html_module.escape(domain)}</p></body></html>'

    # Schema.org JSON-LD
    ld_json_faq = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": html_module.escape(i["q"]), "acceptedAnswer": {"@type": "Answer", "text": html_module.escape(i["a"])}}
            for i in faq
        ]
    }
    ld_json_org = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": html_module.escape(title),
        "url": f"https://{html_module.escape(domain)}",
        "telephone": phones[0] if phones else "",
        "email": emails[0] if emails else ""
    }
    html += f'<script type="application/ld+json">{json_module.dumps(ld_json_faq, ensure_ascii=False)}</script>'
    html += f'<script type="application/ld+json">{json_module.dumps(ld_json_org, ensure_ascii=False)}</script>'

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(html)
    if site_id:
        log_event('card_published', site_id=site_id)
    return f"{safe_name}.html"


@neurocard_bp.route('/neuro/<filename>')
def serve_neuro_card(filename):
    return send_from_directory(STATIC_DIR, filename)


@neurocard_bp.route('/api/generate-card', methods=['POST'])
def api_generate_card():
    data = request.get_json()
    if not data or not data.get('domain') or not data.get('title'):
        return jsonify({'success': False, 'message': 'Нужны domain и title'})
    fn = generate_neuro_card_static(data['domain'], data['title'], data.get('text', ''), data.get('phones', []), data.get('emails', []), data.get('faq', []), data.get('site_id', ''))
    if data.get('site_id'):
        get_supabase().table('sites').update({'neuro_card_url': f'/neuro/{fn}', 'neuro_card_active': True}).eq('id', data['site_id']).execute()
    return jsonify({'success': True, 'url': f'/neuro/{fn}'})


@neurocard_bp.route('/bot')
def bot_page():
    return render_template('pages/bot.html')


@neurocard_bp.route('/bot/chat', methods=['POST'])
def bot_chat():
    question = request.json.get('question', '').strip()
    domain = request.json.get('domain', '').strip()

    context = ''
    site_type = 'general'

    # Пробуем определить намерение через Semantic Router
    site_id = request.json.get('site_id', '').strip()
    intent = detect_intent(question)
    if intent and intent['name'] == 'general':
        return jsonify({'answer': f'<p>{domain} — интернет-магазин с широким ассортиментом. У нас есть каталог товаров, доставка и контакты.</p><p>📞 Свяжитесь с менеджером для подробностей.</p>', 'intent': 'general'})
    if intent and intent['priority'] == 1:
        target_url = None
        target_name = intent.get('url_template', 'Каталог')
        if site_id:
            try:
                cache_key = f'cats_{site_id}'
                cached_cats = _cache.get(cache_key, {})
                if cached_cats and time.time() - cached_cats.get('ts', 0) < 600:
                    cats_data = cached_cats['data']
                else:
                    cats = get_supabase().table('site_categories').select('url','category_name').eq('site_id', site_id).execute()
                    cats_data = cats.data
                    _cache[cache_key] = {'data': cats_data, 'ts': time.time()}
                if cats_data:
                    from shared.embeddings import embed_query, embed_document, cosine_similarity
                    q_emb = embed_query(question)
                    all_scores = []
                    for cat in cats_data:
                        cat_name = cat.get('category_name', '')
                        try:
                            cat_emb = embed_document(cat_name)
                            sim = cosine_similarity(q_emb, cat_emb)
                            url_depth = len(cat.get('url','').strip('/').split('/'))
                            score = sim - url_depth * 0.01
                            all_scores.append({'url': cat.get('url'), 'name': cat_name, 'score': score, 'sim': sim})
                        except:
                            pass
                    all_scores.sort(key=lambda x: x['score'], reverse=True)
                    if all_scores:
                        best = all_scores[0]
                        if best['score'] > 0.5:
                            target_url = best['url']
                            target_name = best['name']
                        else:
                            # Предлагаем топ-3 альтернативы
                            top3 = all_scores[:3]
                            alt_links = ' | '.join([f'<a href="{c["url"]}">{c["name"]}</a>' for c in top3])
                            target_url = top3[0]['url']
                            target_name = f'Возможно вас интересует: {alt_links}'
            except:
                pass
        if not target_url:
            target_url = f"https://{domain}/shop/" if domain else "/shop/"
        # Генерируем живой ответ через AI
        ai_answer = ask_yandexgpt(
            question, 
            f'Раздел сайта: {target_name} ({target_url})',
            f'{PROMPTS.get(site_type, PROMPTS["general"])}\nДай ссылку на раздел: <a href="{target_url}">{target_name}</a>. Будь живым и полезным, как хороший продавец.'
        )
        # Убираем markdown
        import re as _re2
        ai_answer = _re2.sub(r'```(?:html)?\s*|\s*```', '', ai_answer).strip()
        return jsonify({'answer': ai_answer, 'intent': intent['name'], 'target_url': target_url, 'target_name': target_name})

    # Ищем сайт и получаем релевантные чанки
    if domain or site_id:
        try:
            # Если site_id не передан — ищем по домену в sites
            if not site_id and domain:
                cache_key = f'bot_{domain}'
                cached = _cache.get(cache_key, {})
                if cached and time.time() - cached.get('ts', 0) < 300:
                    site_data = cached['data']
                else:
                    site = get_supabase().table('sites').select('id,site_type').eq('domain', domain).execute()
                    site_data = site.data
                    _cache[cache_key] = {'data': site_data, 'ts': time.time()}
                if site_data:
                    site_id = site_data[0]['id']
                    site_type = site_data[0].get('site_type', 'general')
            
            # Если site_id есть — используем векторный поиск
            if site_id:
                # Получаем site_type из БД для правильного промпта
                try:
                    site_info = get_supabase().table('sites').select('site_type').eq('id', site_id).execute()
                    if site_info.data:
                        site_type = site_info.data[0].get('site_type', 'general')
                except:
                    pass
                from shared.ai_client import get_relevant_chunks
                context = get_relevant_chunks(site_id, question)
                if not context:
                    # Fallback: простой поиск по чанкам
                    chunks = get_supabase().table('knowledge_chunks') \
                        .select('chunk_text') \
                        .eq('site_id', site_id) \
                        .limit(5).execute()
                    if chunks.data:
                        context = ' '.join([c['chunk_text'] for c in chunks.data])
        except Exception as e:
            log_event('bot_context_error', error=str(e), domain=domain)

    # Fallback
    if not context:
        context = 'AI Visibility Optimizer — нейро-карточки для бизнеса. 499 руб/мес. Первые 7 дней бесплатно. 499₽/мес после пробного. Отменить можно в любой момент.'

    log_event("bot_context", site_id=site_id, context_len=len(context), context_preview=context[:200])
    log_event('bot_debug', context_len=len(context), context_preview=context[:300])
    system_prompt = PROMPTS.get(site_type, PROMPTS['general']) + '\nИНФО:\n' + context[:2000]

    answer = ask_yandexgpt(question, '', system_prompt)
    # Убираем markdown и HTML-обёртки
    import re
    answer = re.sub(r'```(?:html)?\s*', '', answer)
    answer = re.sub(r'```', '', answer)
    # Убираем полный HTML-документ если есть
    body_match = re.search(r'<body[^>]*>(.*?)</body>', answer, re.DOTALL | re.IGNORECASE)
    if body_match:
        answer = body_match.group(1).strip()
    # Убираем оставшиеся обёртки
    answer = re.sub(r'<!DOCTYPE[^>]*>', '', answer, flags=re.IGNORECASE)
    answer = re.sub(r'</?html[^>]*>', '', answer, flags=re.IGNORECASE)
    answer = re.sub(r'</?head[^>]*>', '', answer, flags=re.IGNORECASE)
    answer = re.sub(r'<title[^>]*>.*?</title>', '', answer, flags=re.IGNORECASE | re.DOTALL)
    answer = re.sub(r'<meta[^>]*>', '', answer, flags=re.IGNORECASE)
    answer = answer.strip()
    return jsonify({'answer': answer})
