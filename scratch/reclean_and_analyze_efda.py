import os
import sys

sys.path.insert(0, '.')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'market_intel.settings')
import django
django.setup()

from intelligence.models import CollectedItem
from connectors.web import UniversalWebConnector
from intelligence.ai_client import AIEngine

item = CollectedItem.objects.get(id=16)
print("OLD TITLE:", item.title)
print("OLD CONTENT LEN:", len(item.original_content))
print("OLD CONTENT PREVIEW:\n", item.original_content[:200])

connector = UniversalWebConnector()
url = item.canonical_url
clean_content = connector._fetch_detail_content(url)

if clean_content:
    item.original_content = clean_content
    item.save(update_fields=['original_content'])
    print("\nNEW CONTENT LEN:", len(item.original_content))
    print("NEW CONTENT PREVIEW:\n", item.original_content[:400])

    # Re-analyze with AI
    ai_engine = AIEngine()
    analysis = ai_engine.analyze_item(item)
    print("\n=== AI ANALYSIS COMPLETED ===")
    print("AI Title:", analysis.item.title)
    print("Executive Summary:", analysis.short_summary)
    print("Detailed Summary:", analysis.detailed_summary[:300])
    print("Primary Category:", [c.name for c in item.categories.all()])
    print("Organization:", getattr(item.entities, 'organization', None))
    print("Relevance Score:", analysis.relevance_score)
else:
    print("Failed to fetch clean content!")
