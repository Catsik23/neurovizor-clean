from shared.supabase import supabase
from datetime import datetime

EVENTS = {
    'SITE_ADDED': 'site_added', 'CRAWL_STARTED': 'crawl_started', 'CRAWL_COMPLETED': 'crawl_completed',
    'FAQ_GENERATED': 'faq_generated', 'FAQ_FAILED': 'faq_failed', 'CARD_PUBLISHED': 'card_published',
    'CARD_BLOCKED': 'card_blocked', 'CHAT_ENABLED': 'chat_enabled', 'USER_REGISTERED': 'user_registered',
    'USER_LOGIN': 'user_login', 'ERROR': 'error',
}

def log_event(event_type, site_id=None, user_id=None, data=None, **kwargs):
    """Записывает событие в таблицу events в Supabase."""
    try:
        event_data = {**(data or {}), **kwargs}
        supabase.table('events').insert({
            'site_id': site_id, 'user_id': user_id, 'event_type': event_type,
            'event_data': event_data, 'created_at': datetime.utcnow().isoformat()
        }).execute()
    except Exception as e:
        print(f'[EVENT ERROR] {e}', flush=True)
