from flask import Blueprint, request, jsonify
import requests, re, os, sys, json

from shared.supabase import supabase
from shared.logger import log_event

ai_bp = Blueprint('ai', __name__)
YANDEX_API_KEY = os.environ.get('YANDEX_API_KEY', '')
YANDEX_FOLDER_ID = os.environ.get('YANDEX_FOLDER_ID', '')
if not YANDEX_API_KEY or not YANDEX_FOLDER_ID:
    print('[WARNING] YANDEX_API_KEY or YANDEX_FOLDER_ID not set — AI features disabled', file=sys.stderr, flush=True)


def generate_faq(title, text, phones, emails):
    if not YANDEX_API_KEY or not YANDEX_FOLDER_ID:
        return _fallback_faq(title, phones, emails)

    prompt = (
        f"Сгенерируй 10 вопросов и ответов для FAQ сайта \"{title}\". "
        "Используй ТОЛЬКО информацию из текста сайта. Пиши строго на русском.\n\n"
        "Верни ТОЛЬКО валидный JSON-массив без markdown-форматирования:\n"
        '[{"q": "вопрос", "a": "ответ", "category": "категория"}, ...]\n\n'
        "Категории: about, pricing, delivery, contacts, guarantees, ordering.\n"
        "Не добавляй комментарии. Не оборачивай в ```json```.\n\n"
        f"Текст сайта:\n<site_content>\n{text[:4000]}\n</site_content>"
    )

    try:
        resp = requests.post(
            "https://llm.api.cloud.yandex.net/foundationModels/v1/completion",
            headers={"Authorization": f"Api-Key {YANDEX_API_KEY}", "x-folder-id": YANDEX_FOLDER_ID},
            json={
                "modelUri": f"gpt://{YANDEX_FOLDER_ID}/yandexgpt-lite",
                "completionOptions": {"maxTokens": 1500, "temperature": 0.2},
                "messages": [
                    {"role": "system", "text": "Ты генератор FAQ. Возвращай ТОЛЬКО JSON-массив."},
                    {"role": "user", "text": prompt}
                ]
            },
            timeout=30
        )
        if resp.status_code != 200:
            log_event('FAQ_API_ERROR', status=resp.status_code, body=resp.text[:200])
            return _fallback_faq(title, phones, emails)
        data = resp.json()
        if "result" in data:
            full_text = data["result"]["alternatives"][0]["message"]["text"]
            return _parse_faq_json(full_text, title, phones, emails)
    except requests.Timeout:
        log_event("FAQ_TIMEOUT", data={"error": "YandexGPT timeout"})
    except requests.ConnectionError:
        log_event("FAQ_CONNECTION_ERROR", data={"error": "YandexGPT connection failed"})
    except Exception as e:
        log_event("FAQ_FAILED", data={"error": str(e)})

    return _fallback_faq(title, phones, emails)


def _parse_faq_json(raw_text, title, phones, emails):
    clean = raw_text.strip()
    if clean.startswith('```'):
        clean = re.sub(r'^```(?:json)?\s*', '', clean)
        clean = re.sub(r'\s*```$', '', clean)
        clean = clean.strip()
    try:
        faq = json.loads(clean)
        if isinstance(faq, list) and len(faq) > 0 and all('q' in i and 'a' in i for i in faq):
            return faq[:10]
    except (json.JSONDecodeError, ValueError) as e:
        log_event('FAQ_JSON_PARSE_ERROR', error=str(e))
    return _parse_faq_regex(raw_text, title, phones, emails)


def _parse_faq_regex(raw_text, title, phones, emails):
    qa_list = []
    lines = raw_text.split('\n')
    current_q = None
    current_a = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        q_match = re.match(r'(?:Вопрос|Q)\s*[:.]?\s*(.*)', line, re.IGNORECASE)
        a_match = re.match(r'(?:Ответ|A)\s*[:.]?\s*(.*)', line, re.IGNORECASE)
        if q_match:
            if current_q and current_a:
                qa_list.append({'q': current_q, 'a': ' '.join(current_a)})
            current_q = q_match.group(1).strip()
            current_a = []
        elif a_match:
            if current_q:
                current_a.append(a_match.group(1).strip())
        else:
            if current_q and line:
                current_a.append(line)
    if current_q and current_a:
        qa_list.append({'q': current_q, 'a': ' '.join(current_a)})
    if qa_list:
        return qa_list[:10]
    return _fallback_faq(title, phones, emails)


def _fallback_faq(title, phones, emails):
    faq = [
        {'q': 'Чем вы занимаетесь?', 'a': f'{title} — мы работаем для вас. Подробнее на сайте или по телефону.'},
        {'q': 'Почему вам доверяют?', 'a': f'Компания {title} дорожит репутацией. Ознакомьтесь с отзывами клиентов на сайте.'},
    ]
    if phones:
        faq.append({'q': 'Как с вами связаться?', 'a': f'Позвоните: {phones[0]}'})
    if emails:
        faq.append({'q': 'Куда написать?', 'a': f'Email: {emails[0]}'})
    faq.append({'q': 'Где посмотреть цены?', 'a': 'Цены указаны на сайте или уточняйте по телефону.'})
    return faq


@ai_bp.route('/api/generate-faq', methods=['POST'])
def api_generate_faq():
    data = request.get_json()
    if not data or not data.get('title') or not data.get('text'):
        return jsonify({'success': False, 'message': 'Нужны title и text'})
    faq = generate_faq(data['title'], data['text'], data.get('phones',[]), data.get('emails',[]))
    log_event('faq_generated', site_id=data.get('site_id'))
    return jsonify({'faq': faq})
