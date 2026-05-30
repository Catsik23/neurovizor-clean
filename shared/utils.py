import re, requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin

def parse_site(url):
    """Парсит сайт, возвращает словарь с domain, title, text, phones, emails."""
    if not url.startswith('http'): url = 'https://' + url
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        response = requests.get(url, headers=headers, timeout=15)
    except requests.RequestException:
        return {'success': False, 'message': f'Failed to fetch {url}'}
    response.encoding = response.apparent_encoding
    soup = BeautifulSoup(response.text, 'html.parser')
    title = soup.title.string.strip() if soup.title else 'Site'
    domain = urlparse(url).netloc
    html = response.text
    text = soup.get_text(separator='\n', strip=True)
    phones = re.findall(r'[\+\(]?[1-9][0-9 .\-\(\)]{8,}[0-9]', text)
    emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)
    return {'success': True, 'domain': domain, 'title': title[:100], 'text': text[:12000], 'html': html[:12000], 'phones': phones[:2], 'emails': emails[:2]}

def detect_site_type(text):
    """Определяет тип сайта: shop/service/b2b/food/general."""
    t = text.lower()
    if any(w in t for w in ['купить','корзина','товар','каталог']): return 'shop'
    if any(w in t for w in ['услуга','запись','приём','консультация']): return 'service'
    if any(w in t for w in ['api','интеграция','платформа','решение']): return 'b2b'
    if any(w in t for w in ['меню','ресторан','блюд','кафе']): return 'food'
    return 'general'

def chunk_text(text, source_url='', chunk_size=150, overlap=30):
    """Разбивает текст на чанки с перекрытием. Возвращает список словарей."""
    if not text or not text.strip():
        return []
    text = re.sub(r'\s+', ' ', text).strip()
    words = text.split()
    step = chunk_size - overlap
    if len(words) <= chunk_size:
        return [{"text": text, "source_url": source_url, "chunk_index": 0, "chunk_type": "full", "position": 0}]
    chunks = []
    for i in range(0, len(words), step):
        chunk_words = words[i:i + chunk_size]
        if len(chunk_words) < 20:
            break
        chunk_text_val = ' '.join(chunk_words)
        chunk_type = "paragraph"
        if chunk_text_val.startswith(('#', '##', '###')):
            chunk_type = "title"
        elif chunk_text_val.startswith(('-', '*', '•', '1.', '2.', '3.')):
            chunk_type = "list"
        elif '|' in chunk_text_val and '\n' in chunk_text_val:
            chunk_type = "table"
        chunks.append({"text": chunk_text_val, "source_url": source_url, "chunk_index": len(chunks), "chunk_type": chunk_type, "position": i})
    return chunks

def ai_visibility_audit(text, html=''):
    """AI Visibility Audit: оценка видимости сайта для нейросетей (0-100)."""
    score, details = 0, []
    if re.search(r'(?:вопрос|ответ|faq|част)', text, re.IGNORECASE): score += 25; details.append('FAQ found')
    else: details.append('No FAQ')
    if re.search(r'application/ld\+json', html): score += 25; details.append('Schema.org found')
    else: details.append('No Schema.org')
    if re.findall(r'[\+\(]?[1-9][0-9 .\-\(\)]{8,}[0-9]', text): score += 15; details.append('Contacts found')
    else: details.append('No contacts')
    if len(text) > 3000: score += 20; details.append('Enough content')
    else: details.append('Not enough content')
    return {'score': min(score, 100), 'details': details}

def extract_entities(text, domain):
    """Извлекает факты: телефоны, email, цены, адреса."""
    entities = []
    for phone in re.findall(r'[\+\(]?[1-9][0-9 .\-\(\)]{8,}[0-9]', text)[:3]:
        entities.append({'type':'phone','value':phone,'confidence':0.95})
    for email in re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)[:2]:
        entities.append({'type':'email','value':email,'confidence':0.95})
    for price in re.findall(r'\d[\d\s]*\s*(?:₽|руб|р\.)', text)[:5]:
        entities.append({'type':'price','value':price,'confidence':0.8})
    return entities

def classify_chunk_topic(chunk):
    """Определяет тему чанка: delivery/pricing/contacts/trust/products/about."""
    t = chunk.lower()
    if any(w in t for w in ['доставка','самовывоз','почта']): return 'delivery'
    if any(w in t for w in ['цена','стоимость','руб','оплата']): return 'pricing'
    if any(w in t for w in ['контакт','телефон','адрес']): return 'contacts'
    if any(w in t for w in ['гарант','возврат','качеств']): return 'trust'
    if any(w in t for w in ['услуга','товар','продукт']): return 'products'
    if any(w in t for w in ['компания','мы','команд']): return 'about'
    return 'general'
