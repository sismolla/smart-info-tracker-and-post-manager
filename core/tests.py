from django.test import TestCase, Client
from django.utils import timezone
from core.models import DatabaseLock, SystemSetting
from core.security import encrypt_value, decrypt_value

class CoreSecurityAndLockTests(TestCase):
    def test_database_lock_acquire_and_release(self):
        key = "test_cron_lock"
        # First acquisition should succeed
        self.assertTrue(DatabaseLock.acquire(key, timeout_seconds=60))
        # Immediate second acquisition should fail
        self.assertFalse(DatabaseLock.acquire(key, timeout_seconds=60))
        # Release lock
        self.assertTrue(DatabaseLock.release(key))
        # Acquisition should now succeed again
        self.assertTrue(DatabaseLock.acquire(key, timeout_seconds=60))
        DatabaseLock.release(key)

    def test_credential_encryption_roundtrip(self):
        raw_secret = "my-super-secret-facebook-page-token-12345"
        encrypted = encrypt_value(raw_secret)
        self.assertNotEqual(raw_secret, encrypted)
        decrypted = decrypt_value(encrypted)
        self.assertEqual(raw_secret, decrypted)

    def test_system_settings_type_casting(self):
        SystemSetting.objects.create(key="test_bool", value="true", setting_type="boolean")
        SystemSetting.objects.create(key="test_int", value="42", setting_type="integer")
        self.assertEqual(SystemSetting.get_value("test_bool"), True)
        self.assertEqual(SystemSetting.get_value("test_int"), 42)

    def test_health_check_endpoint(self):
        client = Client()
        response = client.get('/health/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'ok')
        self.assertIn('services', data)
        self.assertIn('database', data['services'])
