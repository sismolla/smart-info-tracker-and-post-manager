import json
from django.db import models
from django.utils import timezone
from core.security import encrypt_value, decrypt_value

class Connector(models.Model):
    """
    Defines supported external integration connectors in the platform.
    """
    TYPE_CHOICES = [
        ('telegram', 'Telegram (MTProto & Bot API)'),
        ('facebook', 'Meta Facebook (Graph API v19+)'),
        ('linkedin', 'LinkedIn (REST API v2)'),
        ('web', 'Universal Web Crawler & PDF Extractor'),
        ('rss', 'RSS & Atom Feed Ingestion'),
    ]

    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=50, unique=True)
    connector_type = models.CharField(max_length=30, choices=TYPE_CHOICES)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    config_schema = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.get_connector_type_display()})"


class ConnectedAccount(models.Model):
    """
    Stores credentials, OAuth tokens, and session data for authenticated source access.
    All sensitive tokens are encrypted at rest using AES-Fernet.
    """
    connector = models.ForeignKey(Connector, on_delete=models.CASCADE, related_name='accounts')
    name = models.CharField(max_length=150)
    account_identifier = models.CharField(max_length=150, blank=True, help_text="e.g. Phone number, Meta App ID, or Organization ID")
    encrypted_credentials = models.TextField(blank=True, help_text="Encrypted JSON credential dictionary")
    token_expires_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def set_credentials(self, cred_dict: dict):
        raw_json = json.dumps(cred_dict)
        self.encrypted_credentials = encrypt_value(raw_json)

    def get_credentials(self) -> dict:
        if not self.encrypted_credentials:
            return {}
        decrypted = decrypt_value(self.encrypted_credentials)
        if not decrypted:
            return {}
        try:
            return json.loads(decrypted)
        except Exception:
            return {}

    def __str__(self):
        return f"{self.name} - {self.connector.name}"


class InformationSource(models.Model):
    """
    Target information source to monitor (e.g. channel, page, website URL).
    """
    SOURCE_TYPES = [
        ('channel', 'Public / Authorized Channel'),
        ('group', 'Authorized Group'),
        ('page', 'Organization / Public Page'),
        ('website', 'Website URL / Portal'),
        ('feed', 'RSS / Atom Feed'),
        ('sitemap', 'XML Sitemap'),
    ]

    HEALTH_STATUSES = [
        ('healthy', 'Healthy'),
        ('rate_limited', 'Rate Limited'),
        ('failing', 'Failing / Error'),
        ('paused', 'Paused'),
    ]

    name = models.CharField(max_length=200)
    connector = models.ForeignKey(Connector, on_delete=models.CASCADE, related_name='sources')
    account = models.ForeignKey(ConnectedAccount, null=True, blank=True, on_delete=models.SET_NULL, related_name='sources')
    source_type = models.CharField(max_length=30, choices=SOURCE_TYPES, default='channel')
    endpoint_url = models.CharField(max_length=500, help_text="Channel username, Page ID, or Website/RSS URL")
    collection_frequency_minutes = models.PositiveIntegerField(default=30)
    priority = models.PositiveSmallIntegerField(default=3, help_text="1 (Lowest) to 5 (Highest)")
    is_active = models.BooleanField(default=True)
    health_status = models.CharField(max_length=20, choices=HEALTH_STATUSES, default='healthy')
    last_synced_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    config = models.JSONField(default=dict, blank=True, help_text="Custom CSS selectors, filters, regexes")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-priority', 'name']

    def __str__(self):
        return f"{self.name} [{self.get_source_type_display()}]"


class CollectionRun(models.Model):
    """
    Audit log for scheduled and on-demand synchronization runs.
    """
    STATUS_CHOICES = [
        ('running', 'Running'),
        ('success', 'Success'),
        ('partial', 'Partial Failure'),
        ('failed', 'Failed'),
    ]

    EXECUTION_MODES = [
        ('cpanel_cron', 'cPanel Cron Job (Mode A)'),
        ('celery_worker', 'Dedicated Worker (Mode B)'),
        ('manual', 'Manual Dashboard Trigger'),
    ]

    source = models.ForeignKey(InformationSource, on_delete=models.CASCADE, related_name='runs')
    execution_mode = models.CharField(max_length=30, choices=EXECUTION_MODES, default='cpanel_cron')
    started_at = models.DateTimeField(auto_now_add=True, db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='running')
    items_discovered = models.PositiveIntegerField(default=0)
    items_saved = models.PositiveIntegerField(default=0)
    duplicates_skipped = models.PositiveIntegerField(default=0)
    error_details = models.TextField(blank=True)

    class Meta:
        ordering = ['-started_at']

    def __str__(self):
        return f"Run #{self.id} for {self.source.name} ({self.status})"
