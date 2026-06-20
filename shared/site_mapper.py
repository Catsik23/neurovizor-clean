"""
Построение карты сайта — извлекает все URL и строит дерево страниц.
"""
import requests, re
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from collections import deque

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; NeurovizorBot/1.0; +https://neurovizor.ru)'
}

def get_all_urls(start_url: str, max_pages: int = 5) -> dict:
    """Обходит сайт и собирает все URL с текстами ссылок. Возвращает {url: title}."""
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
            print(f'[MAPPER] Error on {current_url}: {e}', flush=True)
    return all_urls


def build_site_tree(urls: dict) -> dict:
    """Строит дерево сайта из {url: title}."""
    tree = {}
    for url, title in urls.items():
        path = urlparse(url).path.strip('/')
        if not path:
            tree['/'] = {'title': title, 'url': url, 'children': {}}
            continue
        segments = path.split('/')
        current = tree
        for i, seg in enumerate(segments):
            if seg not in current:
                current[seg] = {'title': '', 'url': '', 'children': {}}
            if i == len(segments) - 1:
                current[seg]['title'] = title
                current[seg]['url'] = url
            current = current[seg]['children']
    return tree


def print_tree(tree: dict, indent: int = 0):
    """Выводит дерево сайта в консоль."""
    for name, node in sorted(tree.items()):
        title = node.get('title', '')[:40]
        print(f"{'  ' * indent}📁 {name}" + (f" — {title}" if title else ""))
        if node.get('children'):
            print_tree(node['children'], indent + 1)


def _filter_batch(urls_batch: dict, site_type: str) -> list:
    """AI-фильтр для одного батча URL. Возвращает список золотых URL."""
    from shared.ai_client import ask_yandexgpt
    import json as _json
    
    type_prompts = {
        'shop': 'интернет-магазина (каталог, категории товаров, доставка, оплата, контакты)',
        'service': 'сервиса услуг (услуги, цены, запись, контакты)',
        'food': 'ресторана/кафе (меню, доставка, контакты)',
        'b2b': 'B2B-компании (решения, продукты, контакты)',
        'general': 'сайта (каталог, услуги, доставка, оплата, контакты)'
    }
    
    # Предварительно фильтруем мусор
    clean_batch = {}
    for u, t in urls_batch.items():
        # Пропускаем якоря, параметры запроса, пустые названия
        if '#' in u or '?' in u:
            continue
        if not t or t in ['«', '»', '0', '2', '3', '4', '5', '6', '7', '8', '9', '10']:
            continue
        clean_batch[u] = t
    if not clean_batch:
        return []
    urls_lines = []
    for u, t in clean_batch.items():
        # Убираем все спецсимволы, оставляем только буквы, цифры, пробелы, дефис
        clean_t = re.sub(r'[^\w\s\-]', '', t)
        clean_t = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', clean_t)  # убираем control chars
        clean_t = clean_t[:50].strip()
        if not clean_t:
            clean_t = u.split('/')[-2] or u.split('/')[-1] or 'page'
        urls_lines.append(f'{clean_t} | {u}')
    urls_text = '\n'.join(urls_lines)
    
    prompt = f"""Проанализируй карту сайта {type_prompts.get(site_type, type_prompts['general'])}.
ОСТАВЬ: категории товаров, каталог, доставку, оплату, контакты.
УБЕРИ: отдельные товары с артикулами, блог, истории, отзывы, политики, корзину, вход.
Верни ТОЛЬКО JSON-массив URL: ["url1", "url2", ...]

{urls_text}"""
    
    for attempt in range(3):
        try:
            ai_result = ask_yandexgpt(prompt, "", "Возвращаешь ТОЛЬКО JSON-массив URL.", max_tokens=4000, temperature=0)
            clean = re.sub(r'^```(?:json)?\s*|\s*```$', '', ai_result.strip())
            clean = re.sub(r'[--]', '', clean)  # убираем control chars из ответа AI
            if not clean or not clean.startswith('['):
                print(f'[MAPPER] Retry {attempt+1}: invalid response', flush=True)
                continue
            selected = _json.loads(clean)
            if isinstance(selected, list):
                return selected
        except Exception as e:
            print(f'[MAPPER] Retry {attempt+1}: {e}', flush=True)
    return []


def filter_golden_urls(urls: dict, site_type: str = 'general') -> list:
    """AI-фильтр с группировкой URL по веткам дерева."""
    from urllib.parse import urlparse
    
    # Группируем по первой ветке пути
    groups = {}
    for url, title in urls.items():
        path = urlparse(url).path.strip('/')
        root_key = path.split('/')[0] if path else '/'
        if root_key not in groups:
            groups[root_key] = {}
        groups[root_key][url] = title
    
    all_selected = []
    
    for group_name, group_urls in groups.items():
        if len(group_urls) > 20:
            items = list(group_urls.items())
            for i in range(0, len(items), 20):
                batch = dict(items[i:i+20])
                all_selected.extend(_filter_batch(batch, site_type))
        else:
            all_selected.extend(_filter_batch(group_urls, site_type))
    
    if all_selected:
        return all_selected
    
    # Fallback
    return [u for u in urls.keys() if u.count('/') <= 3 and '?' not in u and '#' not in u and '/tovar/' not in u]
