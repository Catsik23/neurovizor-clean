"""
Глубокий парсинг сайта — собирает ВСЕ URL без ограничений.
"""
import requests, re, time
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from collections import deque

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; NeurovizorBot/1.0; +https://neurovizor.ru)'
}

def get_all_urls_deep(start_url: str, max_pages: int = 0) -> dict:
    """
    Обходит сайт и собирает ВСЕ URL.
    max_pages=0 — без ограничений.
    Возвращает {url: link_text}.
    """
    base_domain = f"{urlparse(start_url).scheme}://{urlparse(start_url).netloc}"
    visited = set()
    queue = deque([start_url])
    all_urls = {}
    
    while queue:
        if max_pages > 0 and len(visited) >= max_pages:
            break
        
        current_url = queue.popleft()
        if current_url in visited:
            continue
        visited.add(current_url)
        
        try:
            resp = requests.get(current_url, headers=HEADERS, timeout=10, allow_redirects=True)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            for a in soup.find_all('a', href=True):
                href = a.get('href', '').strip()
                text = a.get_text(strip=True)[:80]
                if not href or not text:
                    continue
                full_url = urljoin(current_url, href)
                # Только внутренние ссылки, убираем якоря и параметры
                if base_domain in full_url and '#' not in full_url and '?' not in full_url:
                    if full_url not in all_urls:
                        all_urls[full_url] = text
                    if full_url not in visited:
                        queue.append(full_url)
            
            if len(all_urls) % 50 == 0:
                print(f'  [{len(all_urls)} URLs found, {len(visited)} pages visited]', flush=True)
            time.sleep(0.3)  # щадящий режим
        
        except Exception as e:
            print(f'  [ERROR] {current_url}: {e}', flush=True)
            continue
    
    print(f'\nTotal: {len(all_urls)} URLs from {len(visited)} pages')
    return all_urls
