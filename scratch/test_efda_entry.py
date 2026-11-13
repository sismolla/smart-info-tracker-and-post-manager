import requests
from bs4 import BeautifulSoup

url = 'https://www.efda.gov.et/efda-takes-historic-step-toward-who-maturity-level-3-for-medical-devices-regulation-addis-ababa/'
headers = {'User-Agent': 'Mozilla/5.0'}
resp = requests.get(url, headers=headers, timeout=15)
soup = BeautifulSoup(resp.text, 'html.parser')

entry = soup.select_one('.entry-content')
if entry:
    # Remove any internal junk if any
    for junk in entry.select('script, style, .sharedaddy, .jp-relatedposts'):
        junk.decompose()
    text = entry.get_text(separator='\n', strip=True)
    print("ENTRY-CONTENT LENGTH:", len(text))
    print("ENTRY-CONTENT PREVIEW:\n", text[:800])
else:
    print("No .entry-content found!")
