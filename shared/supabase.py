import os
from supabase import create_client

SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError('SUPABASE_URL and SUPABASE_KEY must be set in environment')

_supabase_client = None

def get_supabase():
    """Создаёт новый клиент Supabase для каждого вызова."""
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def reset_supabase():
    """Сбрасывает клиент (после таймаута)."""
    global _supabase_client
    _supabase_client = None
    return get_supabase()
