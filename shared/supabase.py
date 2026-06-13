import os
import requests

SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError('SUPABASE_URL and SUPABASE_KEY must be set in environment')

# Единая HTTP-сессия с keep-alive для всех запросов
_session = None

def _get_session():
    global _session
    if _session is None:
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        _session = requests.Session()
        adapter = HTTPAdapter(
            pool_connections=10,
            pool_maxsize=20,
            max_retries=Retry(total=2, backoff_factor=0.3)
        )
        _session.mount('https://', adapter)
    return _session

def _headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal"
    }

def supabase_get(endpoint, params=None):
    url = f"{SUPABASE_URL}/rest/v1/{endpoint}"
    return _get_session().get(url, headers=_headers(), params=params, timeout=15)

def supabase_post(endpoint, json_data):
    url = f"{SUPABASE_URL}/rest/v1/{endpoint}"
    return _get_session().post(url, headers=_headers(), json=json_data, timeout=15)

def supabase_delete(endpoint, params=None):
    url = f"{SUPABASE_URL}/rest/v1/{endpoint}"
    return _get_session().delete(url, headers=_headers(), params=params, timeout=15)

def supabase_rpc(function_name, json_data):
    url = f"{SUPABASE_URL}/rest/v1/rpc/{function_name}"
    return _get_session().post(url, headers=_headers(), json=json_data, timeout=15)

# Совместимость со старым кодом
from supabase import create_client

def get_supabase():
    """Создаёт новый клиент Supabase (для обратной совместимости)."""
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def reset_supabase():
    """Сбрасывает клиент."""
    return get_supabase()
