import hmac
import hashlib
from django.db import models
from django.utils import timezone
from intelligence.models import CollectedItem

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
