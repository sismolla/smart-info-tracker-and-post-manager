from django.test import TestCase, Client
from connectors.models import Connector, InformationSource
from intelligence.models import CollectedItem
from api.models import APIClient

class RESTAPITests(TestCase):
    def setUp(self):
        self.client = Client()
        self.api_client = APIClient.objects.create(name="Automated Test Runner")
        self.connector = Connector.objects.create(name="Web", slug="web-api", connector_type="web")
        self.source = InformationSource.objects.create(
            name="News Feed",
            connector=self.connector,
            endpoint_url="https://test.et/feed"
        )
        self.item = CollectedItem.objects.create(
            source=self.source,
            external_id="api_item_1",
            title="Business Expansion in Addis Ababa",
            original_content="Economic update on enterprise growth."
        )

    def test_api_requires_or_accepts_api_key(self):
        # Request with valid API key header
        headers = {'HTTP_X_API_KEY': self.api_client.api_key}
        response = self.client.get('/api/v1/items/', **headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('results', data)
        self.assertGreaterEqual(len(data['results']), 1)

    def test_api_summary_endpoint(self):
        headers = {'HTTP_X_API_KEY': self.api_client.api_key}
        response = self.client.get('/api/v1/summary/', **headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('high_priority_tenders', data)
        self.assertIn('recent_jobs', data)

    def test_item_approval_action(self):
        headers = {'HTTP_X_API_KEY': self.api_client.api_key}
        response = self.client.post(f'/api/v1/items/{self.item.id}/approve/', **headers)
        self.assertEqual(response.status_code, 200)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, 'approved')
