from shared.supabase import get_supabase
from datetime import datetime
import threading

def log_event(event_type, site_id=None, user_id=None, data=None, **kwargs):
    """Записывает событие в таблицу events (в фоновом потоке, не блокирует ответ)."""
    def _write():
        try:
            event_data = {**(data or {}), **kwargs}
            get_supabase().table('events').insert({
                'site_id': site_id, 'user_id': user_id, 'event_type': event_type,
                'event_data': event_data, 'created_at': datetime.utcnow().isoformat()
            }).execute()
        except Exception as e:
            print(f'[EVENT ERROR] {e}', flush=True)
    
    threading.Thread(target=_write, daemon=True).start()
