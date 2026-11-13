import os
import sys

sys.path.insert(0, '.')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'market_intel.settings')
import django
django.setup()

from connectors.web import UniversalWebConnector

connector = UniversalWebConnector()
url = 'https://www.efda.gov.et/efda-takes-historic-step-toward-who-maturity-level-3-for-medical-devices-regulation-addis-ababa/'

content = connector._fetch_detail_content(url)
print("=== UNIVERSAL WEB CONNECTOR OUTPUT ===")
print("CONTENT TYPE:", type(content))
print("CONTENT LENGTH:", len(content) if content else 0)
print("FIRST 400 CHARACTERS:\n", content[:400] if content else "None")
print("\nCONTAINS 'Skip to content'?:", 'Skip to content' in (content or ''))
print("CONTAINS 'Facebook Twitter Linkedin'?:", 'Facebook Twitter' in (content or ''))
print("CONTAINS 'In a major milestone'?:", 'In a major milestone' in (content or ''))
