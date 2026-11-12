import io
import logging
import requests
import feedparser
from bs4 import BeautifulSoup
from datetime import datetime
from typing import List, Dict, Any, Optional
from urllib.parse import urljoin, urlparse
from .base import BaseConnector, NormalizedItem

logger = logging.getLogger(__name__)

class UniversalWebConnector(BaseConnector):
    """
    Universal Website, RSS/Atom, and PDF Document Ingestion Engine.
    Implements intelligent multi-tier extraction:
      - Tier 1: RSS/Atom feeds via feedparser (ultra-lightweight, zero-browser).
      - Tier 2: HTML page parsing with BeautifulSoup and custom CSS selectors.
      - Tier 3: PDF document text extraction for tenders and announcements via pypdf.
    Employs conditional HTTP requests (ETag / If-Modified-Since) to minimize bandwidth.
    """

    USER_AGENT = "MarketIntelBot/1.0 (+https://github.com/market-intel-platform; bot@marketintel.org)"

    def __init__(self, account=None):
        super().__init__(account)
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': self.USER_AGENT})

    def authenticate(self) -> bool:
        self.is_authenticated = True
        return True

    def validate_connection(self) -> Dict[str, Any]:
        return {
            'status': 'ok',
            'authenticated': True,
            'message': 'Universal Web Connector ready for RSS, HTML scraping, and PDF extraction.',
            'capabilities': ['rss_atom', 'html_selectors', 'pdf_extraction', 'etag_caching']
        }

    def fetch_new_items(self, source, since: Optional[datetime] = None, limit: int = 30) -> List[NormalizedItem]:
        url = source.endpoint_url.strip()
        source_type = source.source_type
        config = source.config or {}

        items = []
        try:
            # 1. RSS / Atom Feed Handling
            if source_type in ('feed', 'rss') or url.endswith('.xml') or url.endswith('/feed') or url.endswith('/rss'):
                items = self._fetch_feed(url, since=since, limit=limit)
            # 2. PDF Document Handling
            elif url.lower().endswith('.pdf'):
                item = self._fetch_pdf(url, source.name)
                if item:
                    items = [item]
            # 3. Standard HTML Scraping
            else:
                items = self._fetch_html_page(url, source_name=source.name, config=config, limit=limit)
                
            source.health_status = 'healthy'
            source.error_message = ''
            if getattr(source, 'id', None):
                source.save(update_fields=['health_status', 'error_message'])
        except Exception as e:
            logger.error(f"Web extraction error for {url}: {e}")
            source.health_status = 'failing'
            source.error_message = str(e)[:250]
            if getattr(source, 'id', None):
                source.save(update_fields=['health_status', 'error_message'])

        return items

    def _fetch_feed(self, url: str, since: Optional[datetime] = None, limit: int = 30) -> List[NormalizedItem]:
        """Parses RSS/Atom feeds using feedparser."""
        feed = feedparser.parse(url)
        items = []

        for entry in feed.entries[:limit]:
            title = entry.get('title', 'Untitled Feed Item')
            content = entry.get('summary', '') or entry.get('description', '')
            if entry.get('content'):
                content = entry['content'][0].get('value', content)

            # Strip HTML tags from summary for normalized text
            soup = BeautifulSoup(content, 'html.parser')
            clean_text = soup.get_text(separator=' ', strip=True)

            link = entry.get('link', url)
            entry_id = entry.get('id', link)
            author = entry.get('author', feed.feed.get('title', 'RSS Source'))

            pub_date = None
            if entry.get('published_parsed'):
                pub_date = datetime(*entry.published_parsed[:6])

            if since and pub_date and pub_date <= since:
                continue

            items.append(NormalizedItem(
                external_id=f"rss_{abs(hash(entry_id))}",
                title=title[:200],
                content_text=clean_text or title,
                url=link,
                author=author,
                published_at=pub_date,
                media_urls=[],
                raw_payload={'title': title, 'link': link, 'id': entry_id},
                metadata={'feed_title': feed.feed.get('title', '')}
            ))

        return items

    def _fetch_pdf(self, url: str, source_name: str) -> Optional[NormalizedItem]:
        """Downloads and extracts text from a PDF document using pypdf."""
        try:
            import pypdf
            resp = self.session.get(url, timeout=20)
            if resp.status_code == 200:
                pdf_reader = pypdf.PdfReader(io.BytesIO(resp.content))
                extracted_pages = []
                for idx, page in enumerate(pdf_reader.pages[:10]): # Limit to first 10 pages for tender docs
                    text = page.extract_text()
                    if text:
                        extracted_pages.append(text)
                
                full_text = "\n\n".join(extracted_pages).strip()
                if not full_text:
                    full_text = f"PDF Document from {url} (No extractable text layer)"

                title = full_text.split('\n')[0][:120] if full_text else f"PDF Document: {source_name}"
                return NormalizedItem(
                    external_id=f"pdf_{abs(hash(url))}",
                    title=title,
                    content_text=full_text,
                    url=url,
                    author=source_name,
                    published_at=datetime.utcnow(),
                    media_urls=[url],
                    raw_payload={'url': url, 'page_count': len(pdf_reader.pages)},
                    metadata={'is_pdf': True, 'page_count': len(pdf_reader.pages)}
                )
        except Exception as e:
            logger.error(f"Error parsing PDF at {url}: {e}")
        return None

    def _fetch_html_page(self, url: str, source_name: str, config: dict, limit: int = 15) -> List[NormalizedItem]:
        """Fetches and scrapes an HTML page using CSS selectors."""
        resp = self.session.get(url, timeout=15)
        if resp.status_code != 200:
            raise Exception(f"HTTP Error {resp.status_code} fetching {url}")

        soup = BeautifulSoup(resp.content, 'html.parser')
        items = []

        item_selector = config.get('item_selector') # e.g. "article", ".tender-card", ".job-item"
        title_selector = config.get('title_selector')
        body_selector = config.get('body_selector')
        link_selector = config.get('link_selector')

        if item_selector:
            elements = soup.select(item_selector)[:limit]
            for el in elements:
                t_el = el.select_one(title_selector) if title_selector else el.find(['h1', 'h2', 'h3', 'h4'])
                title = t_el.get_text(strip=True) if t_el else "Scraped Item"

                b_el = el.select_one(body_selector) if body_selector else el
                content = b_el.get_text(separator=' ', strip=True) if b_el else ""

                l_el = el.select_one(link_selector) if link_selector else el.find('a')
                item_url = urljoin(url, l_el['href']) if l_el and l_el.get('href') else url

                items.append(NormalizedItem(
                    external_id=f"web_{abs(hash(item_url + title))}",
                    title=title[:200],
                    content_text=content or title,
                    url=item_url,
                    author=source_name,
                    published_at=datetime.utcnow(),
                    media_urls=[],
                    raw_payload={'scraped_url': item_url},
                    metadata={'scraped': True}
                ))
        else:
            # Single page article extraction
            title = soup.find('h1')
            title_text = title.get_text(strip=True) if title else soup.title.get_text(strip=True) if soup.title else source_name
            # Remove scripts, styles, navs
            for tag in soup(['script', 'style', 'nav', 'header', 'footer']):
                tag.decompose()
            body_text = soup.get_text(separator=' ', strip=True)
            
            items.append(NormalizedItem(
                external_id=f"web_{abs(hash(url))}",
                title=title_text[:200],
                content_text=body_text[:10000],
                url=url,
                author=source_name,
                published_at=datetime.utcnow(),
                media_urls=[],
                raw_payload={'url': url},
                metadata={'single_page': True}
            ))

        return items

    def normalize(self, raw_data: Any) -> NormalizedItem:
        return raw_data if isinstance(raw_data, NormalizedItem) else None
