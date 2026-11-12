from rest_framework import serializers
from connectors.models import Connector, InformationSource, CollectionRun
from intelligence.models import CollectedItem, ExtractedEntity, AIAnalysis, Category, Tag, DuplicateGroup
from publishing.models import Webhook, Publication

class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'name', 'slug', 'color']

class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ['id', 'name', 'slug']

class ExtractedEntitySerializer(serializers.ModelSerializer):
    class Meta:
        model = ExtractedEntity
        fields = [
            'organization', 'contact_person', 'phone_number', 'email',
            'location', 'product_or_service', 'price',
            'application_deadline', 'tender_deadline', 'opportunity_type', 'keywords'
        ]

class AIAnalysisSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIAnalysis
        fields = [
            'provider', 'model_name', 'short_summary', 'detailed_summary',
            'business_implications', 'detected_language', 'amharic_summary',
            'relevance_score', 'relevance_explanation', 'analyzed_at'
        ]

class CollectedItemSerializer(serializers.ModelSerializer):
    categories = CategorySerializer(many=True, read_only=True)
    tags = TagSerializer(many=True, read_only=True)
    entities = ExtractedEntitySerializer(read_only=True)
    ai_analysis = AIAnalysisSerializer(read_only=True)
    source_name = serializers.CharField(source='source.name', read_only=True)
    source_type = serializers.CharField(source='source.source_type', read_only=True)

    class Meta:
        model = CollectedItem
        fields = [
            'id', 'external_id', 'title', 'original_content', 'canonical_url',
            'author', 'source_name', 'source_type', 'published_at', 'collected_at',
            'language', 'status', 'is_primary_duplicate', 'categories', 'tags',
            'entities', 'ai_analysis'
        ]

class InformationSourceSerializer(serializers.ModelSerializer):
    connector_name = serializers.CharField(source='connector.name', read_only=True)
    connector_type = serializers.CharField(source='connector.connector_type', read_only=True)

    class Meta:
        model = InformationSource
        fields = [
            'id', 'name', 'connector', 'connector_name', 'connector_type',
            'source_type', 'endpoint_url', 'collection_frequency_minutes',
            'priority', 'is_active', 'health_status', 'last_synced_at',
            'error_message', 'config', 'created_at'
        ]

class WebhookSerializer(serializers.ModelSerializer):
    class Meta:
        model = Webhook
        fields = ['id', 'name', 'target_url', 'is_active', 'events', 'created_at']
