import hashlib
from django.db import models
from django.db.models import F
from django.utils import timezone
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
    media_urls = models.JSONField(default=list, blank=True, help_text="List of extracted image and document URLs")
    editorial_notes = models.TextField(blank=True, help_text="Custom editorial note or broadcast message")
    
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
    Structured key business parameters extracted via LLM Semantic Schema Parsing.
    Disambiguates financial components (Budget vs Bid Bond vs Doc Fee vs Salary)
    and converts deadlines to standardized Gregorian dates.
    Unknown values are preserved strictly as null/None.
    """
    item = models.OneToOneField(CollectedItem, on_delete=models.CASCADE, related_name='entities')
    organization = models.CharField(max_length=250, null=True, blank=True)
    reference_number = models.CharField(max_length=150, null=True, blank=True, db_index=True, help_text="Bid reference No or Job requisition ID")
    contact_person = models.CharField(max_length=150, null=True, blank=True)
    phone_number = models.CharField(max_length=100, null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    location = models.CharField(max_length=200, null=True, blank=True)
    product_or_service = models.CharField(max_length=250, null=True, blank=True)
    opportunity_type = models.CharField(max_length=100, null=True, blank=True)
    
    # Structured Financial Disambiguation (replaces naive regex price matching)
    estimated_budget = models.CharField(max_length=120, null=True, blank=True, help_text="Total estimated project or contract budget")
    bid_bond_amount = models.CharField(max_length=120, null=True, blank=True, help_text="Bid security / CPO required")
    document_fee = models.CharField(max_length=120, null=True, blank=True, help_text="Non-refundable fee to purchase tender dossier")
    salary_min = models.CharField(max_length=100, null=True, blank=True)
    salary_max = models.CharField(max_length=100, null=True, blank=True)
    currency = models.CharField(max_length=20, default='ETB', blank=True)
    
    # Standardized Dates & Calendar Disambiguation
    posted_date_iso = models.CharField(max_length=50, null=True, blank=True, help_text="Standardized ISO Gregorian publication date")
    posted_date_original = models.CharField(max_length=150, null=True, blank=True, help_text="Original posted date as written in source text/HTML")
    deadline_iso = models.CharField(max_length=50, null=True, blank=True, help_text="Standardized ISO Gregorian deadline")
    deadline_original = models.CharField(max_length=150, null=True, blank=True, help_text="Original deadline as written (e.g. Ethiopian calendar)")
    is_expired = models.BooleanField(default=False, help_text="Flag indicating whether opportunity deadline has passed")
    
    # Legacy / convenience properties
    price = models.CharField(max_length=100, null=True, blank=True)
    application_deadline = models.CharField(max_length=100, null=True, blank=True)
    tender_deadline = models.CharField(max_length=100, null=True, blank=True)
    keywords = models.JSONField(default=list, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        ref = f" [{self.reference_number}]" if self.reference_number else ""
        return f"Entities for Item #{self.item.id} ({self.organization or 'General'}{ref})"


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


class TranscribedContent(models.Model):
    """
    Stores professional news rewrites and translations of collected items.
    Both English and Amharic versions live here, produced by NewsTranscriber.
    """
    MODES = [
        ('news_en',      'English News Article'),
        ('news_am',      'Amharic News Article'),
        ('translate_am', 'Translated → Amharic'),
        ('translate_en', 'Translated → English'),
        ('both',         'Both Languages'),
    ]

    item = models.OneToOneField(
        CollectedItem, on_delete=models.CASCADE, related_name='transcription'
    )
    mode = models.CharField(max_length=20, choices=MODES, default='both')
    english_text = models.TextField(blank=True)
    amharic_text = models.TextField(blank=True)
    model_used = models.CharField(max_length=80, default='gemini-2.0-flash')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Transcription for Item #{self.item.id} [{self.get_mode_display()}]"


class AIDailyUsageTracker(models.Model):
    """
    Monitors daily AI token consumption, API calls, and estimated dollar costs.
    Automatically trips a circuit breaker when daily limits are breached to prevent
    runaway API billing.
    """
    date = models.DateField(default=timezone.now, unique=True, db_index=True)
    total_calls = models.PositiveIntegerField(default=0)
    total_input_tokens = models.PositiveIntegerField(default=0)
    total_output_tokens = models.PositiveIntegerField(default=0)
    estimated_cost_usd = models.DecimalField(max_digits=8, decimal_places=4, default=0.0000)
    is_circuit_breaker_tripped = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date']
        verbose_name = 'AI Daily Usage Tracker'

    def __str__(self):
        return f"AI Usage {self.date}: {self.total_calls} calls, ${self.estimated_cost_usd} (Breaker: {self.is_circuit_breaker_tripped})"

    @classmethod
    def can_call_ai(cls) -> bool:
        """Checks if current day usage is below spend limit and call limit.
        Also resets the GeminiKeyRotator at the start of each new day so
        previously exhausted keys are eligible again.
        """
        from django.conf import settings
        max_cost = getattr(settings, 'AI_DAILY_SPEND_LIMIT_USD', 2.00)
        max_calls = getattr(settings, 'AI_DAILY_MAX_CALLS', 500)
        
        today = timezone.now().date()
        tracker, created = cls.objects.get_or_create(date=today)

        # New day → reset all Gemini key exhaustion flags
        if created:
            try:
                from intelligence.ai_client import GeminiKeyRotator
                GeminiKeyRotator.reset_all()
            except Exception:
                pass
        
        if tracker.is_circuit_breaker_tripped:
            return False
            
        if tracker.total_calls >= max_calls or float(tracker.estimated_cost_usd) >= max_cost:
            tracker.is_circuit_breaker_tripped = True
            tracker.save(update_fields=['is_circuit_breaker_tripped'])
            return False
            
        return True

    @classmethod
    def record_usage(cls, input_tokens: int, output_tokens: int):
        today = timezone.now().date()

        # Ensure the row exists (safe even under concurrency due to unique=True on date)
        cls.objects.get_or_create(date=today)

        # Gemini 1.5 Flash pricing: $0.075 / 1M input, $0.30 / 1M output
        call_cost = (input_tokens * 0.000000075) + (output_tokens * 0.00000030)

        # Atomic database-level increments — no race condition
        cls.objects.filter(date=today).update(
            total_calls=F('total_calls') + 1,
            total_input_tokens=F('total_input_tokens') + input_tokens,
            total_output_tokens=F('total_output_tokens') + output_tokens,
            estimated_cost_usd=F('estimated_cost_usd') + call_cost,
        )

        # Circuit-breaker check: re-fetch to get the post-update value.
        # A small race here is acceptable (non-critical, per design).
        from django.conf import settings
        max_cost = getattr(settings, 'AI_DAILY_SPEND_LIMIT_USD', 2.00)
        updated = cls.objects.filter(date=today).values('estimated_cost_usd').first()
        if updated and float(updated['estimated_cost_usd']) >= max_cost:
            cls.objects.filter(date=today).update(is_circuit_breaker_tripped=True)
