"""
"""
import requests
import re

def get_yandex_suggests(query, max_items=10):
    """
    Получает поисковые подсказки Яндекса по запросу.
    Возвращает список строк.
    """
    url = "https://suggest.yandex.ru/suggest-ya.cgi"
    params = {
        "srv": "ya_search",
        "part": query,
        "uil": "ru",
        "v": "5"
    }
    try:
        resp = requests.get(url, params=params, timeout=5, headers={
            "User-Agent": "Mozilla/5.0 (compatible; NeurovizorBot/1.0)"
        })
        if resp.status_code == 200:
            data = resp.json()
            # Яндекс возвращает [query, [suggests], ...]
            if len(data) > 1 and isinstance(data[1], list):
                return data[1][:max_items]
    except Exception as e:
        from shared.logger import log_event
        log_event('yandex_suggest_error', error=str(e)[:100])
    return []

def collect_niche_queries(domain, site_text='', max_total=30):
    """
    Собирает поисковые запросы по нише сайта.
    Отталкивается от домена и ключевых слов из текста.
    """
    # Базовые запросы из домена
    base_words = re.findall(r'[a-zа-яё]+', domain.lower())
    
    # Ключевые слова из текста сайта
    keywords = []
    if site_text:
        # Ищем частые слова
        words = re.findall(r'[а-яё]{4,}', site_text.lower())
        from collections import Counter
        keywords = [w for w, _ in Counter(words).most_common(5)]
    
    all_queries = []
    seen = set()
    
    # Собираем подсказки по базовым словам
    for word in base_words[:3] + keywords[:3]:
        if word in seen:
            continue
        seen.add(word)
        suggests = get_yandex_suggests(word, 5)
        all_queries.extend(suggests)
    
    # Собираем подсказки второго уровня
    for q in all_queries[:5]:
        if q not in seen:
            seen.add(q)
            suggests = get_yandex_suggests(q, 3)
            all_queries.extend(suggests)
    
    # Уникальные, не длиннее 80 символов
    unique = []
    for q in all_queries:
        if q not in unique and len(q) <= 80:
            unique.append(q)
    
    return unique[:max_total]
