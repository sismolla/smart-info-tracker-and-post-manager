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

    def test_financial_disambiguation_budget_vs_fee_vs_bond(self):
        """Verifies that document fee (200 ETB) is not mistaken for contract budget or bid bond."""
        text = """
        INVITATION TO BID
        Bid Ref No: MOH/PHARMA/2026/089
        Organization: Ministry of Health
        A non-refundable fee of 200 ETB for purchase of tender dossier.
        Bid security of 150,000 ETB in CPO required.
        Estimated budget of 25,000,000 ETB for surgical gloves procurement.
        Closing Date: 2026-12-20
        """
        item = CollectedItem.objects.create(
            source=self.source,
            external_id="ext_fin_test",
            title="Surgical Gloves Procurement",
            original_content=text
        )
        ai_engine = AIEngine()
        ai_engine.analyze_item(item)
        item.refresh_from_db()

        self.assertEqual(item.entities.reference_number, 'MOH/PHARMA/2026/089')
        self.assertIn('200', item.entities.document_fee)
        self.assertIn('150,000', item.entities.bid_bond_amount)
        self.assertIn('25,000,000', item.entities.estimated_budget)
        self.assertEqual(item.entities.deadline_iso, '2026-12-20')

    def test_reference_number_cross_lingual_deduplication(self):
        """Verifies that matching Bid Reference Numbers trigger deduplication even with different text."""
        item_english = CollectedItem.objects.create(
            source=self.source,
            external_id="tender_en_1",
            title="National Competitive Bid for Hospital Monitors",
            original_content="Tender Ref No: EPSA/EQUIP/2026/999\nOrganization: EPSA\nSupply of 50 patient monitors.",
        )
        AIEngine().analyze_item(item_english)
        DeduplicationEngine.check_and_cluster(item_english)

        # Re-post in Amharic with the same Bid Reference Number
        item_amharic = CollectedItem.objects.create(
            source=self.source,
            external_id="tender_am_2",
            title="የታካሚ መከታተያ ሞኒተሮች ግዢ ጨረታ ማስታወቂያ",
            original_content="የጨረታ ቁጥር: EPSA/EQUIP/2026/999\nድርጅት፡ የኢትዮጵያ መድኃኒት አቅራቢ ኤጀንሲ\n50 ሞኒተሮችን በግልጽ ጨረታ መግዛት ይፈልጋል።",
        )
        AIEngine().analyze_item(item_amharic)
        is_dup, group = DeduplicationEngine.check_and_cluster(item_amharic)

        self.assertTrue(is_dup)
        self.assertEqual(item_amharic.status, 'duplicate')
        self.assertFalse(item_amharic.is_primary_duplicate)
        self.assertIsNotNone(group)
