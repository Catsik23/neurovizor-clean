"""
Модуль сбора поисковых запросов через Yandex Wordstat API (Search API v2)
Использует сервисный аккаунт neurovizor-search
"""
import requests
import os

API_KEY = os.environ.get('YANDEX_SEARCH_API_KEY', '')
if not API_KEY:
    print('[WARNING] YANDEX_SEARCH_API_KEY not set — Wordstat disabled', flush=True)
FOLDER_ID = os.environ.get('YANDEX_FOLDER_ID', '')
WORDSTAT_URL = "https://searchapi.api.cloud.yandex.net/v2/wordstat/topRequests"

def get_top_requests(phrase: str, num: int = 10) -> dict:
    """Получить топ запросов по фразе через Wordstat API."""
    headers = {
        "Authorization": f"Api-Key {API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "folderId": FOLDER_ID,
        "phrase": phrase,
        "numPhrases": num
    }
    
    response = requests.post(WORDSTAT_URL, headers=headers, json=payload, timeout=10)
    
    if response.status_code == 200:
        return response.json()
    else:
        from shared.logger import log_event
        log_event("wordstat_api_error", status=response.status_code, body=response.text[:200])
        return {"results": []}


def collect_niche_queries(phrase: str, num: int = 15) -> list:
    """
    Собирает поисковые запросы по нише.
    Возвращает список словарей [{phrase, count}, ...]
    """
    data = get_top_requests(phrase, num)
    results = data.get('results', [])
    return [{"phrase": r.get('phrase', ''), "count": r.get('count', 0)} for r in results]


def get_search_volume(phrase: str) -> int:
    """Получить частотность конкретного запроса."""
    data = get_top_requests(phrase, 1)
    return int(data.get('totalCount', 0))
