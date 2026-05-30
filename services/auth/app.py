from flask import Blueprint, render_template, request, redirect, url_for, flash, session
import bcrypt
import json as json_module
from datetime import datetime, timedelta
from shared.supabase import supabase
from shared.utils import parse_site, detect_site_type
from shared.logger import log_event

auth_bp = Blueprint('auth', __name__)

def login_required(f):
    """Декоратор: требует авторизацию для доступа к маршруту."""
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Войдите в систему', 'error')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    """Регистрация нового пользователя."""
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()
        password2 = request.form.get('password2', '').strip()

        if not email or not password:
            flash('Заполните все поля', 'error')
            return render_template('pages/register.html')
        if password != password2:
            flash('Пароли не совпадают', 'error')
            return render_template('pages/register.html')

        existing = supabase.table('users').select('id').eq('email', email).execute()
        if existing.data:
            flash('Пользователь с таким email уже существует', 'error')
            return render_template('pages/register.html')

        password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        supabase.table('users').insert({
            'email': email,
            'password_hash': password_hash,
            'tariff': 'trial',
            'trial_ends_at': (datetime.utcnow() + timedelta(days=7)).isoformat(),
            'subscription_active': False
        }).execute()

        log_event('user_registered')
        flash('Регистрация успешна!', 'success')
        return redirect(url_for('auth.login'))

    return render_template('pages/register.html')

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Вход в систему."""
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()

        if not email or not password:
            flash('Заполните все поля', 'error')
            return render_template('pages/login.html')

        user = supabase.table('users').select('*').eq('email', email).execute()
        if not user.data:
            flash('Неверный email или пароль', 'error')
            return render_template('pages/login.html')

        user_data = user.data[0]
        if not bcrypt.checkpw(password.encode(), user_data['password_hash'].encode()):
            flash('Неверный email или пароль', 'error')
            return render_template('pages/login.html')

        session['user_id'] = user_data['id']
        session['user_email'] = user_data['email']
        session['tariff'] = user_data['tariff']
        log_event('user_login', user_id=user_data['id'])
        flash('Добро пожаловать!', 'success')
        return redirect(url_for('auth.dashboard'))

    return render_template('pages/login.html')

@auth_bp.route('/logout')
def logout():
    """Выход из системы."""
    session.clear()
    flash('Вы вышли из системы', 'success')
    return redirect(url_for('index'))

@auth_bp.route('/dashboard')
@login_required
def dashboard():
    """Дашборд — список сайтов пользователя."""
    sites = supabase.table('sites').select('*').eq('user_id', session['user_id']).execute()
    total_faq = 0
    for site in sites.data:
        faq_count = site.get('faq_count', 0) or 0
        site['faq_count'] = faq_count
        total_faq += faq_count
    return render_template('pages/dashboard.html', 
                          sites=sites.data, 
                          total_faq=total_faq,
                          tariff=session.get('tariff', 'trial'))

@auth_bp.route('/dashboard/sites/new', methods=['GET', 'POST'])
@login_required
def add_site():
    """Добавление нового сайта: парсинг, индексация, FAQ, нейро-карточка."""
    if request.method == 'POST':
        url = request.form.get('url', '').strip()
        if not url:
            flash('Введите URL сайта', 'error')
            return render_template('pages/add_site.html')
        if not url.startswith('http'):
            url = 'https://' + url

        result = parse_site(url)
        if not result['success']:
            flash(result.get('message', 'Ошибка анализа сайта'), 'error')
            return render_template('pages/add_site.html')

        # Сохраняем сайт
        site_result = supabase.table('sites').insert({
            'user_id': session['user_id'],
            'url': url,
            'domain': result['domain'],
            'title': result['title'],
            'text_content': '',  # текст сохраним в чанках
            'faq': '[]',
            'site_type': detect_site_type(result['text']),
            'contacts': '{"phones": [], "emails": []}',
            'neuro_card_url': '',
            'neuro_card_active': False
        }).execute()
        
        site_id = site_result.data[0]['id']

        # === ЗАПУСКАЕМ КОНВЕЙЕР В ФОНЕ ===
        from threading import Thread
        
        def run_pipeline(url, site_id, result, user_id):
            import json as json_module
            from services.crawler.app import index_site
            from services.ai.app import generate_faq
            from services.neurocard.app import generate_neuro_card_static
            
            faq = []
            card_url = ''
            
            try:
                import threading
                thread = threading.Thread(target=index_site, args=(site_id, url, user_id), daemon=True)
                thread.start()
            except Exception as e:
                log_event('pipeline_indexing_error', site_id=site_id, user_id=user_id, error=str(e))
            
            try:
                faq = generate_faq(result['title'], result['text'], result['phones'], result['emails'])
            except Exception as e:
                log_event('pipeline_faq_error', site_id=site_id, user_id=user_id, error=str(e))
            
            try:
                filename = generate_neuro_card_static(
                    result['domain'], result['title'], result['text'],
                    result['phones'], result['emails'], faq, site_id
                )
                card_url = f'/neuro/{filename}'
            except Exception as e:
                log_event('pipeline_card_error', site_id=site_id, user_id=user_id, error=str(e))
            
            try:
                supabase.table('sites').update({
                    'faq': json_module.dumps(faq, ensure_ascii=False),
                    'faq_count': len(faq),
                    'neuro_card_url': card_url,
                    'neuro_card_active': bool(faq and card_url)
                }).eq('id', site_id).execute()
                log_event('pipeline_completed', site_id=site_id, user_id=user_id)
            except Exception as e:
                log_event('pipeline_update_error', site_id=site_id, user_id=user_id, error=str(e))
        
        Thread(target=run_pipeline, args=(url, site_id, result, session['user_id']), daemon=True).start()

        log_event('site_added', site_id=site_id, user_id=session['user_id'])
        flash('Сайт добавлен! Индексация займёт 1-2 минуты.', 'success')
        return redirect(url_for('auth.dashboard'))

    return render_template('pages/add_site.html')

@auth_bp.route('/dashboard/sites/<site_id>')
@login_required
def site_card(site_id):
    """Карточка сайта: FAQ, код виджета, нейро-карточка."""
    site = supabase.table('sites').select('*').eq('id', site_id).eq('user_id', session['user_id']).execute()
    if not site.data:
        flash('Сайт не найден', 'error')
        return redirect(url_for('auth.dashboard'))

    site_data = site.data[0]
    # Парсим faq один раз
    faq_raw = site_data.get('faq', '[]')
    if isinstance(faq_raw, str):
        try:
            site_data['faq_list'] = json_module.loads(faq_raw)
        except:
            site_data['faq_list'] = []
    else:
        site_data['faq_list'] = faq_raw if faq_raw else []
    site_data['faq_count'] = len(site_data['faq_list'])
    # Контакты
    contacts_raw = site_data.get('contacts', '{}')
    if isinstance(contacts_raw, str):
        try:
            site_data['contacts'] = json_module.loads(contacts_raw)
        except:
            site_data['contacts'] = {}
    return render_template('pages/site_card.html', site=site_data)


@auth_bp.route('/dashboard/sites/<site_id>/delete', methods=['POST'])
@login_required
def delete_site(site_id):
    site = supabase.table('sites').select('*').eq('id', site_id).eq('user_id', session['user_id']).execute()
    if not site.data:
        flash('Сайт не найден', 'error')
        return redirect(url_for('auth.dashboard'))
    
    supabase.table('sites').delete().eq('id', site_id).execute()
    supabase.table('knowledge_chunks').delete().eq('site_id', site_id).execute()
    supabase.table('extracted_entities').delete().eq('site_id', site_id).execute()
    log_event('site_deleted', site_id=site_id, user_id=session['user_id'])
    flash('Сайт удалён', 'success')
    return redirect(url_for('auth.dashboard'))

@auth_bp.route('/dashboard/settings', methods=['GET', 'POST'])
@login_required
def settings():
    """Настройки профиля: ключи Яндекса, тариф."""
    if request.method == 'POST':
        api_key = request.form.get('yandex_api_key', '').strip()
        folder_id = request.form.get('yandex_folder_id', '').strip()
        supabase.table('users').update({
            'yandex_api_key_encrypted': api_key,
            'yandex_folder_id_encrypted': folder_id
        }).eq('id', session['user_id']).execute()
        flash('Настройки сохранены', 'success')
        return redirect(url_for('auth.dashboard'))

    user = supabase.table('users').select('*').eq('id', session['user_id']).execute()
    return render_template('pages/settings.html', user=user.data[0] if user.data else {})
