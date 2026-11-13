import feedparser

feed = feedparser.parse('https://www.moh.gov.et/rss.xml')
print("Feed entries count:", len(feed.entries))
for entry in feed.entries[:5]:
    print(" - Title:", entry.get('title'))
    print("   Link:", entry.get('link'))
    print("   Summary:", entry.get('summary')[:100] if entry.get('summary') else 'None')
