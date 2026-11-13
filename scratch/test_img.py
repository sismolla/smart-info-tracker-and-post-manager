import os, sys
sys.path.insert(0, '.')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'market_intel.settings')
import django
django.setup()

from connectors.web import UniversalWebConnector
from bs4 import BeautifulSoup

connector = UniversalWebConnector()
url = 'https://www.efda.gov.et/efda-takes-historic-step-toward-who-maturity-level-3-for-medical-devices-regulation-addis-ababa/'
try:
    resp = connector.session.get(url, timeout=15)
    soup = BeautifulSoup(resp.text, 'html.parser')
    og_img = [m.get('content') for m in soup.find_all('meta', property='og:image') if m.get('content')]
    post_img = [img.get('src') for img in soup.select('.entry-content img, article img, .post-thumbnail img') if img.get('src')]
    print("OG IMAGE:", og_img)
    print("POST IMAGES:", post_img)
except Exception as e:
    print("Error:", e)
