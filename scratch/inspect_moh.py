import requests
from bs4 import BeautifulSoup

url = 'https://www.moh.gov.et/arm2025'
resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
soup = BeautifulSoup(resp.text, 'html.parser')

print("article tags:", len(soup.find_all('article')))
for a in soup.find_all('article'):
    print(" - article class:", a.get('class'))

print(".field--name-body count:", len(soup.select('.field--name-body')))
for f in soup.select('.field--name-body'):
    print(" - field text len:", len(f.get_text(strip=True)))
    print(" - field text preview:", f.get_text(strip=True)[:200])

print(".node__content count:", len(soup.select('.node__content')))
for n in soup.select('.node__content'):
    print(" - node__content len:", len(n.get_text(strip=True)))

print("Top bar / header classes:")
for el in soup.select('[class*="header"], [id*="header"], [class*="top"]')[:5]:
    print(" -", el.name, "class:", el.get('class'), "id:", el.get('id'))
