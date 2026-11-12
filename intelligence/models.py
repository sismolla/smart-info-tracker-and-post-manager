import hashlib
from django.db import models
from django.contrib.auth import get_user_model
from connectors.models import InformationSource, CollectionRun

User = get_user_model()

class Category(models.Model):
    """
    Standardized taxonomy classification for market intelligence items.
    """
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    color = models.CharField(max_length=20, default="#3b82f6", help_text="Hex color code for UI badge")
    is_system = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = 'Categories'
        ordering = ['name']

    def __str__(self):
        return self.name


class Tag(models.Model):
    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=80, unique=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"#{self.name}"


class DuplicateGroup(models.Model):
    """
    Clusters identical or near-duplicate announcements from multiple sources.
    Keeps full provenance of each occurrence without data loss.
    """
    canonical_hash = models.CharField(max_length=64, db_index=True)
    primary_item = models.ForeignKey('CollectedItem', null=True, blank=True, on_delete=models.SET_NULL, related_name='primary_for_group')
    similarity_score = models.FloatField(default=1.0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"DuplicateGroup #{self.id} (Hash: {self.canonical_hash[:10]}...)"


class CollectedItem(models.Model):
    """
    Canonical collected information entity.
    """
    STATUS_CHOICES = [
        ('ingested', 'Newly Ingested'),
        ('dedup_checked', 'Deduplication Passed'),
        ('duplicate', 'Duplicate Identified'),
        ('ai_processed', 'AI Analyzed'),
        ('approved', 'Approved for Publishing'),
        ('rejected', 'Rejected / Discarded'),
        ('archived', 'Archived'),
        ('published', 'Published to Destination'),
    ]

    source = models.ForeignKey(InformationSource, on_delete=models.CASCADE, related_name='items')
    collection_run = models.ForeignKey(CollectionRun, null=True, blank=True, on_delete=models.SET_NULL, related_name='items')
    external_id = models.CharField(max_length=200, db_index=True)
    title = models.CharField(max_length=300)
    original_content = models.TextField()
    canonical_url = models.URLField(max_length=1000, blank=True)
    author = models.CharField(max_length=200, blank=True)
    published_at = models.DateTimeField(null=True, blank=True, db_index=True)
    collected_at = models.DateTimeField(auto_now_add=True, db_index=True)
    content_hash = models.CharField(max_length=64, db_index=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    language = models.CharField(max_length=10, default='en', db_index=True)
    status = models.CharField(max_length=25, choices=STATUS_CHOICES, default='ingested', db_index=True)
    
    # Deduplication & Clustering
    duplicate_group = models.ForeignKey(DuplicateGroup, null=True, blank=True, on_delete=models.SET_NULL, related_name='items')
    is_primary_duplicate = models.BooleanField(default=True)

    # Classifications & Tags
    categories = models.ManyToManyField(Category, blank=True, related_name='items')
    tags = models.ManyToManyField(Tag, blank=True, related_name='items')

    class Meta:
        ordering = ['-collected_at']
        indexes = [
            models.Index(fields=['content_hash', 'status']),
            models.Index(fields=['source', 'collected_at']),
        ]

    def __str__(self):
        return f"[{self.get_status_display()}] {self.title[:80]}"

    def save(self, *args, **kwargs):
        if not self.content_hash:
            norm = " ".join(self.original_content.lower().split())
            self.content_hash = hashlib.sha256(norm.encode('utf-8')).hexdigest()
        super().save(*args, **kwargs)


class ContentVersion(models.Model):
    """
    Tracks editorial changes and revisions made by administrators.
    """
    item = models.ForeignKey(CollectedItem, on_delete=models.CASCADE, related_name='versions')
    version_number = models.PositiveIntegerField(default=1)
    edited_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    title = models.CharField(max_length=300)
    content_text = models.TextField()
    changed_at = models.DateTimeField(auto_now_add=True)
    change_summary = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-version_number']

    def __str__(self):
        return f"Item #{self.item.id} v{self.version_number}"


class ExtractedEntity(models.Model):
    """
    Structured key business parameters extracted via Regex and AI.
    Unknown values are preserved strictly as null/None.
    """
    item = models.OneToOneField(CollectedItem, on_delete=models.CASCADE, related_name='entities')
    organization = models.CharField(max_length=250, null=True, blank=True)
    contact_person = models.CharField(max_length=150, null=True, blank=True)
    phone_number = models.CharField(max_length=100, null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    location = models.CharField(max_length=200, null=True, blank=True)
    product_or_service = models.CharField(max_length=250, null=True, blank=True)
    price = models.CharField(max_length=100, null=True, blank=True)
    application_deadline = models.CharField(max_length=100, null=True, blank=True)
    tender_deadline = models.CharField(max_length=100, null=True, blank=True)
    opportunity_type = models.CharField(max_length=100, null=True, blank=True)
    keywords = models.JSONField(default=list, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Entities for Item #{self.item.id} ({self.organization or 'General'})"


class AIAnalysis(models.Model):
    """
    Full AI reasoning, summaries, translation, and explainable relevance scoring.
    """
    item = models.OneToOneField(CollectedItem, on_delete=models.CASCADE, related_name='ai_analysis')
    provider = models.CharField(max_length=50, default='gemini')
    model_name = models.CharField(max_length=80, default='gemini-1.5-flash')
    short_summary = models.TextField()
    detailed_summary = models.TextField()
    business_implications = models.TextField(blank=True)
    suggested_categories = models.JSONField(default=list, blank=True)
    suggested_tags = models.JSONField(default=list, blank=True)
    detected_language = models.CharField(max_length=20, default='en')
    amharic_summary = models.TextField(blank=True)
    
    # Explainable Relevance Scoring (0 to 100)
    relevance_score = models.PositiveSmallIntegerField(default=50, db_index=True)
    relevance_explanation = models.JSONField(default=dict, blank=True)
    
    token_usage = models.JSONField(default=dict, blank=True)
    analyzed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"AI Analysis for #{self.item.id} (Score: {self.relevance_score}/100)"
