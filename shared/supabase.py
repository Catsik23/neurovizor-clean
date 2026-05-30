import os
from supabase import create_client

SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError('SUPABASE_URL and SUPABASE_KEY must be set in environment')

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def get_supabase():
    """Возвращает клиент Supabase. Создаёт новый при необходимости."""
    return supabase
