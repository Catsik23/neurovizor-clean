"""
Краулер: парсинг сайтов, чанкование, векторизация и сохранение в Supabase.
"""
from flask import Blueprint, request, jsonify
from bs4 import BeautifulSoup
import requests
import re
from datetime import datetime
from shared.supabase import get_supabase
from shared.utils import chunk_text, ai_visibility_audit, detect_site_type, extract_entities
from shared.embeddings import embed_document
from shared.logger import log_event
import threading

crawler_bp = Blueprint('crawler', __name__)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; NeurovizorBot/1.0; +https://neurovizor.ru)'
}

def parse_url(url: str, base_domain: str = None) -> dict:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or 'utf-8'
    except requests.RequestException as e:
        log_event("error", "crawler_fetch_failed", url=url, error=str(e))
        raise ValueError(f"Не удалось загрузить страницу: {e}")

    soup = BeautifulSoup(resp.text, 'html.parser')

    # Собираем внутренние ссылки с текстом
    internal_links = []
    if base_domain:
        from urllib.parse import urljoin
        for a in soup.find_all('a', href=True):
            href = a.get('href', '').strip()
            text = a.get_text(strip=True)[:80]
            if not href or not text:
                continue
            full_url = urljoin(url, href)
            # Только внутренние ссылки
            if base_domain in full_url and full_url not in [l['url'] for l in internal_links]:
                internal_links.append({'url': full_url, 'title': text})
    
    for tag in soup(['script', 'style', 'nav', 'footer', 'header']):
        tag.decompose()

    body = soup.find('body')
    text = body.get_text(separator=' ', strip=True) if body else soup.get_text(separator=' ', strip=True)
    text = re.sub(r'\s+', ' ', text).strip()

    title = soup.title.string.strip() if soup.title and soup.title.string else url
    description = ''
    meta_desc = soup.find('meta', attrs={'name': 'description'})
    if meta_desc and meta_desc.get('content'):
        description = meta_desc['content'].strip()

    return {
        "url": url,
        "title": title,
        "description": description,
        "text": text,
        "html": resp.text,
        "internal_links": internal_links
    }


def get_base_domain(url: str) -> str:
    from urllib.parse import urlparse
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def crawl_site(url: str, max_pages: int = 10) -> list:
    """
    Глубокий парсинг: главная + все внутренние страницы (до max_pages).
    Возвращает список словарей parse_url.
    """
    base_domain = get_base_domain(url)
    pages = []
    visited = set()
    from collections import deque
    queue = deque([url])
    
    while queue and len(pages) < max_pages:
        current_url = queue.popleft()
        if current_url in visited:
            continue
        visited.add(current_url)
        
        try:
            page_data = parse_url(current_url, base_domain)
            pages.append(page_data)
            
            # Добавляем новые ссылки в очередь
            for link in page_data.get('internal_links', []):
                if link['url'] not in visited and link['url'] not in queue:
                    queue.append(link['url'])
        except Exception as e:
            log_event("warning", "crawl_page_failed", url=current_url, error=str(e))
            continue
    
    return pages

