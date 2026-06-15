"""
Semantic Router — определяет намерение пользователя и возвращает URL раздела.
"""
import json
from shared.embeddings import embed_query, cosine_similarity

# Интенты с примерами запросов
INTENTS = {
    "catalog": {
        "priority": 1,
        "threshold": 0.65,
        "url_template": "/shop/",
        "utterances": [
            "показать каталог", "где посмотреть товары", "что у вас есть",
            "ассортимент", "выбор товаров", "какие есть платья", "покажите юбки",
            "есть платья", "есть юбки", "есть брюки", "какие платья есть",
            "какие юбки есть", "хочу посмотреть", "что продаёте", "товары"
        ]
    },
    "delivery": {
        "priority": 1,
        "threshold": 0.65,
        "url_template": "/payment-and-delivery/",
        "utterances": [
            "доставка", "как получить заказ", "сроки доставки", "курьер",
            "почта", "стоимость доставки", "доставка по россии", "как заказать",
            "доставляете ли вы", "условия доставки", "бесплатная доставка"
        ]
    },
    "contacts": {
        "priority": 1,
        "threshold": 0.65,
        "url_template": "/contacts/",
        "utterances": [
            "контакты", "связаться", "телефон", "адрес магазина",
            "как с вами связаться", "напишите мне", "позвонить", "где находитесь",
            "ваш телефон", "ваш адрес", "как проехать", "как добраться"
        ]
    },
    "payment": {
        "priority": 1,
        "threshold": 0.65,
        "url_template": "/payment-and-delivery/",
        "utterances": [
            "оплата", "как оплатить", "способы оплаты", "рассрочка",
            "плайт", "картой", "наличные", "чек", "стоимость"
        ]
    },
    "general": {
        "priority": 2,
        "threshold": 0.6,
        "url_template": "",
        "utterances": [
            "о чём сайт", "что это за сайт", "расскажи о компании",
            "чем занимаетесь", "какие услуги", "о компании"
        ]
    }
}

# Кэш эмбеддингов интентов
_intent_embeddings = {}
_embeddings_loaded = False

def _preload_intent_embeddings():
    """Предзагрузка эмбеддингов при старте."""
    global _intent_embeddings, _embeddings_loaded
    if not _embeddings_loaded:
        import math
        for name, intent in INTENTS.items():
            embeddings = [embed_query(u) for u in intent['utterances']]
            # Среднее геометрическое
            avg = []
            for col in zip(*embeddings):
                product = 1.0
                for v in col:
                    product *= abs(v) + 1e-10
                sign = 1 if sum(col) > 0 else -1
                avg.append(math.pow(product, 1.0/len(col)) * sign)
            _intent_embeddings[name] = avg
        _embeddings_loaded = True

def _get_intent_embeddings():
    """Возвращает кэш эмбеддингов."""
    if not _embeddings_loaded:
        _preload_intent_embeddings()
    return _intent_embeddings


def detect_intent(question: str) -> dict:
    """
    Определяет намерение пользователя.
    Возвращает {intent_name, confidence, url_template} или None.
    """
    query_emb = embed_query(question)
    embeddings = _get_intent_embeddings()
    
    best_intent = None
    best_score = 0
    
    for name, intent_emb in embeddings.items():
        score = cosine_similarity(query_emb, intent_emb)
        intent = INTENTS[name]
        if score >= intent['threshold'] and score > best_score:
            best_score = score
            best_intent = {
                'name': name,
                'confidence': round(score, 3),
                'priority': intent['priority'],
                'url_template': intent['url_template']
            }
    
    return best_intent

# Предзагружаем эмбеддинги при импорте
_preload_intent_embeddings()
