from django.contrib import admin
from .models import Category, Tag, CollectedItem, ExtractedEntity, AIAnalysis, AIDailyUsageTracker, TranscribedContent

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'is_system', 'created_at')
    search_fields = ('name', 'slug')

@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug')
    search_fields = ('name',)

@admin.register(CollectedItem)
class CollectedItemAdmin(admin.ModelAdmin):
    list_display = ('title', 'source', 'status', 'language', 'published_at', 'collected_at')
    list_filter = ('status', 'source', 'language')
    search_fields = ('title', 'original_content')

@admin.register(ExtractedEntity)
class ExtractedEntityAdmin(admin.ModelAdmin):
    list_display = ('item', 'organization', 'reference_number', 'estimated_budget', 'deadline_iso')
    search_fields = ('organization', 'reference_number')

@admin.register(AIAnalysis)
class AIAnalysisAdmin(admin.ModelAdmin):
    list_display = ('item', 'model_name', 'relevance_score', 'analyzed_at')
    list_filter = ('model_name', 'provider')

@admin.register(AIDailyUsageTracker)
class AIDailyUsageTrackerAdmin(admin.ModelAdmin):
    list_display = ('date', 'total_calls', 'estimated_cost_usd', 'is_circuit_breaker_tripped')

@admin.register(TranscribedContent)
class TranscribedContentAdmin(admin.ModelAdmin):
    list_display = ('item', 'mode', 'model_used', 'created_at', 'updated_at')
    list_filter = ('mode', 'model_used')

