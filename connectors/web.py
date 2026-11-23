import io
import re
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import feedparser
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import List, Dict, Any, Optional
from urllib.parse import urljoin, urlparse
from django.utils import timezone
from .base import BaseConnector, NormalizedItem

try:
    import trafilatura
    HAS_TRAFILATURA = True
except ImportError:
    HAS_TRAFILATURA = False

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

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

    SOURCE_EXTRACTION_PROFILES = {
        'efda.gov.et': {
            'content_selectors': [
                '.entry-content',
                'article .entry-content',
                '.post-content',
                '.post-entry',
                'article',
            ],
            'strip_selectors': [
                '.masthead', '.phantom-header', '#header', '.header-bar', '.top-bar', 
                '.footer', 'footer', '#footer', 'nav', '.menu', '.sidebar', 
                '.related-posts', '.share-buttons', '.sharedaddy', '.jp-relatedposts', 
                '.widget-area', '.breadcrumb', '.navigation', '.site-header',
            ],
            'title_selectors': ['h1.entry-title', 'h1.post-title', 'h1', '.entry-title'],
        },
        'moh.gov.et': {
            'content_selectors': [
                'article.node .field--name-body',
                'article.node .node__content',
                '.node__content',
                '.field--name-body',
                '.region-content article',
                'article',
            ],
            'strip_selectors': [
                '#header', '#footer', '.block-menu', '.navigation', '.toolbar', 
                '.breadcrumb', '.region-sidebar-first', '.region-sidebar-second', 
                'nav', 'header', 'footer', '.site-header',
            ],
            'title_selectors': ['h1.page-title', 'h1', '.title'],
        },
        'ephi.gov.et': {
            'content_selectors': [
                '.entry-content',
                '.post-content',
                'article',
                'main',
                'table',
            ],
            'strip_selectors': [
                'header', 'footer', 'nav', '.sidebar', '.menu', '#header', '#footer',
                '.elementor-nav-menu', '.top-bar',
            ],
            'title_selectors': ['h1.entry-title', 'h1'],
        },
        'ppa.gov.et': {
            'content_selectors': [
                '.entry-content',
                '.post-content',
                'article',
                '.content-area',
            ],
            'strip_selectors': [
                'header', 'footer', 'nav', '.sidebar', '.menu', '#header', '#footer', 
                '.top-header', '.site-header',
            ],
            'title_selectors': ['h1.entry-title', 'h1'],
        },
        'qelal.et': {
            'content_selectors': [
                '.tender-details',
                '.tender-content',
                '.tender-card-body',
                'article',
                'main',
            ],
            'strip_selectors': [
                'header', 'footer', 'nav', '.sidebar', '.similar-tenders', 
                '.advertisement', '.site-header',
            ],
            'title_selectors': ['h1.tender-title', 'h1', '.tender-name'],
        },
        '2merkato.com': {
            'content_selectors': [
                '.tender-detail',
                '.tender-content',
                '#tender-content',
                'article',
                'main',
            ],
            'strip_selectors': [
                'header', 'footer', 'nav', '.sidebar', '.advertisement', '.ads',
                '.site-header', '.top-nav',
            ],
            'title_selectors': ['h1', '.tender-title'],
        },
        'ethiojobs.net': {
            'content_selectors': [
                '.job-description',
                '.job-details',
                '.vacancy-desc',
                '#job-details',
                '.listing-details',
                'article',
            ],
            'strip_selectors': [
                'header', 'footer', 'nav', '.sidebar', '.similar-jobs', 
                '.advertisement', '.apply-box', '.site-header',
            ],
            'title_selectors': ['h1.job-title', 'h1', '.page-title'],
        },
        'ena.et': {
            'content_selectors': [
                '.article-content',
                '.news-content',
                '.content-area',
                '.entry-content',
                'article',
            ],
            'strip_selectors': [
                'header', 'footer', 'nav', '.navigation', '.sidebar', 
                '.related-news', '.top-bar', '.site-header',
            ],
            'title_selectors': ['h1.article-title', 'h1'],
        },
        'thereporterethiopia.com': {
            'content_selectors': [
                '.field--name-body',
                '.node__content',
                '.entry-content',
                'article',
            ],
            'strip_selectors': [
                'header', 'footer', 'nav', '.sidebar', '.advertisement', 
                '.social-share', '.site-header',
            ],
            'title_selectors': ['h1.page-header', 'h1'],
        },
        'egp.gov.et': {
            'content_selectors': [
                'table',
                '.bid-details',
                '.tender-details',
                'main',
            ],
            'strip_selectors': [
                'header', 'footer', 'nav', '.sidebar', '.site-header',
            ],
            'title_selectors': ['h1', 'h2'],
        },
    }

    ETHIOPIAN_MONTHS = {
        'መስከረም': 9, 'ጥቅምት': 10, 'ኅዳር': 11, 'ህዳር': 11,
        'ታኅሣሥ': 12, 'ታህሳስ': 12, 'ጥር': 1, 'የካቲት': 2,
        'መጋቢት': 3, 'ሚያዝያ': 4, 'ግንቦት': 5, 'ሰኔ': 6,
        'ሐምሌ': 7, 'ሃምሌ': 7, 'ነሐሴ': 8, 'ነሃሴ': 8,
        'ጳጉሜ': 9, 'ጳጉመን': 9
    }

    @classmethod
    def parse_smart_date(cls, date_str: str) -> Optional[datetime]:
        """
        Robust date parser supporting:
          - ISO 8601 (e.g. '2026-08-11T06:58:32+00:00', '2026-08-11')
          - Standard English dates ('August 25, 2026', 'Aug 11, 2026', '25 August 2026')
          - Text datelines with attached author/text ('August 25, 2026Bydawit', 'Aug112026')
          - Relative dates ('2 hours ago', 'yesterday', '3 days ago')
          - Ethiopian calendar dates ('ኅዳር 2 ቀን 2019', 'ነሐሴ 15 ቀን 2018')
        Always returns a timezone-aware datetime in UTC.
        """
        if not date_str or not isinstance(date_str, str):
            return None

        clean = date_str.strip()
        if not clean or len(clean) < 4:
            return None

        now = timezone.now()
        lower = clean.lower()

        # 1. Relative dates
        if 'yesterday' in lower:
            return now - timedelta(days=1)
        if 'today' in lower or 'just now' in lower:
            return now

        rel_match = re.search(r'(\d+)\s+(minute|hour|day|week|month)s?\s+ago', lower)
        if rel_match:
            val = int(rel_match.group(1))
            unit = rel_match.group(2)
            if unit == 'minute':
                return now - timedelta(minutes=val)
            elif unit == 'hour':
                return now - timedelta(hours=val)
            elif unit == 'day':
                return now - timedelta(days=val)
            elif unit == 'week':
                return now - timedelta(weeks=val)
            elif unit == 'month':
                return now - timedelta(days=val * 30)

        # 2. ISO 8601 format
        try:
            iso_candidate = clean.replace('Z', '+00:00')
            dt = datetime.fromisoformat(iso_candidate)
            if timezone.is_naive(dt):
                dt = timezone.make_aware(dt, dt_timezone.utc)
            return dt
        except Exception:
            pass

        # 3. Clean prefixes / suffixes
        cleaned = re.sub(r'^(?:posted\s*(?:on)?|published\s*(?:on)?|date\s*:?|updated\s*(?:on)?)\s*', '', clean, flags=re.IGNORECASE)
        cleaned = re.sub(r'(?:[\s\b]by|by)\b.*$', '', cleaned, flags=re.IGNORECASE).strip()

        # 4. Standard strptime patterns
        formats = [
            '%B %d, %Y', '%b %d, %Y', '%d %B %Y', '%d %b %Y',
            '%Y/%m/%d', '%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y',
            '%B %d %Y', '%b %d %Y', '%d %B, %Y', '%d %b, %Y',
            '%A, %B %d, %Y', '%a, %d %b %Y', '%a, %d %b %Y %H:%M:%S %z'
        ]
        for fmt in formats:
            try:
                dt = datetime.strptime(cleaned, fmt)
                if timezone.is_naive(dt):
                    dt = timezone.make_aware(dt, dt_timezone.utc)
                return dt
            except Exception:
                continue

        # 5. Regex for Month Day, Year embedded in string (e.g. "August 25, 2026Bydawit" or "Aug112026")
        m = re.search(
            r'(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s*(\d{1,2}),?\s*(\d{4})',
            clean,
            re.IGNORECASE
        )
        if m:
            month_str = m.group(1)[:3].capitalize()
            day_str = m.group(2)
            year_str = m.group(3)
            try:
                dt = datetime.strptime(f"{month_str} {day_str} {year_str}", "%b %d %Y")
                if timezone.is_naive(dt):
                    dt = timezone.make_aware(dt, dt_timezone.utc)
                return dt
            except Exception:
                pass

        # 6. Ethiopian calendar conversion
        for am_month, g_month in cls.ETHIOPIAN_MONTHS.items():
            if am_month in clean:
                em = re.search(fr'{am_month}\s+(\d{{1,2}})\s*(?:ቀን)?\s*(\d{{4}})', clean)
                if em:
                    e_day = int(em.group(1))
                    e_year = int(em.group(2))
                    g_year = e_year + 7 if g_month >= 9 else e_year + 8
                    try:
                        dt = datetime(g_year, g_month, min(e_day, 28))
                        return timezone.make_aware(dt, dt_timezone.utc)
                    except Exception:
                        pass

        return None

    @classmethod
    def extract_published_date(cls, soup: BeautifulSoup, url: str = "", raw_html: str = "") -> Optional[datetime]:
        """
        Inspects HTML soup, meta headers, structured JSON-LD, time tags, CSS selectors,
        and content text to accurately identify the original posted date.
        """
        if not soup:
            return None

        # 1. Meta Tags (article:published_time, og:published_time, date, publication_date)
        meta_candidates = [
            ('property', 'article:published_time'),
            ('property', 'og:published_time'),
            ('property', 'og:article:published_time'),
            ('name', 'publication_date'),
            ('name', 'publishdate'),
            ('name', 'date'),
            ('name', 'DC.date.issued'),
            ('name', 'sailthru.date'),
            ('itemprop', 'datePublished'),
        ]
        for attr, key in meta_candidates:
            meta_tag = soup.find('meta', attrs={attr: key})
            if meta_tag and meta_tag.get('content'):
                parsed = cls.parse_smart_date(meta_tag['content'])
                if parsed:
                    return parsed

        # 2. <time> HTML5 tags
        for t in soup.find_all('time'):
            dt_str = t.get('datetime') or t.get('pubdate') or t.get_text(strip=True)
            if dt_str:
                parsed = cls.parse_smart_date(dt_str)
                if parsed:
                    return parsed

        # 3. JSON-LD Structured Data (<script type="application/ld+json">)
        for s in soup.find_all('script', type=lambda t: t and 'ld+json' in t.lower()):
            text = s.string or s.get_text()
            if text:
                m = re.search(r'"(?:datePublished|dateCreated|uploadDate)"\s*:\s*"([^"]+)"', text)
                if m:
                    parsed = cls.parse_smart_date(m.group(1))
                    if parsed:
                        return parsed

        # 4. Standard CMS Date Classes
        cms_date_selectors = [
            '.node__submitted-date',
            '.node__submitted-info',
            '.submitted',
            '.entry-date',
            '.posted-on',
            '.post_date',
            '.post-date',
            '.views-field-created',
            '.views-field-post-date',
            '.date-display-single',
            '.article__date',
            '.meta-date',
            '.published',
            '[class*="post-date"]',
            '[class*="entry-date"]',
        ]
        for sel in cms_date_selectors:
            el = soup.select_one(sel)
            if el:
                txt = el.get('datetime') or el.get_text(strip=True)
                parsed = cls.parse_smart_date(txt)
                if parsed:
                    return parsed

        # 5. URL date pattern (e.g. /2026/08/11/slug/ or /2026-08-11/)
        if url:
            url_m = re.search(r'/(202[0-9])/([0-1][0-9])/([0-3][0-9])/', url)
            if url_m:
                try:
                    dt = datetime(int(url_m.group(1)), int(url_m.group(2)), int(url_m.group(3)))
                    return timezone.make_aware(dt, dt_timezone.utc)
                except Exception:
                    pass
            url_dash = re.search(r'/(202[0-9])-([0-1][0-9])-([0-3][0-9])/', url)
            if url_dash:
                try:
                    dt = datetime(int(url_dash.group(1)), int(url_dash.group(2)), int(url_dash.group(3)))
                    return timezone.make_aware(dt, dt_timezone.utc)
                except Exception:
                    pass

        # 6. Scanning text content dateline
        full_text = soup.get_text(separator=' ', strip=True)
        snippet = full_text[:2000]
        m_txt = re.search(
            r'\b(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2}),?\s*(\d{4})\b',
            snippet,
            re.IGNORECASE
        )
        if m_txt:
            parsed = cls.parse_smart_date(m_txt.group(0))
            if parsed:
                return parsed

        for am_month in cls.ETHIOPIAN_MONTHS.keys():
            if am_month in snippet:
                parsed = cls.parse_smart_date(snippet)
                if parsed:
                    return parsed

        return None

    def extract_clean_content_by_rule(
        self,
        soup: BeautifulSoup,
        url: str,
        config: dict = None,
        raw_html: str = ""
    ) -> tuple:
        """
        Extracts clean article/tender content and title using source-specific rules
        and user-defined CSS selectors. Strips all navigation bars, mega-menus, footers,
        and ad sidebars to prevent AI hallucination or dirty ingestion.
        """
        import copy
        soup = copy.copy(soup)
        config = config or {}
        domain = urlparse(url).netloc.lower()

        # Find matching rule from registry
        profile = None
        for d_key, p in self.SOURCE_EXTRACTION_PROFILES.items():
            if d_key in domain:
                profile = p
                break

        # 1. Strip universal boilerplate tags
        universal_strip = [
            'script', 'style', 'nav', 'header', 'footer', 'aside',
            'form', 'noscript', 'svg', 'iframe', 'button', 'input'
        ]
        for tag in universal_strip:
            for el in soup.find_all(tag):
                el.decompose()

        # 2. Strip profile and config junk selectors
        strip_selectors = list(profile.get('strip_selectors', [])) if profile else []
        if config.get('strip_selector'):
            strip_selectors.extend([s.strip() for s in config['strip_selector'].split(',') if s.strip()])

        for selector in strip_selectors:
            for el in soup.select(selector):
                el.decompose()

        # 3. Extract Title
        title = None
        title_selectors = []
        if config.get('title_selector'):
            title_selectors.append(config['title_selector'])
        if profile and 'title_selectors' in profile:
            title_selectors.extend(profile['title_selectors'])

        for t_sel in title_selectors:
            t_el = soup.select_one(t_sel)
            if t_el and t_el.get_text(strip=True):
                title = t_el.get_text(strip=True)
                break

        if not title:
            h1 = soup.find('h1')
            title = h1.get_text(strip=True) if h1 else (soup.title.get_text(strip=True) if soup.title else None)

        # 4. Extract Main Content via Selectors
        content = None
        content_selectors = []
        if config.get('content_selector'):
            content_selectors.append(config['content_selector'])
        if profile and 'content_selectors' in profile:
            content_selectors.extend(profile['content_selectors'])

        for c_sel in content_selectors:
            selectors_to_try = [s.strip() for s in c_sel.split(',')] if ',' in c_sel else [c_sel]
            for sel in selectors_to_try:
                c_el = soup.select_one(sel)
                if c_el:
                    for junk in c_el.select('script, style, .sharedaddy, .jp-relatedposts, .widget'):
                        junk.decompose()
                    text = c_el.get_text(separator='\n', strip=True)
                    if len(text) > 80:
                        content = text
                        break
            if content:
                break

        # 5. Fallback: Trafilatura on raw HTML if selectors yielded nothing
        if (not content or len(content) < 80) and HAS_TRAFILATURA and raw_html:
            try:
                traf_text = trafilatura.extract(raw_html, include_tables=True, include_links=True)
                if traf_text and len(traf_text.strip()) > 80:
                    content = traf_text.strip()
            except Exception as te:
                logger.debug(f"Trafilatura fallback failed on {url}: {te}")

        # 6. Fallback: Semantic HTML5 elements
        if not content or len(content) < 80:
            main = soup.select_one('article, main, [role="main"], #content, .content')
            target = main if main else soup.body
            if target:
                content = target.get_text(separator='\n', strip=True)

        # 7. Post-clean residual navigation phrases
        lines = [line.strip() for line in (content or '').split('\n') if line.strip()]
        cleaned_lines = []
        skip_phrases = [
            'skip to content', 'skip to main content', 'home /', 'search:',
            'facebook twitter linkedin', 'share this:'
        ]
        for line in lines:
            if any(line.lower().startswith(p) for p in skip_phrases):
                continue
            cleaned_lines.append(line)

        clean_content = '\n\n'.join(cleaned_lines) if cleaned_lines else (content or '')
        return title, clean_content

    @classmethod
    def extract_images_from_soup(cls, soup: BeautifulSoup, base_url: str) -> List[str]:
        """
        Extracts high-quality content images from HTML soup, including OpenGraph tags,
        article bodies, and featured thumbnails. Filters out tracking pixels, icons, and data URIs.
        """
        images = []
        seen = set()

        def add_img(src):
            if not src:
                return
            src = src.strip()
            # Filter data URIs, svg placeholders, tracking pixels
            if src.startswith('data:') or src.endswith('.svg') or 'tracking' in src.lower() or '1x1' in src.lower():
                return
            if 'gravatar.com' in src or 'analytics' in src.lower() or 'facebook.com/tr' in src:
                return
            full_url = urljoin(base_url, src)
            if full_url.startswith('http://') or full_url.startswith('https://'):
                clean_path = full_url.split('?')[0].lower()
                valid_exts = ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp')
                is_valid = any(clean_path.endswith(ext) for ext in valid_exts) or any(
                    k in full_url.lower() for k in ('/upload', '/media', '/image', '/photo', '/asset', 'cdn', 'wp-content')
                )
                if is_valid and full_url not in seen:
                    seen.add(full_url)
                    images.append(full_url)

        # 1. OpenGraph & Meta image tags (highest resolution featured image)
        for meta_prop in ('og:image', 'twitter:image', 'image'):
            for m in soup.find_all('meta', property=meta_prop) + soup.find_all('meta', attrs={'name': meta_prop}):
                add_img(m.get('content'))

        # 2. link rel="image_src"
        for link in soup.find_all('link', rel=lambda r: r and 'image' in str(r).lower()):
            add_img(link.get('href'))

        # 3. Main article / Content images (checking src, data-src, data-lazy-src, data-original)
        for img in soup.select('article img, .entry-content img, .post-content img, .post-thumbnail img, main img, #content img, .tender-details img'):
            src = (
                img.get('data-src') or
                img.get('data-lazy-src') or
                img.get('data-original') or
                img.get('src')
            )
            add_img(src)

        # 4. Fallback: all images on page if nothing found yet
        if not images:
            for img in soup.find_all('img'):
                src = img.get('data-src') or img.get('src')
                add_img(src)

        return images

    def _fetch_detail_content(self, url: str, ssl_verify: bool = True, config: dict = None, return_media: bool = False):
        """
        Visits an individual article or tender detail page and extracts the clean
        main content, title, images, and smart publication date using source-specific rule profiles.
        """
        if not url or not url.startswith('http'):
            return (None, None, [], None) if return_media else None

        config = config or {}
        detail_timeout = config.get('detail_timeout', 25)
        try:
            resp = self.session.get(url, timeout=detail_timeout, verify=ssl_verify)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.content, 'html.parser')
                images = self.extract_images_from_soup(soup, url)
                detail_date = self.extract_published_date(soup, url=url, raw_html=resp.text)
                clean_title, clean_text = self.extract_clean_content_by_rule(soup, url, config=config, raw_html=resp.text)
                if clean_text and len(clean_text) > 80:
                    return (clean_title, clean_text, images, detail_date) if return_media else clean_text
                return (clean_title, None, images, detail_date) if return_media else None
        except Exception as e:
            logger.debug(f"Detail fetch failed for {url}: {e}")

        return (None, None, [], None) if return_media else None

    def _fetch_feed(self, url: str, source_name: str, config: dict, since: Optional[datetime] = None, limit: int = 30) -> List[NormalizedItem]:
        """Parses RSS/Atom feeds with smart pagination, image discovery, and two-level detail enrichment."""
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
        parsed_entries = []
        links_to_crawl = []
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
                try:
                    dt = datetime(*entry.published_parsed[:6])
                    pub_date = timezone.make_aware(dt, dt_timezone.utc)
                except Exception:
                    pass
            elif entry.get('published') or entry.get('updated') or entry.get('created'):
                pub_date = self.parse_smart_date(entry.get('published') or entry.get('updated') or entry.get('created'))

            if since and pub_date and pub_date <= since:
                continue

            # Drop stale news older than max_age_days (default: 3 days)
            max_age_days = config.get('max_age_days', 3)
            if pub_date:
                age_seconds = (timezone.now() - pub_date).total_seconds()
                if age_seconds > max_age_days * 86400:
                    logger.debug(f"Skipping stale feed item '{title}' ({pub_date}) older than {max_age_days}d.")
                    continue

            # Extract media images from RSS entry
            entry_images = []
            seen_imgs = set()
            def add_feed_img(u):
                if u and u.startswith('http') and u not in seen_imgs:
                    seen_imgs.add(u)
                    entry_images.append(u)

            # Check media_content
            for mc in entry.get('media_content', []):
                if isinstance(mc, dict) and mc.get('url'):
                    add_feed_img(mc['url'])

            # Check media_thumbnail
            for mt in entry.get('media_thumbnail', []):
                if isinstance(mt, dict) and mt.get('url'):
                    add_feed_img(mt['url'])

            # Check enclosures
            for enc in entry.get('enclosures', []):
                if isinstance(enc, dict) and enc.get('href'):
                    if 'image' in enc.get('type', '') or any(enc['href'].lower().endswith(ext) for ext in ('.jpg', '.jpeg', '.png', '.webp')):
                        add_feed_img(enc['href'])

            # Check HTML <img> inside entry content
            for img_tag in soup.find_all('img'):
                src = img_tag.get('data-src') or img_tag.get('src')
                if src and not src.startswith('data:'):
                    add_feed_img(urljoin(link, src))

            need_detail = crawl_detail and (len(clean_text) < 300 or config.get('force_detail_crawl', False) or not entry_images)
            if need_detail and link and link.startswith('http'):
                links_to_crawl.append(link)

            parsed_entries.append({
                'entry_id': entry_id,
                'title': title,
                'clean_text': clean_text,
                'link': link,
                'author': author,
                'pub_date': pub_date,
                'entry_images': entry_images,
                'seen_imgs': seen_imgs,
                'need_detail': need_detail,
            })

        # Parallel detail page crawling for feed items
        detail_results = {}
        unique_links = list(set(links_to_crawl))
        if unique_links:
            max_workers = min(8, len(unique_links))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_map = {
                    executor.submit(self._fetch_detail_content, u, ssl_verify, config, True): u
                    for u in unique_links
                }
                for future in as_completed(future_map):
                    u = future_map[future]
                    try:
                        detail_results[u] = future.result()
                    except Exception as e:
                        logger.debug(f"Parallel feed detail fetch failed for {u}: {e}")

        # Assemble normalized items
        for p in parsed_entries:
            title = p['title']
            clean_text = p['clean_text']
            entry_images = p['entry_images']
            seen_imgs = p['seen_imgs']
            link = p['link']

            pub_date = p['pub_date']
            if p['need_detail'] and link in detail_results and detail_results[link]:
                detail_title, detail_body, detail_images, detail_date = detail_results[link]
                if detail_body and len(detail_body) > len(clean_text):
                    clean_text = detail_body
                if detail_title and (not title or title == 'Untitled Feed Item'):
                    title = detail_title
                for d_img in (detail_images or []):
                    if d_img and d_img.startswith('http') and d_img not in seen_imgs:
                        seen_imgs.add(d_img)
                        entry_images.append(d_img)
                if not pub_date and detail_date:
                    pub_date = detail_date

            if not pub_date and clean_text:
                pub_date = self.parse_smart_date(clean_text[:600])

            # Drop stale items discovered during detail enrichment older than max_age_days
            max_age_days = config.get('max_age_days', 3)
            if pub_date:
                age_seconds = (timezone.now() - pub_date).total_seconds()
                if age_seconds > max_age_days * 86400:
                    logger.debug(f"Dropping stale feed item '{title}' ({pub_date}) older than {max_age_days}d.")
                    continue

            items.append(NormalizedItem(
                external_id=f"rss_{abs(hash(p['entry_id']))}",
                title=title[:200],
                content_text=clean_text or title,
                url=link,
                author=p['author'],
                published_at=pub_date,
                media_urls=entry_images,
                raw_payload={'title': title, 'link': link, 'id': p['entry_id']},
                metadata={'feed_source': source_name, 'image_count': len(entry_images)}
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
                pdf_date = self.parse_smart_date(full_text[:1000])

                # Drop stale PDF document older than max_age_days
                if pdf_date:
                    max_age_days = config.get('max_age_days', 3)
                    age_seconds = (timezone.now() - pdf_date).total_seconds()
                    if age_seconds > max_age_days * 86400:
                        logger.debug(f"Dropping stale PDF document '{title}' ({pdf_date}) older than {max_age_days}d.")
                        return None
                return NormalizedItem(
                    external_id=f"pdf_{abs(hash(url))}",
                    title=title,
                    content_text=full_text,
                    url=url,
                    author=source_name,
                    published_at=pdf_date,
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

                # Extract date from table cells if available
                row_date = None
                for c in cells:
                    d = self.parse_smart_date(c)
                    if d:
                        row_date = d
                        break

                # Drop stale table notices older than max_age_days
                if row_date:
                    max_age_days = config.get('max_age_days', 3)
                    age_seconds = (timezone.now() - row_date).total_seconds()
                    if age_seconds > max_age_days * 86400:
                        continue

                items.append(NormalizedItem(
                    external_id=f"table_{abs(hash(item_url + content_str))}",
                    title=title[:200],
                    content_text=content_str,
                    url=item_url,
                    author=source_name,
                    published_at=row_date,
                    media_urls=pdf_links,
                    raw_payload={'table_index': t_idx + 1, 'row_index': r_idx + 1, 'cells': cells},
                    metadata={'is_table_record': True, 'table_headers': headers}
                ))

        return items

    def _fetch_with_playwright(self, url: str, config: dict) -> str:
        """
        Selectively renders dynamic client-side SPAs (Vue, React, Angular, Next.js)
        using headless Chromium via Playwright.
        """
        if not HAS_PLAYWRIGHT:
            logger.warning("Playwright is not installed. Falling back to HTTP requests.")
            resp = self.session.get(url, timeout=15, verify=config.get('ssl_verify', True))
            return resp.text

        ssl_verify = config.get('ssl_verify', True)
        wait_seconds = config.get('wait_seconds', 3)
        wait_until = config.get('wait_until', 'commit')
        wait_selector = config.get('wait_selector') or ('table' if config.get('extract_tables') else None)
        timeout_ms = config.get('timeout_ms', 40000)

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
            )
            context = browser.new_context(
                ignore_https_errors=(not ssl_verify),
                user_agent=self.USER_AGENT,
                viewport={'width': 1280, 'height': 800}
            )
            page = context.new_page()
            try:
                page.goto(url, wait_until=wait_until, timeout=timeout_ms)
                if wait_selector:
                    try:
                        page.wait_for_selector(wait_selector, timeout=18000)
                    except Exception as we:
                        logger.debug(f"Playwright selector wait timed out on {url}: {we}")
                if wait_seconds:
                    import time
                    time.sleep(wait_seconds)
                return page.content()
            finally:
                context.close()
                browser.close()

    def _fetch_html_page(self, url: str, source_name: str, config: dict, limit: int = 15) -> List[NormalizedItem]:
        """Fetches and scrapes an HTML page with selector cards, table parsing, & Level-2 detail crawling."""
        ssl_verify = config.get('ssl_verify', True)
        crawl_detail = config.get('crawl_detail', True)
        extract_tables = config.get('extract_tables', False)
        max_pages = config.get('max_pages', 1)
        use_js = config.get('requires_js', False) or config.get('render_js', False)

        items = []
        current_url = url
        pages_crawled = 0

        while current_url and pages_crawled < max_pages:
            pages_crawled += 1

            if use_js:
                html_content = self._fetch_with_playwright(current_url, config)
                soup = BeautifulSoup(html_content, 'html.parser')
            else:
                resp = self.session.get(current_url, timeout=config.get('timeout', 30), verify=ssl_verify)
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
                parsed_cards = []
                detail_urls_to_crawl = []
                for el in elements:
                    t_el = el.select_one(title_selector) if title_selector else (el.find(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']) or el.select_one('.title, [class*="title"], [class*="heading"]'))
                    title = t_el.get_text(strip=True) if t_el else "Scraped Item"

                    b_el = el.select_one(body_selector) if body_selector else el
                    content = b_el.get_text(separator=' ', strip=True) if b_el else ""

                    l_el = el.select_one(link_selector) if link_selector else el.find('a')
                    item_url = urljoin(current_url, l_el['href']) if l_el and l_el.get('href') else current_url

                    # Extract date from card if available
                    card_date = None
                    date_sel = config.get('date_selector')
                    if date_sel:
                        d_el = el.select_one(date_sel)
                        if d_el:
                            card_date = self.parse_smart_date(d_el.get('datetime') or d_el.get_text(strip=True))
                    if not card_date:
                        time_el = el.find('time') or el.select_one('.node__submitted-date, .post_date, .post-date, .entry-date, .date, .tender-date, .meta-date, [class*="date"]')
                        if time_el:
                            card_date = self.parse_smart_date(time_el.get('datetime') or time_el.get_text(strip=True))

                    # Drop stale news older than max_age_days (default: 3 days)
                    max_age_days = config.get('max_age_days', 3)
                    if card_date:
                        age_seconds = (timezone.now() - card_date).total_seconds()
                        if age_seconds > max_age_days * 86400:
                            logger.debug(f"Skipping stale card '{title}' ({card_date}) older than {max_age_days}d.")
                            continue

                    # Extract images from card
                    card_images = []
                    for img in el.find_all('img'):
                        src = img.get('data-src') or img.get('src')
                        if src and not src.startswith('data:'):
                            card_images.append(urljoin(current_url, src))

                    if crawl_detail and item_url != current_url and item_url.startswith('http'):
                        detail_urls_to_crawl.append(item_url)

                    parsed_cards.append({
                        'title': title,
                        'content': content,
                        'item_url': item_url,
                        'card_images': card_images,
                        'card_date': card_date,
                    })

                # Parallel detail page crawling for cards
                card_detail_results = {}
                unique_card_urls = list(set(detail_urls_to_crawl))
                if unique_card_urls:
                    max_workers = min(8, len(unique_card_urls))
                    with ThreadPoolExecutor(max_workers=max_workers) as executor:
                        future_map = {
                            executor.submit(self._fetch_detail_content, u, ssl_verify, config, True): u
                            for u in unique_card_urls
                        }
                        for future in as_completed(future_map):
                            u = future_map[future]
                            try:
                                card_detail_results[u] = future.result()
                            except Exception as e:
                                logger.debug(f"Parallel card detail fetch failed for {u}: {e}")

                for card in parsed_cards:
                    title = card['title']
                    content = card['content']
                    item_url = card['item_url']
                    card_images = card['card_images']
                    final_date = card.get('card_date')

                    if item_url in card_detail_results and card_detail_results[item_url]:
                        detail_title, detail_text, detail_images, detail_date = card_detail_results[item_url]
                        if detail_title and (not title or title == "Scraped Item" or len(title) < 5):
                            title = detail_title
                        if detail_text and len(detail_text) > len(content):
                            content = detail_text
                        for d_img in (detail_images or []):
                            if d_img not in card_images:
                                card_images.append(d_img)
                        if detail_date:
                            final_date = detail_date

                    if not final_date and content:
                        final_date = self.parse_smart_date(content[:600])

                    # Drop stale card items older than max_age_days
                    max_age_days = config.get('max_age_days', 3)
                    if final_date:
                        age_seconds = (timezone.now() - final_date).total_seconds()
                        if age_seconds > max_age_days * 86400:
                            logger.debug(f"Dropping stale card '{title}' ({final_date}) older than {max_age_days}d.")
                            continue

                    items.append(NormalizedItem(
                        external_id=f"web_{abs(hash(item_url + title))}",
                        title=title[:200],
                        content_text=content or title,
                        url=item_url,
                        author=source_name,
                        published_at=final_date,
                        media_urls=card_images,
                        raw_payload={'scraped_url': item_url},
                        metadata={'scraped': True, 'two_level_crawled': crawl_detail, 'image_count': len(card_images)}
                    ))

            # 2. Table-Based Extraction (e.g. EPHI procurement tables)
            elif extract_tables or soup.find('table'):
                table_items = self._extract_table_items(soup, current_url, source_name, config)
                if table_items:
                    items.extend(table_items[:limit])

            # 3. Clean Single Page Article Extraction (Using Source Profiles & Rules)
            if not items:
                raw_html_str = html_content if use_js else resp.text
                single_images = self.extract_images_from_soup(soup, current_url)
                single_date = self.extract_published_date(soup, url=current_url, raw_html=raw_html_str)

                # Drop stale single page article older than max_age_days
                max_age_days = config.get('max_age_days', 3)
                if single_date:
                    age_seconds = (timezone.now() - single_date).total_seconds()
                    if age_seconds > max_age_days * 86400:
                        logger.debug(f"Dropping stale single page article ({single_date}) older than {max_age_days}d.")
                        break

                title_text, clean_body = self.extract_clean_content_by_rule(
                    soup, current_url, config=config, raw_html=raw_html_str
                )
                title_text = title_text or (soup.find('h1').get_text(strip=True) if soup.find('h1') else source_name)
                clean_body = clean_body or title_text

                items.append(NormalizedItem(
                    external_id=f"web_{abs(hash(current_url))}",
                    title=title_text[:200],
                    content_text=clean_body[:25000],
                    url=current_url,
                    author=source_name,
                    published_at=single_date,
                    media_urls=single_images,
                    raw_payload={'url': current_url},
                    metadata={'single_page': True, 'rule_extracted': True, 'image_count': len(single_images)}
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
