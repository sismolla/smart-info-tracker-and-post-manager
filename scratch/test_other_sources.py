import os
import sys

sys.path.insert(0, '.')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'market_intel.settings')
import django
django.setup()

from connectors.web import UniversalWebConnector

connector = UniversalWebConnector()

# Test MOH
moh_url = 'https://www.moh.gov.et/arm2025'
moh_content = connector._fetch_detail_content(moh_url)
print("\n=== MOH EXTRACTION ===")
print("Length:", len(moh_content) if moh_content else 0)
print("Preview:", (moh_content[:250] if moh_content else "None").replace('\n', ' '))

# Test Qelal
qelal_url = 'https://tenders.qelal.et/tender-6af5bcdd0a538a2de9000001/'
qelal_content = connector._fetch_detail_content(qelal_url)
print("\n=== QELAL EXTRACTION ===")
print("Length:", len(qelal_content) if qelal_content else 0)
print("Preview:", (qelal_content[:250] if qelal_content else "None").replace('\n', ' '))
