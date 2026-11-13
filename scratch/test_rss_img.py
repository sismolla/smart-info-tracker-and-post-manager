import feedparser
feed = feedparser.parse('https://www.efda.gov.et/feed/')
for entry in feed.entries[:3]:
    print("Entry:", entry.get('title'))
    print("  enclosures:", entry.get('enclosures'))
    print("  media_content:", entry.get('media_content'))
    print("  media_thumbnail:", entry.get('media_thumbnail'))
