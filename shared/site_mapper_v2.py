"""
Site Mapper v2 — с заголовком каждой страницы для AI-контекста.
"""
import requests, re
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from collections import deque

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; NeurovizorBot/1.0; +https://neurovizor.ru)'
}

def _get_title(url: str) -> str:
    """Загружает страницу и возвращает её заголовок."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10, allow_redirects=True)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        return soup.title.string.strip() if soup.title else ''
    except:
        return ''


def get_all_urls_with_titles(start_url: str, max_pages: int = 5) -> dict:
    """
    Обходит сайт, собирает URL и заголовок каждой страницы.
    Возвращает {url: {'link_text': str, 'page_title': str}}.
    """
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
                link_text = a.get_text(strip=True)[:80]
                if not href or not link_text:
                    continue
                full_url = urljoin(current_url, href)
                if base_domain in full_url and full_url not in all_urls:
                    all_urls[full_url] = {
                        'link_text': link_text,
                        'page_title': ''
                    }
                    if full_url not in visited and len(visited) + len(queue) < max_pages:
                        queue.append(full_url)
        except Exception as e:
            print(f'[MAPPER v2] Error on {current_url}: {e}', flush=True)
    
    # Второй проход: загружаем заголовки для всех URL
    print(f'[MAPPER v2] Fetching titles for {len(all_urls)} URLs...')
    for i, url in enumerate(all_urls):
        if i % 20 == 0:
            print(f'  {i}/{len(all_urls)}...')
        try:
            all_urls[url]['page_title'] = _get_title(url)[:100]
        except:
            all_urls[url]['page_title'] = all_urls[url].get('link_text', '')
    
    return all_urls
