import os
import sys
import django

# Setup django environment
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'market_intel.settings')
django.setup()

from intelligence.models import CollectedItem
from connectors.web import UniversalWebConnector

def main():
    connector = UniversalWebConnector()
    items = CollectedItem.objects.all()
    print(f"Total items in DB: {items.count()}")

    for item in items:
        if not item.canonical_url:
            continue
        print(f"\nProcessing Item #{item.id}: {item.title[:60]} ({item.canonical_url})")
        try:
            # Re-fetch detail page content and images
            content, images = connector._fetch_detail_content(item.canonical_url, return_media=True)
            print(f"  Extracted {len(images)} images.")
            if images:
                item.media_urls = images
                for i, img in enumerate(images, 1):
                    print(f"    Image {i}: {img}")
                item.save(update_fields=['media_urls'])
                print(f"  Saved images to Item #{item.id}")
            else:
                print(f"  No images extracted.")
        except Exception as e:
            print(f"  Error fetching images for Item #{item.id}: {e}")

if __name__ == '__main__':
    main()
