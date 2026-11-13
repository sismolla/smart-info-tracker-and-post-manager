import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse

DOMAIN_RULES = {
    'efda.gov.et': {
        'content_selectors': ['.entry-content', '.post-content', 'article .entry-content', 'article'],
        'strip_selectors': [
            '.masthead', '.phantom-header', '#header', '.header-bar', '.top-bar', 
            '.footer', 'footer', '#footer', 'nav', '.menu', '.sidebar', 
            '.related-posts', '.share-buttons', '.sharedaddy', '.jp-relatedposts', '.widget-area'
        ],
        'title_selectors': ['h1.entry-title', 'h1', '.entry-title']
    },
    'moh.gov.et': {
        'content_selectors': ['article.node', '.node__content', '.field--name-body', '.region-content article', 'article'],
        'strip_selectors': [
            '#header', '#footer', '.block-menu', '.navigation', '.toolbar', 
            '.breadcrumb', '.region-sidebar-first', '.region-sidebar-second', 'nav', 'header', 'footer'
        ],
        'title_selectors': ['h1.page-title', 'h1', '.title']
    },
    'ephi.gov.et': {
        'content_selectors': ['.entry-content', '.post-content', 'article', 'main'],
        'strip_selectors': ['header', 'footer', 'nav', '.sidebar', '.menu', '#header', '#footer'],
        'title_selectors': ['h1.entry-title', 'h1']
    },
    'ppa.gov.et': {
        'content_selectors': ['.entry-content', '.post-content', 'article', '.content-area'],
        'strip_selectors': ['header', 'footer', 'nav', '.sidebar', '.menu', '#header', '#footer', '.top-header'],
        'title_selectors': ['h1.entry-title', 'h1']
    },
    'qelal.et': {
        'content_selectors': ['.tender-details', '.tender-content', '.tender-card-body', 'article', 'main'],
        'strip_selectors': ['header', 'footer', 'nav', '.sidebar', '.similar-tenders', '.advertisement'],
        'title_selectors': ['h1.tender-title', 'h1', '.tender-name']
    },
    '2merkato.com': {
        'content_selectors': ['.tender-detail', '.tender-content', '#tender-content', 'article', 'main'],
        'strip_selectors': ['header', 'footer', 'nav', '.sidebar', '.advertisement', '.ads'],
        'title_selectors': ['h1', '.tender-title']
    },
    'ethiojobs.net': {
        'content_selectors': ['.job-description', '.job-details', '.vacancy-desc', '#job-details', '.listing-details', 'article'],
        'strip_selectors': ['header', 'footer', 'nav', '.sidebar', '.similar-jobs', '.advertisement', '.apply-box'],
        'title_selectors': ['h1.job-title', 'h1', '.page-title']
    },
    'ena.et': {
        'content_selectors': ['.article-content', '.news-content', '.content-area', '.entry-content', 'article'],
        'strip_selectors': ['header', 'footer', 'nav', '.navigation', '.sidebar', '.related-news', '.top-bar'],
        'title_selectors': ['h1.article-title', 'h1']
    }
}

def clean_extract(url, html):
    soup = BeautifulSoup(html, 'html.parser')
    domain = urlparse(url).netloc.lower()
    
    # Match rule by domain substring
    rule = None
    for d_key, r in DOMAIN_RULES.items():
        if d_key in domain:
            rule = r
            break
            
    # 1. Strip default junk tags
    default_strip = ['script', 'style', 'nav', 'header', 'footer', 'aside', 'form', 'noscript', 'svg', 'iframe']
    for tag_name in default_strip:
        for t in soup.find_all(tag_name):
            t.decompose()
            
    # 2. Strip rule-specific junk selectors
    if rule and 'strip_selectors' in rule:
        for selector in rule['strip_selectors']:
            for el in soup.select(selector):
                el.decompose()
                
    # 3. Extract title
    title = None
    if rule and 'title_selectors' in rule:
        for t_sel in rule['title_selectors']:
            t_el = soup.select_one(t_sel)
            if t_el and t_el.get_text(strip=True):
                title = t_el.get_text(strip=True)
                break
    if not title:
        h1 = soup.find('h1')
        title = h1.get_text(strip=True) if h1 else (soup.title.get_text(strip=True) if soup.title else 'Untitled')

    # 4. Extract content via rule selectors
    content = None
    if rule and 'content_selectors' in rule:
        for c_sel in rule['content_selectors']:
            c_el = soup.select_one(c_sel)
            if c_el:
                content = c_el.get_text(separator='\n', strip=True)
                if len(content) > 100:
                    break

    # 5. Fallback to generic main/article or body
    if not content or len(content) < 80:
        main = soup.select_one('article, main, #content, .content')
        target = main if main else soup.body
        if target:
            content = target.get_text(separator='\n', strip=True)
            
    # Clean leading "Skip to content" or navigation residues
    lines = [line.strip() for line in (content or '').split('\n') if line.strip()]
    cleaned_lines = []
    skip_phrases = ['skip to content', 'skip to main content', 'home /', 'search:']
    for l in lines:
        if any(l.lower().startswith(p) for p in skip_phrases):
            continue
        cleaned_lines.append(l)
        
    return title, '\n'.join(cleaned_lines)

# Test EFDA
url_efda = 'https://www.efda.gov.et/efda-takes-historic-step-toward-who-maturity-level-3-for-medical-devices-regulation-addis-ababa/'
resp = requests.get(url_efda, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
title, content = clean_extract(url_efda, resp.text)
print("=== EFDA EXTRACTED ===")
print("TITLE:", title)
print("CONTENT LENGTH:", len(content))
print("CONTENT FIRST 300 CHARS:\n", content[:300])
print("HAS 'Skip to content'?:", 'Skip to content' in content)
print("HAS 'Facebook Twitter Linkedin'?:", 'Facebook Twitter' in content)
