from unittest.mock import patch, MagicMock
from django.test import TestCase, override_settings
from connectors.models import Connector, InformationSource
from intelligence.models import CollectedItem, AIAnalysis, ExtractedEntity
from publishing.models import Webhook, Publication
from publishing.publishers import PublishingManager
from publishing.alerts import TelegramAlertDispatcher

class PublishingAndAlertTests(TestCase):
    def setUp(self):
        self.connector = Connector.objects.create(name="Web", slug="web-pub", connector_type="web")
        self.source = InformationSource.objects.create(
            name="News Portal",
            connector=self.connector,
            endpoint_url="https://example.com/news"
        )
        self.item = CollectedItem.objects.create(
            source=self.source,
            external_id="pub_item_1",
            title="Urgent Medical Supply Procurement Tender",
            original_content="Procurement of surgical gloves and masks. Deadline: 2026-12-31.",
            canonical_url="https://example.com/tender/1"
        )
        ExtractedEntity.objects.create(
            item=self.item,
            organization="Addis Ababa Health Bureau",
            reference_number="AAHB/MED/2026/01",
            estimated_budget="5,000,000 ETB",
            deadline_iso="2026-12-31"
        )
        AIAnalysis.objects.create(
            item=self.item,
            relevance_score=85,
            short_summary="Procurement of medical equipment and surgical supplies."
        )

    def test_webhook_publication_dispatch_with_hmac(self):
        webhook = Webhook.objects.create(
            name="Partner System",
            target_url="https://partner.example.com/webhook",
            secret_token="supersecret123",
            is_active=True
        )

        with patch('requests.post') as mock_post:
            mock_post.return_value = MagicMock(status_code=200, text="OK")
            pub = PublishingManager.publish_item(self.item, channel='webhook')
            
            self.assertEqual(pub.status, 'published')
            self.assertEqual(mock_post.call_count, 1)
            
            call_kwargs = mock_post.call_args[1]
            headers = call_kwargs['headers']
            self.assertIn('X-Hub-Signature-256', headers)
            self.assertTrue(headers['X-Hub-Signature-256'].startswith('sha256='))

    def test_telegram_alert_threshold_filter(self):
        # Item with relevance 50 should be skipped if threshold is 75
        low_score_item = CollectedItem.objects.create(
            source=self.source,
            external_id="pub_item_low",
            title="General Notice",
            original_content="General hospital meeting notice."
        )
        AIAnalysis.objects.create(
            item=low_score_item,
            relevance_score=40,
            short_summary="Low importance meeting."
        )

        with override_settings(TELEGRAM_BOT_TOKEN="12345:dummy", TELEGRAM_ALERT_CHAT_ID="-10099999", TELEGRAM_ALERT_MIN_SCORE=75):
            # Without force, should skip
            result = TelegramAlertDispatcher.send_alert(low_score_item, force=False)
            self.assertFalse(result)

    def test_telegram_alert_dispatch_success(self):
        with override_settings(TELEGRAM_BOT_TOKEN="12345:dummy", TELEGRAM_ALERT_CHAT_ID="-10099999", TELEGRAM_ALERT_MIN_SCORE=75):
            with patch('requests.post') as mock_post:
                mock_post.return_value = MagicMock(
                    status_code=200,
                    json=lambda: {'ok': True, 'result': {'message_id': 101}}
                )
                success = TelegramAlertDispatcher.send_alert(self.item)
                self.assertTrue(success)
                self.assertEqual(mock_post.call_count, 1)
                
                payload = mock_post.call_args[1]['json']
                self.assertEqual(payload['chat_id'], '-10099999')
                self.assertIn('AAHB/MED/2026/01', payload['text'])
                self.assertIn('5,000,000 ETB', payload['text'])
