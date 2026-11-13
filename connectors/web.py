import io
import re
import logging
import requests
import feedparser
from bs4 import BeautifulSoup
from datetime import datetime
from typing import List, Dict, Any, Optional
from urllib.parse import urljoin, urlparse
from .base import BaseConnector, NormalizedItem

try:
    import trafilatura
    HAS_TRAFILATURA = True
except ImportError:
    HAS_TRAFILATURA = False

logger = logging.getLogger(__name__)

class UniversalWebConnector(BaseConnector):
    """
    Universal Website, RSS/Atom, and PDF Document Ingestion Engine.
    Implements intelligent multi-tier extraction:
      - Tier 1: RSS/Atom feeds with smart feed pagination & Level-2 detail crawling.
      - Tier 2: Two-level HTML crawling (Listing -> Detail Page) via Trafilatura & BeautifulSoup.
      - Tier 3: Government procurement table parser extracting table rows, columns, & tender PDFs.
      - Tier 4: PDF document text extraction for tenders and announcements via pypdf.
    """

    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 MarketIntel/2.0"

    def __init__(self, account=None):
        super().__init__(account)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': self.USER_AGENT,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9,am;q=0.8',
        })

    def authenticate(self) -> bool:
        self.is_authenticated = True
        return True

    def validate_connection(self) -> Dict[str, Any]:
        return {
            'status': 'ok',
            'authenticated': True,
            'message': 'Universal Web Connector ready for RSS, HTML scraping, Table extraction, and PDF extraction.',
            'capabilities': ['rss_atom', 'html_selectors', 'two_level_crawling', 'table_extraction', 'pdf_extraction', 'trafilatura_cleaner']
        }

    def fetch_new_items(self, source, since: Optional[datetime] = None, limit: int = 30) -> List[NormalizedItem]:
        url = source.endpoint_url.strip()
        source_type = source.source_type
        config = source.config or {}

        items = []
        try:
            clean_url = url.split('?')[0].rstrip('/')
            is_feed = (
                source_type in ('feed', 'rss') or
                clean_url.endswith('.xml') or
                clean_url.endswith('/feed') or
                clean_url.endswith('/rss') or
                clean_url.endswith('/atom')
            )

            # 1. RSS / Atom Feed Handling
            if is_feed:
                items = self._fetch_feed(url, source_name=source.name, config=config, since=since, limit=limit)
            # 2. PDF Document Handling
            elif clean_url.lower().endswith('.pdf'):
                item = self._fetch_pdf(url, source.name, config=config)
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

    def _fetch_detail_content(self, url: str, ssl_verify: bool = True) -> Optional[str]:
        """
        Visits an individual article or tender detail page and extracts the clean
        main content using Trafilatura, stripping menus, sidebars, and ads.
        """
        if not url or not url.startswith('http'):
            return None

        try:
            resp = self.session.get(url, timeout=12, verify=ssl_verify)
            if resp.status_code == 200:
                # 1. Try Trafilatura for clean main article & table extraction
                if HAS_TRAFILATURA:
                    try:
                        clean_text = trafilatura.extract(resp.text, include_tables=True, include_links=True)
                        if clean_text and len(clean_text.strip()) > 80:
                            return clean_text.strip()
                    except Exception as te:
                        logger.debug(f"Trafilatura failed on {url}: {te}")

                # 2. BeautifulSoup clean main container fallback
                soup = BeautifulSoup(resp.content, 'html.parser')
                for tag in soup(['script', 'style', 'nav', 'header', 'footer', 'aside', 'form', 'noscript']):
                    tag.decompose()

                main = soup.select_one(
                    'article, main, .entry-content, .node__content, .post-content, '
                    '#content, .content, .region-content, .detail-content, .tender-details'
                )
                target = main if main else soup.body
                if target:
                    return target.get_text(separator=' ', strip=True)
        except Exception as e:
            logger.debug(f"Detail fetch failed for {url}: {e}")

        return None

    def _fetch_feed(self, url: str, source_name: str, config: dict, since: Optional[datetime] = None, limit: int = 30) -> List[NormalizedItem]:
        """Parses RSS/Atom feeds with smart pagination and two-level detail enrichment."""
        ssl_verify = config.get('ssl_verify', True)
        max_pages = config.get('max_pages', 1)
        crawl_detail = config.get('crawl_detail', True) # Default to true to fix teasers like MOH

        all_entries = []
        
        # Paginate feeds (e.g. ?paged=1, ?paged=2 for WordPress / PPA)
        for page_num in range(1, max_pages + 1):
            page_url = url
            if page_num > 1:
                delimiter = '&' if '?' in url else '?'
                page_url = f"{url}{delimiter}paged={page_num}"

            try:
                resp = self.session.get(page_url, timeout=12, verify=ssl_verify)
                if resp.status_code != 200:
                    break
                feed = feedparser.parse(resp.text)
                if not feed.entries:
                    break
                all_entries.extend(feed.entries)
                if len(all_entries) >= limit:
                    break
            except Exception as e:
                logger.debug(f"Feed pagination stop on page {page_num} of {url}: {e}")
                break

        items = []
        for entry in all_entries[:limit]:
            title = entry.get('title', 'Untitled Feed Item')
            link = entry.get('link', url)
            entry_id = entry.get('id', link)
            author = entry.get('author', source_name)

            content = entry.get('summary', '') or entry.get('description', '')
            if entry.get('content'):
                content = entry['content'][0].get('value', content)

            soup = BeautifulSoup(content, 'html.parser')
            clean_text = soup.get_text(separator=' ', strip=True)

            pub_date = None
            if entry.get('published_parsed'):
                pub_date = datetime(*entry.published_parsed[:6])

            if since and pub_date and pub_date <= since:
                continue

            # Two-Level Crawling: If content is just a short teaser (< 300 chars like MOH),
            # or if crawl_detail is explicitly requested, visit the detail page!
            if crawl_detail and (len(clean_text) < 300 or config.get('force_detail_crawl', False)):
                detail_body = self._fetch_detail_content(link, ssl_verify=ssl_verify)
                if detail_body and len(detail_body) > len(clean_text):
                    clean_text = detail_body

            items.append(NormalizedItem(
                external_id=f"rss_{abs(hash(entry_id))}",
                title=title[:200],
                content_text=clean_text or title,
                url=link,
                author=author,
                published_at=pub_date,
                media_urls=[],
                raw_payload={'title': title, 'link': link, 'id': entry_id},
                metadata={'feed_source': source_name}
            ))

        return items

    def _fetch_pdf(self, url: str, source_name: str, config: dict = None) -> Optional[NormalizedItem]:
        """Downloads and extracts text from a PDF document using pypdf."""
        config = config or {}
        ssl_verify = config.get('ssl_verify', True)
        try:
            import pypdf
            resp = self.session.get(url, timeout=20, verify=ssl_verify)
            if resp.status_code == 200:
                pdf_reader = pypdf.PdfReader(io.BytesIO(resp.content))
                extracted_pages = []
                for idx, page in enumerate(pdf_reader.pages[:10]):
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

    def _extract_table_items(self, soup: BeautifulSoup, url: str, source_name: str, config: dict) -> List[NormalizedItem]:
        """
        Parses government procurement & vacancy HTML tables into structured records
        with document PDF links.
        """
        items = []
        table_selector = config.get('table_selector', 'table')
        tables = soup.select(table_selector)

        for t_idx, tbl in enumerate(tables):
            rows = tbl.find_all('tr')
            if len(rows) < 2:
                continue

            # Extract header column names
            headers = [th.get_text(strip=True) for th in rows[0].find_all(['th', 'td'])]

            for r_idx, tr in enumerate(rows[1:]):
                cells = [td.get_text(strip=True) for td in tr.find_all(['td', 'th'])]
                if not any(cells):
                    continue

                links = [urljoin(url, a['href']) for a in tr.find_all('a', href=True)]
                pdf_links = [l for l in links if l.lower().endswith('.pdf') or 'download' in l.lower()]

                # Build structured representation
                row_parts = []
                for i, c in enumerate(cells):
                    header_label = headers[i] if i < len(headers) and headers[i] else f"Field_{i+1}"
                    row_parts.append(f"{header_label}: {c}")

                content_str = " | ".join(row_parts)
                title = cells[0] if cells else f"Procurement Notice #{r_idx+1}"
                if len(title) < 10 and len(cells) > 1:
                    title = f"{cells[0]} - {cells[1]}"

                item_url = links[0] if links else f"{url}#table-{t_idx+1}-row-{r_idx+1}"

                items.append(NormalizedItem(
                    external_id=f"table_{abs(hash(item_url + content_str))}",
                    title=title[:200],
                    content_text=content_str,
                    url=item_url,
                    author=source_name,
                    published_at=datetime.utcnow(),
                    media_urls=pdf_links,
                    raw_payload={'table_index': t_idx + 1, 'row_index': r_idx + 1, 'cells': cells},
                    metadata={'is_table_record': True, 'table_headers': headers}
                ))

        return items

    def _fetch_html_page(self, url: str, source_name: str, config: dict, limit: int = 15) -> List[NormalizedItem]:
        """Fetches and scrapes an HTML page with selector cards, table parsing, & Level-2 detail crawling."""
        ssl_verify = config.get('ssl_verify', True)
        crawl_detail = config.get('crawl_detail', True)
        extract_tables = config.get('extract_tables', False)
        max_pages = config.get('max_pages', 1)

        items = []
        current_url = url
        pages_crawled = 0

        while current_url and pages_crawled < max_pages:
            pages_crawled += 1
            resp = self.session.get(current_url, timeout=15, verify=ssl_verify)
            if resp.status_code != 200:
                raise Exception(f"HTTP Error {resp.status_code} fetching {current_url}")

            soup = BeautifulSoup(resp.content, 'html.parser')

            item_selector = config.get('item_selector')
            title_selector = config.get('title_selector')
            body_selector = config.get('body_selector')
            link_selector = config.get('link_selector')

            # 1. Custom CSS Selector Cards
            if item_selector:
                elements = soup.select(item_selector)[:limit]
                for el in elements:
                    t_el = el.select_one(title_selector) if title_selector else el.find(['h1', 'h2', 'h3', 'h4'])
                    title = t_el.get_text(strip=True) if t_el else "Scraped Item"

                    b_el = el.select_one(body_selector) if body_selector else el
                    content = b_el.get_text(separator=' ', strip=True) if b_el else ""

                    l_el = el.select_one(link_selector) if link_selector else el.find('a')
                    item_url = urljoin(current_url, l_el['href']) if l_el and l_el.get('href') else current_url

                    # Level-2 Crawling: Visit the detail page to get full content
                    if crawl_detail and item_url != current_url and item_url.startswith('http'):
                        detail_text = self._fetch_detail_content(item_url, ssl_verify=ssl_verify)
                        if detail_text and len(detail_text) > len(content):
                            content = detail_text

                    items.append(NormalizedItem(
                        external_id=f"web_{abs(hash(item_url + title))}",
                        title=title[:200],
                        content_text=content or title,
                        url=item_url,
                        author=source_name,
                        published_at=datetime.utcnow(),
                        media_urls=[],
                        raw_payload={'scraped_url': item_url},
                        metadata={'scraped': True, 'two_level_crawled': crawl_detail}
                    ))

            # 2. Table-Based Extraction (e.g. EPHI procurement tables)
            elif extract_tables or soup.find('table'):
                table_items = self._extract_table_items(soup, current_url, source_name, config)
                if table_items:
                    items.extend(table_items[:limit])

            # 3. Clean Single Page Article Extraction (Using Trafilatura)
            if not items:
                # Use Trafilatura to extract clean main text without nav/footer boilerplate
                clean_body = ""
                if HAS_TRAFILATURA:
                    try:
                        clean_body = trafilatura.extract(resp.text, include_tables=True, include_links=True)
                    except Exception:
                        pass

                title_el = soup.find('h1')
                title_text = title_el.get_text(strip=True) if title_el else soup.title.get_text(strip=True) if soup.title else source_name

                if not clean_body:
                    for tag in soup(['script', 'style', 'nav', 'header', 'footer', 'aside', 'form', 'noscript']):
                        tag.decompose()
                    clean_body = soup.get_text(separator=' ', strip=True)

                items.append(NormalizedItem(
                    external_id=f"web_{abs(hash(current_url))}",
                    title=title_text[:200],
                    content_text=clean_body[:25000],
                    url=current_url,
                    author=source_name,
                    published_at=datetime.utcnow(),
                    media_urls=[],
                    raw_payload={'url': current_url},
                    metadata={'single_page': True, 'trafilatura_cleaned': bool(HAS_TRAFILATURA)}
                ))

            # Check next page pagination link
            next_link_el = soup.select_one('a[rel="next"], .pagination a.next, a.next, a.page-numbers.next, li.next a')
            if next_link_el and next_link_el.get('href') and pages_crawled < max_pages:
                current_url = urljoin(current_url, next_link_el['href'])
            else:
                break

        return items

    def normalize(self, raw_data: Any) -> NormalizedItem:
        return raw_data if isinstance(raw_data, NormalizedItem) else None
