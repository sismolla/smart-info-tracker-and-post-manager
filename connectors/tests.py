from django.test import TestCase
from connectors.base import registry, NormalizedItem
from connectors.models import Connector, InformationSource, ConnectedAccount
from connectors.telegram import TelegramConnector
from connectors.facebook import FacebookConnector
from connectors.web import UniversalWebConnector

class ConnectorFrameworkTests(TestCase):
    def setUp(self):
        self.conn_tg = Connector.objects.create(name="Telegram", slug="telegram", connector_type="telegram")
        self.conn_web = Connector.objects.create(name="Web", slug="web", connector_type="web")

    def test_registry_resolution(self):
        cls_tg = registry.get('telegram')
        self.assertEqual(cls_tg, TelegramConnector)
        cls_fb = registry.get('facebook')
        self.assertEqual(cls_fb, FacebookConnector)
        cls_web = registry.get('web')
        self.assertEqual(cls_web, UniversalWebConnector)

    def test_telegram_metadata_extraction(self):
        raw_msg = {
            'id': 100,
            'target': 'ethio_test',
            'text': "New Tender Available! Contact us at +251 911 223344 or email info@test.et. Price: 50,000 ETB. Visit https://test.et/bid",
            'date': '2026-11-12T10:00:00',
            'fwd_from': None,
            'views': 450,
        }
        connector = TelegramConnector()
        normalized = connector.normalize(raw_msg)
        
        self.assertIsInstance(normalized, NormalizedItem)
        self.assertEqual(normalized.external_id, "tg_ethio_test_100")
        self.assertIn('+251 911 223344', normalized.metadata['phones'])
        self.assertIn('info@test.et', normalized.metadata['emails'])
        self.assertIn('50,000 ETB', normalized.metadata['prices'])
        self.assertIn('https://test.et/bid', normalized.metadata['embedded_links'])

    def test_connected_account_credential_encryption(self):
        account = ConnectedAccount.objects.create(
            connector=self.conn_tg,
            name="Production Bot"
        )
        creds = {'api_id': '123456', 'api_hash': 'abcdef1234567890'}
        account.set_credentials(creds)
        account.save()

        # Reload from DB
        reloaded = ConnectedAccount.objects.get(id=account.id)
        self.assertNotIn('abcdef1234567890', reloaded.encrypted_credentials)
        self.assertEqual(reloaded.get_credentials()['api_id'], '123456')
        self.assertEqual(reloaded.get_credentials()['api_hash'], 'abcdef1234567890')

    def test_telegram_string_session_and_bot_mode(self):
        account = ConnectedAccount.objects.create(
            connector=self.conn_tg,
            name="Telegram StringSession Account"
        )
        account.set_credentials({'api_id': '12345', 'api_hash': 'abcdef', 'string_session': '1AZWarz...'})
        connector = TelegramConnector(account=account)
        self.assertTrue(connector.authenticate())
        self.assertEqual(connector.string_session, '1AZWarz...')

    def test_web_connector_with_unsaved_transient_source(self):
        # Verifies that transient / unsaved sources do not crash with ValueError on save
        transient_source = InformationSource(
            name="Transient Test Source",
            connector=self.conn_web,
            source_type="website",
            endpoint_url="https://example.com"
        )
        self.assertIsNone(transient_source.id)
        connector = UniversalWebConnector()
        # Should execute without raising ValueError: Cannot force an update in save() with no primary key
        items = connector.fetch_new_items(transient_source, limit=1)
        self.assertIsInstance(items, list)

    def test_web_connector_table_extraction(self):
        html = """
        <html><body>
          <table class="tenders-table">
            <tr><th>Tender Ref</th><th>Project Name</th><th>Deadline</th><th>Document</th></tr>
            <tr><td>MOH/2026/01</td><td>Supply of Rapid Test Kits</td><td>2026-12-15</td><td><a href="/docs/tender1.pdf">Download PDF</a></td></tr>
            <tr><td>MOH/2026/02</td><td>Hospital Cold Chain Units</td><td>2026-12-30</td><td><a href="/docs/tender2.pdf">Download PDF</a></td></tr>
          </table>
        </body></html>
        """
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        connector = UniversalWebConnector()
        table_items = connector._extract_table_items(
            soup=soup,
            url="https://example.com/procurement",
            source_name="Procurement Portal",
            config={'table_selector': 'table.tenders-table'}
        )
        self.assertEqual(len(table_items), 2)
        self.assertIn("MOH/2026/01", table_items[0].title)
        self.assertIn("Supply of Rapid Test Kits", table_items[0].content_text)
        self.assertIn("https://example.com/docs/tender1.pdf", table_items[0].media_urls)

    def test_web_connector_two_level_detail_crawl(self):
        from unittest.mock import patch, MagicMock
        connector = UniversalWebConnector()
        with patch.object(connector.session, 'get') as mock_get:
            mock_resp = MagicMock(status_code=200)
            mock_resp.text = """
            <html><body><article><div class="entry-content">
            <h1>Federal Medical Tender Notice</h1>
            <p>Comprehensive terms of reference for 100 ICU ventilators. Total budget 40,000,000 ETB.</p>
            </div></article></body></html>
            """
            mock_resp.content = mock_resp.text.encode('utf-8')
            mock_get.return_value = mock_resp

            detail_text = connector._fetch_detail_content("https://example.com/tender/101")
            self.assertIsNotNone(detail_text)
            self.assertIn("100 ICU ventilators", detail_text)
            self.assertIn("40,000,000 ETB", detail_text)
