"""
Автономный генератор семантики:
1. Сбор запросов через Wordstat API
2. Кластеризация через эмбеддинги
3. Генерация FAQ под каждый кластер с фактами с сайта
"""
import os, sys
import numpy as np
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def cluster_queries(queries: list, n_clusters: int = 5) -> dict:
    """
    Кластеризует запросы по смысловым группам через эмбеддинги.
    Возвращает словарь {cluster_id: [queries]}.
    """
    from shared.embeddings import embed_document
    from sklearn.cluster import KMeans
    
    if len(queries) < n_clusters:
        n_clusters = max(2, len(queries) // 3)
    
    # Эмбеддинги для всех запросов
    texts = [q.get('phrase', q) if isinstance(q, dict) else q for q in queries]
    embeddings = np.array([embed_document(t) for t in texts])
    
    # KMeans кластеризация
    kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    labels = kmeans.fit_predict(embeddings)
    
    # Группируем
    clusters = defaultdict(list)
    for i, label in enumerate(labels):
        clusters[int(label)].append(queries[i])
    
    return dict(clusters)


def generate_faq_for_cluster(site_facts: dict, cluster_queries: list, cluster_topic: str = "") -> list:
    """
    Генерирует FAQ для одного кластера запросов с учётом фактов с сайта.
    Возвращает список [{q, a, category, source_url}, ...].
    """
    from shared.ai_client import ask_yandexgpt
    
    site_title = site_facts.get('title', 'компании')
    site_text = site_facts.get('text', '')[:3000]
    site_url = site_facts.get('url', '')
    phones = site_facts.get('phones', [])
    
    # Формируем запросы для контекста
    queries_text = '\n'.join([f"- {q.get('phrase', q) if isinstance(q, dict) else q}" 
                              for q in cluster_queries[:5]])
    
    prompt = f"""Сгенерируй 3-5 вопросов и ответов для FAQ компании "{site_title}".

На основе поисковых запросов:
{queries_text}

И информации с сайта:
{site_text[:2000]}

Правила:
- Каждый ответ должен содержать конкретный факт с сайта
- Если на сайте нет точной информации — напиши "уточните по телефону {phones[0] if phones else ''}"
- Каждый вопрос должен звучать как реальный запрос пользователя
- Верни ТОЛЬКО JSON-массив: [{{"q":"вопрос","a":"ответ","category":"категория","source_url":"{site_url}"}}]
- Категории: pricing, delivery, contacts, about, services, guarantees"""

    try:
        faq_text = ask_yandexgpt(prompt, "", 
            "Ты — SEO-аналитик. Генерируешь FAQ для нейро-карточек. Возвращаешь ТОЛЬКО JSON.")
        
        # Парсим JSON
        import json, re
        clean = re.sub(r'^```(?:json)?\s*|\s*```$', '', faq_text.strip())
        faq = json.loads(clean)
        if isinstance(faq, list):
            return faq[:5]
    except Exception as e:
        from shared.logger import log_event
        log_event("semantic_faq_parse_error", error=str(e))
    
    # Fallback — базовый FAQ
    base_q = cluster_queries[0].get('phrase', 'услуги') if cluster_queries else 'услуги'
    return [{
        "q": f"Какие {base_q} предлагает {site_title}?",
        "a": f"Подробная информация на сайте {site_url}. Телефон: {phones[0] if phones else 'уточняйте'}.",
        "category": "services",
        "source_url": site_url
    }]


def generate_full_faq(site_facts: dict, niche_queries: list, 
                      total_faq: int = 50, top_n: int = 10) -> dict:
    """
    Полный цикл генерации FAQ.
    Возвращает {full_faq: [...], demo_faq: [...]}.
    """
    # Кластеризуем
    clusters = cluster_queries(niche_queries, n_clusters=min(7, len(niche_queries) // 3))
    
    all_faq = []
    for cluster_id, queries in clusters.items():
        # Определяем тему кластера по первому запросу
        topic = queries[0].get('phrase', '')[:30] if queries else f"тема {cluster_id}"
        faq_items = generate_faq_for_cluster(site_facts, queries, topic)
        all_faq.extend(faq_items)
    
    # Убираем дубликаты по вопросу
    seen = set()
    unique_faq = []
    for item in all_faq:
        if item['q'] not in seen:
            seen.add(item['q'])
            unique_faq.append(item)
    
    # Топ-N для демо (по частотности — первые в списке)
    demo_faq = unique_faq[:top_n]
    
    return {
        "full_faq": unique_faq[:total_faq],
        "demo_faq": demo_faq,
        "clusters_count": len(clusters),
        "total_generated": len(unique_faq)
    }
