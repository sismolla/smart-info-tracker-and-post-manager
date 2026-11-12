from django.test import TestCase
from django.utils import timezone
from connectors.models import Connector, InformationSource
from intelligence.models import CollectedItem, Category
from intelligence.language import detect_language
from intelligence.dedup import DeduplicationEngine
from intelligence.scoring import calculate_relevance_score
from intelligence.ai_client import AIEngine

class IntelligenceEngineTests(TestCase):
    def setUp(self):
        self.connector = Connector.objects.create(name="Telegram", slug="tg-test", connector_type="telegram")
        self.source = InformationSource.objects.create(
            name="Test Source",
            connector=self.connector,
            endpoint_url="@test_channel"
        )

    def test_amharic_language_detection(self):
        amharic_text = "በኢትዮጵያ ውስጥ አዲስ የጤና እና የህክምና መሳሪያዎች ጨረታ ወጥቷል።"
        english_text = "New medical ultrasound procurement tender announced in Addis Ababa."
        
        self.assertEqual(detect_language(amharic_text), 'am')
        self.assertEqual(detect_language(english_text), 'en')

    def test_deduplication_exact_and_fuzzy(self):
        item1 = CollectedItem.objects.create(
            source=self.source,
            external_id="ext_1",
            title="Procurement of Hospital Syringes 2026",
            original_content="Organization: Federal MOH. Tender for 100,000 sterile disposable syringes. Deadline: Dec 2026.",
        )
        is_dup1, _ = DeduplicationEngine.check_and_cluster(item1)
        self.assertFalse(is_dup1)
        self.assertTrue(item1.is_primary_duplicate)

        # Exact duplicate with slightly different spacing and casing
        item2 = CollectedItem.objects.create(
            source=self.source,
            external_id="ext_2",
            title="Procurement of Hospital Syringes 2026",
            original_content="Organization: Federal MOH.  Tender for 100,000 sterile disposable syringes.   Deadline: Dec 2026.",
        )
        is_dup2, group = DeduplicationEngine.check_and_cluster(item2)
        self.assertTrue(is_dup2)
        self.assertFalse(item2.is_primary_duplicate)
        self.assertEqual(item2.status, 'duplicate')
        self.assertIsNotNone(group)

    def test_relevance_scoring_calculation(self):
        item = CollectedItem.objects.create(
            source=self.source,
            external_id="ext_score",
            title="Urgent Healthcare Tender",
            original_content="Bid opportunity for pharmaceutical drugs and hospital supplies. Contact +251911000000. Deadline: Next week.",
        )
        result = calculate_relevance_score(item)
        self.assertIn('total_score', result)
        self.assertIn('breakdown', result)
        self.assertGreaterEqual(result['total_score'], 50)

    def test_ai_engine_heuristic_analysis(self):
        item = CollectedItem.objects.create(
            source=self.source,
            external_id="ext_ai",
            title="Hiring Medical Officer",
            original_content="Organization: St. Paul Hospital. Looking for licensed physician. Phone: 0911223344. Deadline: 2026-12-01.",
        )
        ai_engine = AIEngine()
        analysis = ai_engine.analyze_item(item)
        self.assertIsNotNone(analysis)
        self.assertIn('Job Opportunities', analysis.suggested_categories)
        self.assertEqual(item.entities.organization, 'St. Paul Hospital')
