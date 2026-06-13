import os, requests, re, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shared.supabase import get_supabase, supabase_rpc
from shared.logger import log_event

YANDEX_API_KEY = os.environ.get('YANDEX_API_KEY', '')
YANDEX_FOLDER_ID = os.environ.get('YANDEX_FOLDER_ID', '')

_model = None
def get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer('/opt/neurovizor/models/e5-small', trust_remote_code=True)
    return _model

def ask_yandexgpt(question, context, system_prompt=None):
    if not YANDEX_API_KEY or not YANDEX_FOLDER_ID:
        return simple_search(question, context)
    try:
        response = requests.post(
            "https://llm.api.cloud.yandex.net/foundationModels/v1/completion",
            headers={
                "Authorization": f"Api-Key {YANDEX_API_KEY}",
                "x-folder-id": YANDEX_FOLDER_ID
            },
            json={
                "modelUri": f"gpt://{YANDEX_FOLDER_ID}/yandexgpt-lite",
                "completionOptions": {"maxTokens": 400, "temperature": 0.3},
                "messages": [
                    {"role": "system", "text": system_prompt if system_prompt else "Ты — ИИ-ассистент Нейровизора, персональный помощник этого сайта. Отвечай ТОЛЬКО HTML-тегами внутри тела сообщения: <b>жирный</b>, <ul><li>списки</li></ul>, эмодзи 📦 💰 📞. Если есть ссылки — <a href='URL'>Название</a>. НЕ добавляй <!DOCTYPE>, <html>, <head>, <body>. Если информации нет — предложи связаться с менеджером.\nИНФО:\n" + context[:4000]},
                    {"role": "user", "text": question}
                ]
            },
            timeout=10
        )
        if response.status_code != 200:
            log_event('YANDEX_API_ERROR', data={'status': response.status_code, 'body': response.text[:200]})
            return simple_search(question, context)
        data = response.json()
        if "result" in data:
            return data["result"]["alternatives"][0]["message"]["text"]
    except (requests.Timeout, requests.ConnectionError, ValueError, KeyError) as e:
        log_event("YANDEX_ERROR", data={"error": str(e)})
    return simple_search(question, context)

def simple_search(question, context):
    keywords = question.lower().split()
    sentences = re.split(r'(?<=[.!?])\s+', context)
    best = []
    for s in sentences:
        score = sum(1 for kw in keywords if kw in s.lower())
        if score > 0:
            best.append((score, s))
    best.sort(reverse=True)
    if best:
        return ' '.join([s for _, s in best[:2]])[:300]
    return 'Уточните у менеджера.'

def get_relevant_chunks(site_id, question):
    try:
        model = get_model()
        query_embedding = model.encode(f"query: {question}", normalize_embeddings=True).tolist()
        response = supabase_rpc('match_chunks', {
            'query_embedding': query_embedding,
            'match_count': 10,
            'p_site_id': str(site_id)
        })
        if response.status_code == 200:
            data = response.json()
            if data:
                return ' '.join([r['chunk_text'] for r in data])
    except Exception as e:
        log_event("VECTOR_SEARCH_ERROR", data={"error": str(e)})
    return ''
