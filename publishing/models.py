import hmac
import hashlib
from django.db import models
from django.utils import timezone
from intelligence.models import CollectedItem
from . import crypto


class PublishChannel(models.Model):
    """
    A connected publishing destination: Telegram bot/channel, Facebook Page, or LinkedIn Org.
    Credentials are stored encrypted in the database instead of hard-coded in .env,
    allowing admins to connect as many channels as they need through the UI.
    """
    TYPE_TELEGRAM = 'telegram'
    TYPE_FACEBOOK = 'facebook'
    TYPE_LINKEDIN = 'linkedin'

    CHANNEL_TYPES = [
        (TYPE_TELEGRAM, 'Telegram Bot / Channel'),
        (TYPE_FACEBOOK, 'Facebook Page'),
        (TYPE_LINKEDIN, 'LinkedIn Organization'),
    ]

    name          = models.CharField(max_length=120, help_text="A friendly label, e.g. 'Pharma Gebeya TG Main'")
    channel_type  = models.CharField(max_length=20, choices=CHANNEL_TYPES, db_index=True)
    description   = models.CharField(max_length=255, blank=True)
    is_active     = models.BooleanField(default=True)
    created_at    = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)

    # Encrypted credential store — one JSONField per channel keeps the schema simple
    # Telegram:  {bot_token, chat_id, min_score}
    # Facebook:  {page_access_token, page_id}
    # LinkedIn:  {access_token, org_urn}
    _credentials  = models.JSONField(default=dict, db_column='credentials',
                                     help_text="Encrypted credential dict (do not edit manually)")

    # Health / test tracking
    last_tested_at     = models.DateTimeField(null=True, blank=True)
    last_test_ok       = models.BooleanField(null=True, blank=True)
    last_test_message  = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ['channel_type', 'name']

    def __str__(self):
        return f"{self.get_channel_type_display()} — {self.name}"

    # ------------------------------------------------------------------
    # Credential helpers — always encrypt on write, decrypt on read
    # ------------------------------------------------------------------

    def set_credentials(self, data: dict):
        """Encrypt and save a plain-text credential dict."""
        encrypted = {k: crypto.encrypt(str(v)) if v else '' for k, v in data.items()}
        self._credentials = encrypted

    def get_credentials(self) -> dict:
        """Return fully decrypted credential dict."""
        return {k: crypto.decrypt(v) for k, v in (self._credentials or {}).items()}

    # Convenience getters ------------------------------------------------

    @property
    def bot_token(self) -> str:
        return self.get_credentials().get('bot_token', '')

    @property
    def chat_id(self) -> str:
        return self.get_credentials().get('chat_id', '')

    @property
    def tg_min_score(self) -> int:
        return int(self.get_credentials().get('min_score', 75) or 75)

    @property
    def page_access_token(self) -> str:
        return self.get_credentials().get('page_access_token', '')

    @property
    def page_id(self) -> str:
        return self.get_credentials().get('page_id', '')

    @property
    def access_token(self) -> str:
        return self.get_credentials().get('access_token', '')

    @property
    def org_urn(self) -> str:
        raw = self.get_credentials().get('org_urn', '')
        if raw and not raw.startswith('urn:li:organization:'):
            return f'urn:li:organization:{raw}'
        return raw

    @property
    def masked_credentials(self) -> dict:
        """Return credential keys with values masked for safe display."""
        creds = self.get_credentials()
        MASK_KEYS = {'bot_token', 'page_access_token', 'access_token'}
        return {k: (f"{v[:6]}…{v[-4:]}" if k in MASK_KEYS and len(v) > 10 else v)
                for k, v in creds.items()}

class Webhook(models.Model):
    """
    External subscriber webhooks to receive real-time published intelligence.
    """
    name = models.CharField(max_length=150)
    target_url = models.URLField(max_length=500)
    secret_token = models.CharField(max_length=120, blank=True, help_text="Used to generate X-Hub-Signature HMAC SHA256")
    is_active = models.BooleanField(default=True)
    events = models.JSONField(default=list, help_text="e.g. ['item.approved', 'item.published', 'tender.detected']")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.target_url})"

    def generate_signature(self, payload_bytes: bytes) -> str:
        if not self.secret_token:
            return ""
        return hmac.new(self.secret_token.encode('utf-8'), payload_bytes, hashlib.sha256).hexdigest()


class WebhookDelivery(models.Model):
    """
    Audit log of dispatched webhook payloads with retry tracking.
    """
    webhook = models.ForeignKey(Webhook, on_delete=models.CASCADE, related_name='deliveries')
    event_type = models.CharField(max_length=80)
    payload = models.JSONField(default=dict)
    response_status = models.PositiveIntegerField(null=True, blank=True)
    response_body = models.TextField(blank=True)
    is_success = models.BooleanField(default=False)
    attempt_count = models.PositiveSmallIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Delivery to {self.webhook.name}: {'SUCCESS' if self.is_success else 'FAILED'}"


class Publication(models.Model):
    """
    Records of published intelligence dispatched to external endpoints or formats.
    """
    CHANNELS = [
        ('webhook', 'Outgoing Webhook'),
        ('telegram', 'Telegram Push Alert'),
        ('linkedin', 'LinkedIn Organization Post'),
        ('facebook', 'Facebook Page Feed'),
        ('api_feed', 'Consumer REST API Feed'),
        ('blog_export', 'Formatted Blog Post'),
        ('csv_export', 'CSV Data Export'),
        ('json_export', 'JSON Data Export'),
    ]

    item = models.ForeignKey(CollectedItem, on_delete=models.CASCADE, related_name='publications')
    channel = models.CharField(max_length=40, choices=CHANNELS)
    destination = models.CharField(max_length=300, blank=True)
    published_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, default='published')
    formatted_payload = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"Published Item #{self.item.id} -> {self.get_channel_display()}"
