import os, sys
sys.path.insert(0, '.')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'market_intel.settings')
import django
django.setup()

from connectors.models import InformationSource

source_configs = {
    'EFDA': {
        'content_selector': '.entry-content, article .entry-content, .post-content',
        'strip_selector': '.masthead, .phantom-header, #header, nav, .menu, .sidebar, footer',
        'title_selector': 'h1.entry-title, h1',
        'crawl_detail': True,
        'category_slug': 'official_regulatory'
    },
    'Ministry of Health Ethiopia (MOH)': {
        'content_selector': 'article.node .field--name-body, .node__content, .field--name-body',
        'strip_selector': '#header, #footer, nav, .block-menu, .region-sidebar-first',
        'title_selector': 'h1.page-title, h1',
        'crawl_detail': True,
        'category_slug': 'healthcare_news'
    },
    'EPHI': {
        'extract_tables': True,
        'table_selector': 'table',
        'content_selector': '.entry-content, article',
        'strip_selector': 'header, footer, nav, .sidebar',
        'category_slug': 'procurement'
    },
    'PPA': {
        'content_selector': '.entry-content, .post-content, article',
        'strip_selector': 'header, footer, nav, .sidebar, #header, #footer',
        'max_pages': 2,
        'crawl_detail': False,
        'category_slug': 'procurement'
    },
    'Qelal': {
        'content_selector': '.tender-details, .tender-content, article',
        'strip_selector': 'header, footer, nav, .sidebar, .similar-tenders',
        'crawl_detail': True,
        'category_slug': 'tenders'
    },
    '2merkato': {
        'requires_js': True,
        'item_selector': 'a[href*="/tenders/"]',
        'title_selector': 'h3, h2, span, p',
        'content_selector': '.tender-detail, .tender-content, main',
        'strip_selector': 'header, footer, nav, .advertisement',
        'link_selector': 'a[href*="/tenders/"]',
        'wait_selector': 'a[href*="/tenders/"]',
        'wait_seconds': 3,
        'timeout_ms': 35000,
        'crawl_detail': False,
        'category_slug': 'tenders'
    },
    'Ethiojobs': {
        'requires_js': True,
        'item_selector': 'a[href*="/job/"], a[href*="/display-job/"]',
        'title_selector': 'h3, h2, div',
        'content_selector': '.job-description, .job-details, .vacancy-desc, article',
        'strip_selector': 'header, footer, nav, .similar-jobs, .advertisement',
        'link_selector': 'a[href*="/job/"]',
        'wait_selector': 'a[href*="/job/"]',
        'wait_seconds': 2,
        'timeout_ms': 25000,
        'crawl_detail': False,
        'category_slug': 'employment'
    },
    'ENA': {
        'content_selector': '.article-content, .news-content, .entry-content, article',
        'strip_selector': 'header, footer, nav, .navigation, .sidebar, .related-news',
        'base_url': 'https://www.ena.et/',
        'listing_url': 'https://www.ena.et/web/ena/health',
        'category_slug': 'healthcare_news'
    }
}

for src in InformationSource.objects.all():
    for name_key, cfg in source_configs.items():
        if name_key.lower() in src.name.lower():
            merged_config = dict(src.config or {})
            merged_config.update(cfg)
            src.config = merged_config
            src.save(update_fields=['config'])
            print(f"Updated source #{src.id} '{src.name}' with clean extraction rule selectors.")