def index_site(site_id: str, url: str, user_id: str):
    log_event("index_site_started", site_id=site_id, url=url)
    print(f">>> INDEX_START {site_id} {url}", flush=True)

    try:
        supabase = get_supabase()

        # Обновляем статус только для реальных сайтов
        if not str(site_id).startswith('demo-'):
            supabase.table("sites").update({
                "updated_at": datetime.utcnow().isoformat()
            }).eq("id", site_id).execute()

        # Глубокий парсинг: все страницы сайта
        pages = crawl_site(url, max_pages=15)
        print(f">>> CRAWLED {len(pages)} pages", flush=True)
        log_event("crawl_completed", site_id=site_id, pages_count=len(pages))
        print(f">>> AUDIT START", flush=True)
        
        # Объединяем текст со всех страниц
        all_text = ' '.join([p['text'] for p in pages])
        main_page = pages[0] if pages else parse_url(url)
        
        audit_result = ai_visibility_audit(all_text, main_page.get("html", ""))
        site_type = detect_site_type(all_text)
        print(f">>> AUDIT DONE, type={site_type}", flush=True)

        # Удаляем старые чанки
        print(f">>> DELETING old chunks...", flush=True)
        import requests as _req
        import os as _os
        _del_headers = {
            "apikey": _os.environ.get("SUPABASE_KEY", ""),
            "Authorization": "Bearer " + _os.environ.get("SUPABASE_KEY", "")
        }
        _req.delete(
            f"{_os.environ.get('SUPABASE_URL', '')}/rest/v1/knowledge_chunks?site_id=eq.{site_id}",
            headers=_del_headers, timeout=10
        )
        print(f">>> DELETED", flush=True)

        from shared.utils import page_usefulness_score
        saved_count = 0
        noise_count = 0
        # Чанкуем каждую страницу отдельно, фильтруем шум, сохраняем source_url
        for page in pages:
            # Пропускаем шумовые страницы
            if page_usefulness_score(page.get("text", ""), page.get("html", ""), page.get("url", "")) < 20:
                noise_count += 1
                continue
            chunks = chunk_text(page["text"], source_url=page.get("url", ""))
            print(f">>> PAGE {page["url"]}: {len(chunks)} chunks", flush=True)
            for chunk in chunks:
                try:
                    embedding = embed_document(chunk["text"])
                    print(f">>> INSERTING chunk {chunk.get("chunk_type","?")}", flush=True)
                    import requests as _req
                    import os as _os
                    _payload = {
                        "site_id": site_id,
                        "chunk_text": chunk["text"][:5000],
                        "chunk_type": chunk.get("chunk_type", "paragraph"),
                        "chunk_position": chunk.get("position", 0),
                        "source_url": page.get("url", ""),
                        "source_title": page.get("title", ""),
                        "embedding": embedding
                    }
                    _headers = {
                        "apikey": _os.environ.get("SUPABASE_KEY", ""),
                        "Authorization": "Bearer " + _os.environ.get("SUPABASE_KEY", ""),
                        "Content-Type": "application/json",
                        "Prefer": "return=minimal"
                    }
                    _url = _os.environ.get("SUPABASE_URL", "") + "/rest/v1/knowledge_chunks"
                    _resp = _req.post(_url, json=_payload, headers=_headers, timeout=10)
                    if _resp.status_code == 201:
                        saved_count += 1
                    else:
                        log_event("warning", "chunk_save_failed", site_id=site_id, status=_resp.status_code)
                    saved_count += 1
                except Exception as e:
                    log_event("warning", "chunk_save_failed", site_id=site_id, error=str(e))

        supabase.table("sites").update({
            "ai_visibility_score": audit_result.get("score", 0),
            "site_type": site_type,
            "faq_count": saved_count,
            "parsed_content": all_text[:100000],
            "pages_count": len(pages),
            "indexed_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        }).eq("id", site_id).execute()

        # Сохраняем карту категорий
        try:
            supabase.table("site_categories").delete().eq("site_id", site_id).execute()
            cat_urls = {}
            for page in pages:
                for link in page.get('internal_links', []):
                    url = link.get('url', '')
                    title = link.get('title', '')[:80]
                    if url and title and url not in cat_urls:
                        cat_urls[url] = title
                        supabase.table("site_categories").insert({
                            "site_id": site_id,
                            "category_name": title,
                            "url": url
                        }).execute()
        except Exception as e:
            print(f'>>> CATEGORIES ERROR: {e}', flush=True)
            log_event("warning", "categories_save_failed", site_id=site_id, error=str(e))
        else:
            print(f'>>> CATEGORIES SAVED: {len(cat_urls)}', flush=True)

        log_event("info", "index_site_completed", site_id=site_id,
                 chunk_count=saved_count, score=audit_result.get("score"))

    except Exception as e:
        log_event("index_site_failed", site_id=site_id, error=str(e))
        try:
            supabase.table("sites").update({
                "indexing_error": str(e)[:500],
                "updated_at": datetime.utcnow().isoformat()
            }).eq("id", site_id).execute()
        except:
            pass

@crawler_bp.route('/index', methods=['POST'])
def start_indexing():
    user_id = request.session.get("user_id")
    if not user_id:
        return jsonify({"error": "Требуется авторизация"}), 401

    data = request.get_json()
    site_id = data.get("site_id")
    url = data.get("url")

    if not site_id or not url:
        return jsonify({"error": "site_id и url обязательны"}), 400

    thread = threading.Thread(target=index_site, args=(site_id, url, user_id), daemon=True)
    thread.start()

    return jsonify({
        "status": "started",
        "site_id": site_id,
        "message": "Индексация запущена"
    })

@crawler_bp.route('/status/<site_id>', methods=['GET'])
def indexing_status(site_id):
    try:
        supabase = get_supabase()
        result = supabase.table("sites").select("indexing_status, faq_count, ai_visibility_score").eq("id", site_id).single().execute()

        if result.data:
            return jsonify(result.data)
        return jsonify({"error": "Сайт не найден"}), 404
    except Exception as e:
        log_event("error", "index_status_failed", site_id=site_id, error=str(e))
        return jsonify({"error": str(e)}), 500
