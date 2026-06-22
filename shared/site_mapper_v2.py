"""
Site Mapper v2 — AI возвращает URL + русские названия. Без retry.
"""
import requests, re, json as _json
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from collections import deque

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; NeurovizorBot/1.0; +https://neurovizor.ru)'
}

def get_all_urls(start_url: str, max_pages: int = 15) -> dict:
    base_domain = f"{urlparse(start_url).scheme}://{urlparse(start_url).netloc}"
    visited = set()
    queue = deque([start_url])
    all_urls = {}
    while queue and len(visited) < max_pages:
        current_url = queue.popleft()
        if current_url in visited:
            continue
        visited.add(current_url)
        try:
            resp = requests.get(current_url, headers=HEADERS, timeout=10, allow_redirects=True)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')
            for a in soup.find_all('a', href=True):
                href = a.get('href', '').strip()
                text = a.get_text(strip=True)[:80]
                if not href or not text:
                    continue
                full_url = urljoin(current_url, href)
                if base_domain in full_url and full_url not in all_urls:
                    all_urls[full_url] = text
                    if full_url not in visited and len(visited) + len(queue) < max_pages:
                        queue.append(full_url)
        except Exception as e:
            print(f'[MAPPER v2] Error on {current_url}: {e}', flush=True)
    return all_urls


def _filter_batch_v2(urls_batch: dict, site_type: str) -> list:
    from shared.ai_client import ask_yandexgpt
    type_prompts = {
        'shop': 'интернет-магазина (каталог, категории товаров, корзина, доставка, оплата, контакты)',
        'service': 'сервиса услуг (услуги, цены, запись, контакты)',
        'food': 'ресторана/кафе (меню, корзина, доставка, контакты)',
        'b2b': 'B2B-компании (решения, продукты, контакты)',
        'general': 'сайта (каталог, услуги, корзина, доставка, оплата, контакты)'
    }
    clean_batch = {}
    for u, t in urls_batch.items():
        if '#' in u or '?' in u:
            continue
        if not t or t in ['«', '»', '0', '2', '3', '4', '5', '6', '7', '8', '9', '10']:
            continue
        clean_batch[u] = t
    if not clean_batch:
        return []
    urls_lines = []
    for u, t in clean_batch.items():
        clean_t = re.sub(r'[^\w\s\-]', '', t)[:50].strip()
        if not clean_t:
            clean_t = u.split('/')[-2] or u.split('/')[-1] or 'page'
        urls_lines.append(f'{clean_t} | {u}')
    urls_text = '\n'.join(urls_lines)
    prompt = f"""Проанализируй карту сайта {type_prompts.get(site_type, type_prompts['general'])}.
ОСТАВЬ: категории товаров, каталог, корзину, доставку, оплату, контакты.
УБЕРИ: отдельные товары с артикулами, блог, истории, отзывы, политики, вход.
Для каждого URL придумай короткое русское название (1-3 слова).
Верни ТОЛЬКО JSON-массив объектов: [{{"url": "url1", "title": "Название"}}, ...]

{urls_text}"""
    try:
        ai_result = ask_yandexgpt(prompt, "", "Возвращаешь JSON-массив объектов с url и title.")
        clean = re.sub(r'^```(?:json)?\s*', '', ai_result.strip())
        first_bracket = clean.find('[')
        if first_bracket < 0:
            return []
        clean = clean[first_bracket:]
        depth = 0
        end_pos = 0
        for i, ch in enumerate(clean):
            if ch == '[': depth += 1
            elif ch == ']':
                depth -= 1
                if depth == 0:
                    end_pos = i + 1
                    break
        if end_pos > 0:
            clean = clean[:end_pos]
        selected = _json.loads(clean)
        if isinstance(selected, list) and len(selected) > 0 and 'url' in selected[0]:
            valid = [item for item in selected if item.get('url') in urls_batch]
            if valid:
                return valid
    except:
        pass
    return []


def filter_golden_urls_v2(urls: dict, site_type: str = 'general') -> list:
    from urllib.parse import urlparse
    groups = {}
    for url, title in urls.items():
        path = urlparse(url).path.strip('/')
        root_key = path.split('/')[0] if path else '/'
        if root_key not in groups:
            groups[root_key] = {}
        groups[root_key][url] = title
    all_selected = []
    for group_name, group_urls in groups.items():
        items = list(group_urls.items())
        for i in range(0, len(items), 20):
            batch = dict(items[i:i+20])
            all_selected.extend(_filter_batch_v2(batch, site_type))
    valid = [item for item in all_selected if item.get('url') in urls]
    if valid:
        return valid
    return [{"url": u, "title": t if isinstance(t, str) and not t.startswith('http') else u.split('/')[-1]} 
            for u, t in urls.items() if u.count('/') <= 3 and '?' not in u and '#' not in u ]
