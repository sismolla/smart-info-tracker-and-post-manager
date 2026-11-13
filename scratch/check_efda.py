import requests
from bs4 import BeautifulSoup

url = 'https://www.efda.gov.et/efda-takes-historic-step-toward-who-maturity-level-3-for-medical-devices-regulation-addis-ababa/'
headers = {'User-Agent': 'Mozilla/5.0'}
resp = requests.get(url, headers=headers, timeout=15)
soup = BeautifulSoup(resp.text, 'html.parser')

print("Nav tags count:", len(soup.find_all('nav')))
print("Header tags count:", len(soup.find_all('header')))
print("Article tags count:", len(soup.find_all('article')))
print("Entry-content count:", len(soup.select('.entry-content')))
print("Post-content count:", len(soup.select('.post-content')))

# Check where the mega menu is:
menu_els = soup.select('div[class*="menu"], div[id*="menu"]')
print("Menu elements count:", len(menu_els))
for m in menu_els[:3]:
    print(" - Menu tag:", m.name, "id:", m.get('id'), "class:", m.get('class'))
