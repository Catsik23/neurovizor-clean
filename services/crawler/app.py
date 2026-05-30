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

def parse_url(url: str) -> dict:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or 'utf-8'
    except requests.RequestException as e:
        log_event("error", "crawler_fetch_failed", url=url, error=str(e))
        raise ValueError(f"Не удалось загрузить страницу: {e}")

    soup = BeautifulSoup(resp.text, 'html.parser')

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
        "html": resp.text
    }

def index_site(site_id: str, url: str, user_id: str):
    log_event("info", "index_site_started", site_id=site_id, url=url)

    try:
        supabase = get_supabase()

        supabase.table("sites").update({
            "indexing_status": "in_progress",
            "updated_at": datetime.utcnow().isoformat()
        }).eq("id", site_id).execute()

        page_data = parse_url(url)
        audit_result = ai_visibility_audit(page_data["text"], page_data["html"])
        site_type = detect_site_type(page_data["text"])
        entities = extract_entities(page_data["text"])

        if isinstance(entities, list):
            for entity in entities:
                try:
                    supabase.table("extracted_entities").upsert({
                        "site_id": site_id,
                        "entity_type": entity.get("type", "unknown"),
                        "entity_value": entity.get("value", ""),
                        "source_url": url,
                        "created_at": datetime.utcnow().isoformat()
                    }).execute()
                except Exception as e:
                    log_event("warning", "entity_save_failed", entity=str(entity)[:100], error=str(e))
        elif isinstance(entities, dict):
            for entity_type, entity_list in entities.items():
                for entity_value in entity_list:
                    try:
                        supabase.table("extracted_entities").upsert({
                            "site_id": site_id,
                            "entity_type": entity_type,
                            "entity_value": entity_value,
                            "source_url": url,
                            "created_at": datetime.utcnow().isoformat()
                        }).execute()
                    except Exception as e:
                        log_event("warning", "entity_save_failed", entity=entity_value, error=str(e))

        chunks = chunk_text(page_data["text"])
        log_event("info", "chunks_created", site_id=site_id, chunk_count=len(chunks))

        # Удаляем старые чанки и сохраняем новые
        supabase.table("knowledge_chunks").delete().eq("site_id", site_id).execute()

        saved_count = 0
        for chunk in chunks:
            try:
                embedding = embed_document(chunk["text"])
                supabase.table("knowledge_chunks").insert({
                    "site_id": site_id,
                    "chunk_text": chunk["text"],
                    "chunk_type": chunk.get("chunk_type", "paragraph"),
                    "chunk_position": chunk.get("position", 0),
                    "embedding": embedding,
                    "created_at": datetime.utcnow().isoformat()
                }).execute()
                saved_count += 1
            except Exception as e:
                log_event("warning", "chunk_save_failed", site_id=site_id, error=str(e))

        supabase.table("sites").update({
            "indexing_status": "completed",
            "ai_visibility_score": audit_result.get("score", 0),
            "site_type": site_type,
            "faq_count": saved_count,
            "parsed_content": page_data["text"][:50000],
            "indexed_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        }).eq("id", site_id).execute()

        log_event("info", "index_site_completed", site_id=site_id,
                 chunk_count=saved_count, score=audit_result.get("score"))

    except Exception as e:
        log_event("error", "index_site_failed", site_id=site_id, error=str(e))
        try:
            supabase.table("sites").update({
                "indexing_status": "failed",
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
