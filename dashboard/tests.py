from unittest.mock import patch, MagicMock
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from connectors.models import Connector, InformationSource
from intelligence.models import CollectedItem, AIAnalysis, ExtractedEntity

class DashboardSecurityAndCurationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.password = "StrongPass2026!"
        self.user = User.objects.create_user(
            username="admin_curator",
            email="admin@marketintel.org",
            password=self.password,
            is_staff=True
        )

        self.connector = Connector.objects.create(name="Telegram", slug="tg-curate", connector_type="telegram")
        self.source = InformationSource.objects.create(
            name="Federal Procurement Channel",
            connector=self.connector,
            endpoint_url="@fed_procure"
        )
        self.item1 = CollectedItem.objects.create(
            source=self.source,
            external_id="dash_item_1",
            title="Tender for CT Scanner",
            original_content="Supply of modern 64-slice CT Scanner. Ref: CT/2026/01",
            status="ai_processed"
        )
        self.item2 = CollectedItem.objects.create(
            source=self.source,
            external_id="dash_item_2",
            title="Tender for MRI Equipment",
            original_content="Procurement of 1.5T MRI machine. Ref: MRI/2026/02",
            status="ai_processed"
        )
        AIAnalysis.objects.create(item=self.item1, relevance_score=90, short_summary="CT Scanner procurement")
        AIAnalysis.objects.create(item=self.item2, relevance_score=85, short_summary="MRI machine procurement")

    def test_unauthenticated_access_redirects_to_login(self):
        """Dashboard routes must be strictly protected by @login_required."""
        endpoints = [
            reverse('dashboard_overview'),
            reverse('dashboard_sources'),
            reverse('dashboard_items'),
            reverse('dashboard_ai_settings'),
            reverse('dashboard_publishing'),
            reverse('dashboard_health'),
        ]
        for url in endpoints:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertIn('/login/', response.url)

    def test_authenticated_login_and_logout_flow(self):
        # 1. Invalid login attempt
        bad_resp = self.client.post(reverse('login'), {'username': 'admin_curator', 'password': 'wrongpassword'})
        self.assertEqual(bad_resp.status_code, 200)

        # 2. Valid login attempt
        login_resp = self.client.post(reverse('login'), {'username': 'admin_curator', 'password': self.password})
        self.assertEqual(login_resp.status_code, 302)
        self.assertEqual(login_resp.url, reverse('dashboard_overview'))

        # 3. Access dashboard overview as authenticated user
        overview_resp = self.client.get(reverse('dashboard_overview'))
        self.assertEqual(overview_resp.status_code, 200)
        self.assertContains(overview_resp, "admin_curator")

        # 4. Logout
        logout_resp = self.client.get(reverse('logout'))
        self.assertEqual(logout_resp.status_code, 302)
        self.assertEqual(logout_resp.url, reverse('login'))

    def test_bulk_approve_action(self):
        self.client.login(username="admin_curator", password=self.password)

        with patch('publishing.alerts.TelegramAlertDispatcher.send_alert') as mock_alert:
            response = self.client.post(reverse('dashboard_items'), {
                'bulk_action': 'approve',
                'selected_items': [self.item1.id, self.item2.id]
            })
            self.assertEqual(response.status_code, 302)
            self.item1.refresh_from_db()
            self.item2.refresh_from_db()
            self.assertEqual(self.item1.status, 'approved')
            self.assertEqual(self.item2.status, 'approved')
            self.assertEqual(mock_alert.call_count, 2)

    def test_bulk_reject_action(self):
        self.client.login(username="admin_curator", password=self.password)

        response = self.client.post(reverse('dashboard_items'), {
            'bulk_action': 'reject',
            'selected_items': [self.item1.id]
        })
        self.assertEqual(response.status_code, 302)
        self.item1.refresh_from_db()
        self.item2.refresh_from_db()
        self.assertEqual(self.item1.status, 'rejected')
        self.assertEqual(self.item2.status, 'ai_processed')

    def test_bulk_publish_action(self):
        self.client.login(username="admin_curator", password=self.password)

        with patch('publishing.publishers.PublishingManager.publish_item') as mock_pub, \
             patch('publishing.alerts.TelegramAlertDispatcher.send_alert') as mock_alert:
            response = self.client.post(reverse('dashboard_items'), {
                'bulk_action': 'publish',
                'selected_items': [self.item1.id, self.item2.id]
            })
            self.assertEqual(response.status_code, 302)
            self.assertEqual(mock_pub.call_count, 2)
            self.assertEqual(mock_alert.call_count, 2)
