import os
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_DATASETS_OFFLINE", "1")

import numpy as np
from functools import lru_cache
from shared.logger import log_event

_model = None

def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer('/opt/neurovizor/models/e5-small')
        # Холостой прогрев
        _model.encode("warmup", normalize_embeddings=True)
        log_event("info", "embeddings_model_loaded")
    return _model

def embed_text(text):
    if not text or not text.strip():
        return [0.0] * 384
    model = _get_model()
    embedding = model.encode(text.strip(), normalize_embeddings=True)
    return embedding.tolist()

def embed_query(query):
    return embed_text(f"query: {query}")

def embed_document(text):
    return embed_text(f"passage: {text}")

def embed_batch(texts, mode="document"):
    if not texts:
        return []
    prefix = "passage: " if mode == "document" else "query: "
    model = _get_model()
    embeddings = model.encode([prefix + t.strip() for t in texts], normalize_embeddings=True, batch_size=8)
    return embeddings.tolist()

def embed_for_db(text, mode="document"):
    embedding = embed_text(f"{'passage' if mode == 'document' else 'query'}: {text}")
    return "[" + ",".join(str(x) for x in embedding) + "]"

@lru_cache(maxsize=1000)
def embed_cached(text):
    return tuple(embed_document(text))

def cosine_similarity(vec1, vec2):
    return float(np.dot(vec1, vec2))
