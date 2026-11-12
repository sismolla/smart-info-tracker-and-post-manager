import datetime
from django.core.management.base import BaseCommand
from django.utils import timezone
from connectors.models import Connector, InformationSource
from intelligence.models import Category, CollectedItem
from workflows.engine import PipelineEngine
from api.models import APIClient

class Command(BaseCommand):
    help = "Seeds initial connectors, categories, sources, and rich market intelligence demo data."

    def handle(self, *args, **options):
        self.stdout.write("Seeding baseline connectors and taxonomies...")

        # 1. Connectors
        connectors_data = [
            ('telegram', 'Telegram Connector', 'telegram', 'Official MTProto & Bot API channel/group monitoring'),
            ('facebook', 'Meta Facebook Connector', 'facebook', 'Meta Graph API v19+ Page monitoring'),
            ('linkedin', 'LinkedIn Connector', 'linkedin', 'LinkedIn REST API v2 company and job updates'),
            ('web', 'Universal Web Crawler', 'web', 'Scraper for portals, HTML tables, and PDF tender documents'),
            ('rss', 'RSS & Atom Ingestion', 'rss', 'Fast RSS/Atom syndicated news and blog feeds'),
        ]
        conn_objs = {}
        for slug, name, c_type, desc in connectors_data:
            c, _ = Connector.objects.get_or_create(
                slug=slug,
                defaults={'name': name, 'connector_type': c_type, 'description': desc, 'is_active': True}
            )
            conn_objs[slug] = c

        # 2. Categories
        categories_data = [
            ("Tenders and Procurement", "tenders-and-procurement", "#f59e0b"),
            ("Healthcare News", "healthcare-news", "#10b981"),
            ("Pharmaceutical Information", "pharmaceutical-information", "#06b6d4"),
            ("Medical Equipment", "medical-equipment", "#6366f1"),
            ("Job Opportunities", "job-opportunities", "#3b82f6"),
            ("Business News", "business-news", "#8b5cf6"),
            ("Product Announcements", "product-announcements", "#ec4899"),
            ("Market Trends", "market-trends", "#14b8a6"),
            ("Government Announcements", "government-announcements", "#64748b"),
        ]
        for name, slug, color in categories_data:
            Category.objects.get_or_create(
                slug=slug,
                defaults={'name': name, 'color': color, 'is_system': True}
            )

        # 3. Information Sources
        sources_data = [
            ('Ethiopian Procurement & Tenders', conn_objs['telegram'], 'channel', '@ethio_tenders_official', 15, 5),
            ('Ministry of Health Ethiopia Updates', conn_objs['facebook'], 'page', 'moh_ethiopia_official', 30, 4),
            ('East Africa Business Intelligence', conn_objs['linkedin'], 'page', 'urn:li:organization:9847123', 60, 4),
            ('The Reporter Ethiopia Business Feed', conn_objs['rss'], 'feed', 'https://www.thereporterethiopia.com/feed', 30, 3),
        ]
        src_objs = {}
        for name, conn, s_type, endpoint, freq, prio in sources_data:
            s, _ = InformationSource.objects.get_or_create(
                endpoint_url=endpoint,
                defaults={
                    'name': name,
                    'connector': conn,
                    'source_type': s_type,
                    'collection_frequency_minutes': freq,
                    'priority': prio,
                    'is_active': True,
                    'health_status': 'healthy',
                }
            )
            src_objs[endpoint] = s

        # 4. API Client for Testing
        client, created = APIClient.objects.get_or_create(
            name='Enterprise Analytics Consumer',
            defaults={'api_key': 'mkt_live_sample_key_998877665544332211'}
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f"Generated Demo API Key: {client.api_key}"))

        # 5. Rich Demonstration Intelligence Items
        sample_items = [
            {
                'source': src_objs['@ethio_tenders_official'],
                'external_id': 'tg_tender_001',
                'title': 'National Tender: Procurement of Diagnostic Ultrasound & MRI Spare Parts',
                'author': '@ethio_tenders_official',
                'url': 'https://t.me/ethio_tenders_official/4092',
                'published_at': timezone.now() - datetime.timedelta(hours=2),
                'content': """INVITATION TO NATIONAL COMPETITIVE BID (NCB)
Bid Reference No: EPSA/MOH/NCB/2026/042

Organization: Ethiopian Pharmaceuticals Supply Agency (EPSA)
Opportunity: Supply and Delivery of 15 Diagnostic Color Doppler Ultrasound Machines and MRI Spare Assemblies.
Eligible Bidders: All VAT-registered medical equipment importers and distributors with renewed trade licenses.

Financial Security: Bid bond of 250,000 ETB required.
Tender Closing Date: 2026-12-15 at 10:00 AM.
Bid Submission & Inquiries:
Contact Person: Ato Samuel Bekele (Procurement Directorate)
Telephone: +251 911 445566 or 011 275 1122
Email: tender@epsa.gov.et
Address: Arada Sub-City, Addis Ababa, Ethiopia."""
            },
            {
                'source': src_objs['@ethio_tenders_official'],
                'external_id': 'tg_tender_002_repost',
                'title': 'URGENT: EPSA Medical Ultrasound & MRI Spare Parts Bid 2026',
                'author': '@ethio_tenders_official',
                'url': 'https://t.me/ethio_tenders_official/4105',
                'published_at': timezone.now() - datetime.timedelta(hours=1),
                'content': """INVITATION TO NATIONAL COMPETITIVE BID (NCB)
Bid Reference No: EPSA/MOH/NCB/2026/042

Organization: Ethiopian Pharmaceuticals Supply Agency (EPSA)
Opportunity: Supply and Delivery of 15 Diagnostic Color Doppler Ultrasound Machines and MRI Spare Assemblies.
Eligible Bidders: All VAT-registered medical equipment importers and distributors with renewed trade licenses.

Financial Security: Bid bond of 250,000 ETB required.
Tender Closing Date: 2026-12-15 at 10:00 AM.
Telephone: +251 911 445566
Email: tender@epsa.gov.et"""
            },
            {
                'source': src_objs['moh_ethiopia_official'],
                'external_id': 'fb_moh_post_101',
                'title': 'Ministry of Health Signs Strategic Partnership for Local Insulin Formulation',
                'author': 'moh_ethiopia_official',
                'url': 'https://facebook.com/moh_ethiopia_official/posts/9812731',
                'published_at': timezone.now() - datetime.timedelta(hours=5),
                'content': """Press Release: Strengthening National Pharmaceutical Sovereignty

The Ministry of Health, in partnership with the Ethiopian Investment Commission and Julphar Pharmaceuticals, has officially inaugurated a new formulation line for human insulin vials in Kilinto Industrial Park.

Key Strategic Highlights:
1. Expected to cover 40% of national domestic insulin demand by Q3 2027.
2. Investment capital estimated at $18,000,000 USD.
3. Will create over 250 specialized biochemical engineering jobs.

Organization: Ministry of Health Ethiopia
Contact: communications@moh.gov.et
Telephone: +251 115 517011
Location: Kilinto Industrial Park, Addis Ababa."""
            },
            {
                'source': src_objs['urn:li:organization:9847123'],
                'external_id': 'li_job_eastafrica_554',
                'title': 'Senior Regulatory Affairs Specialist - Medical Devices & Diagnostics',
                'author': 'East Africa Business Council',
                'url': 'https://www.linkedin.com/feed/update/urn:li:ugcPost:8721635',
                'published_at': timezone.now() - datetime.timedelta(hours=8),
                'content': """Hiring Announcement:
Position: Senior Regulatory Affairs Specialist (Healthcare & Medical Devices)
Employer: Bionex Healthcare East Africa
Location: Addis Ababa, Ethiopia (Hybrid)

Responsibilities:
- Oversee EFDA (Ethiopian Food and Drug Authority) product registrations and import approvals.
- Manage compliance documentation for in-vitro diagnostics and surgical consumables.

Requirements:
- B.Sc or M.Sc in Pharmacy, Biomedical Engineering, or related health science.
- Minimum 5 years experience in pharmaceutical or medical device registration.
Application Deadline: 2026-11-30
Apply via CV to: careers@bionex-health.com
Contact Phone: +251 922 889900"""
            },
            {
                'source': src_objs['https://www.thereporterethiopia.com/feed'],
                'external_id': 'rss_rep_9912',
                'title': 'Ethiopian Pharmaceutical Market Projected to Reach $1.2B by 2028',
                'author': 'The Reporter Ethiopia',
                'url': 'https://www.thereporterethiopia.com/article/pharma-market-growth',
                'published_at': timezone.now() - datetime.timedelta(hours=14),
                'content': """A comprehensive market analysis published by the Chamber of Commerce highlights accelerating expansion in Ethiopia's healthcare supply sector.

Driven by government tax incentives for medical manufacturers and expanded public health insurance coverage, total sector expenditure is projected to increase from $820M to $1.2B over the next 36 months.

Key growth drivers include surgical supplies, cold-chain biologics, and regional export access under the AfCFTA agreement."""
            }
        ]

        self.stdout.write("Processing sample items through deduplication and AI pipeline...")
        for raw in sample_items:
            item, created = CollectedItem.objects.get_or_create(
                source=raw['source'],
                external_id=raw['external_id'],
                defaults={
                    'title': raw['title'],
                    'original_content': raw['content'],
                    'canonical_url': raw['url'],
                    'author': raw['author'],
                    'published_at': raw['published_at'],
                }
            )
            if created:
                PipelineEngine.process_item(item)
                self.stdout.write(self.style.SUCCESS(f"  Processed item #{item.id}: {item.title[:60]}... [Status: {item.status}]"))

        self.stdout.write(self.style.SUCCESS("\nDemo data seeding completed successfully!"))
