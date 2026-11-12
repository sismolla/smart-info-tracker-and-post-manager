from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db.models import Q
from connectors.models import InformationSource, CollectionRun
from intelligence.models import CollectedItem, Category
from publishing.models import Webhook
from publishing.publishers import PublishingManager
from .serializers import (
    CollectedItemSerializer, InformationSourceSerializer,
    WebhookSerializer, CategorySerializer
)

class CollectedItemViewSet(viewsets.ModelViewSet):
    """
    API endpoint for searching, filtering, and curating collected intelligence items.
    """
    queryset = CollectedItem.objects.select_related('source', 'entities', 'ai_analysis').prefetch_related('categories', 'tags').all()
    serializer_class = CollectedItemSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        
        # Filtering parameters
        status_param = self.request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param)

        category_param = self.request.query_params.get('category')
        if category_param:
            qs = qs.filter(categories__slug=category_param)

        source_id = self.request.query_params.get('source_id')
        if source_id:
            qs = qs.filter(source_id=source_id)

        min_score = self.request.query_params.get('min_score')
        if min_score:
            qs = qs.filter(ai_analysis__relevance_score__gte=int(min_score))

        search_query = self.request.query_params.get('search')
        if search_query:
            qs = qs.filter(
                Q(title__icontains=search_query) |
                Q(original_content__icontains=search_query) |
                Q(entities__organization__icontains=search_query)
            )

        return qs

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        item = self.get_object()
        item.status = 'approved'
        item.save(update_fields=['status'])
        return Response({'status': 'approved', 'item_id': item.id})

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        item = self.get_object()
        item.status = 'rejected'
        item.save(update_fields=['status'])
        return Response({'status': 'rejected', 'item_id': item.id})

    @action(detail=True, methods=['post'])
    def publish(self, request, pk=None):
        item = self.get_object()
        pub = PublishingManager.publish_item(item, channel='api')
        return Response({'status': 'published', 'item_id': item.id, 'publication_id': pub.id})


class InformationSourceViewSet(viewsets.ModelViewSet):
    """
    API endpoint to register, configure, pause, and inspect information sources.
    """
    queryset = InformationSource.objects.select_related('connector', 'account').all()
    serializer_class = InformationSourceSerializer

    @action(detail=True, methods=['post'])
    def sync(self, request, pk=None):
        """Triggers an on-demand synchronization run for this source."""
        source = self.get_object()
        from connectors.base import registry
        connector_cls = registry.get(source.connector.connector_type)
        if not connector_cls:
            return Response({'error': f'Connector {source.connector.connector_type} not found.'}, status=400)

        conn = connector_cls(account=source.account)
        new_items = conn.fetch_new_items(source, limit=20)
        
        saved_count = 0
        from workflows.engine import PipelineEngine
        for raw in new_items:
            item, created = CollectedItem.objects.get_or_create(
                source=source,
                external_id=raw.external_id,
                defaults={
                    'title': raw.title,
                    'original_content': raw.content_text,
                    'canonical_url': raw.url,
                    'author': raw.author,
                    'published_at': raw.published_at,
                    'raw_payload': raw.raw_payload,
                }
            )
            if created:
                PipelineEngine.process_item(item)
                saved_count += 1

        source.last_synced_at = timezone.now()
        source.save(update_fields=['last_synced_at'])

        return Response({
            'status': 'sync_complete',
            'discovered': len(new_items),
            'saved': saved_count,
        })


class IntelligenceSummaryView(APIView):
    """
    Curated executive summary endpoint providing high-priority opportunities,
    tenders, jobs, and market trends.
    """
    def get(self, request):
        tenders = CollectedItem.objects.filter(categories__slug__icontains='tender')[:5]
        jobs = CollectedItem.objects.filter(categories__slug__icontains='job')[:5]
        healthcare = CollectedItem.objects.filter(categories__slug__icontains='health')[:5]
        recent = CollectedItem.objects.filter(is_primary_duplicate=True)[:10]

        return Response({
            'high_priority_tenders': CollectedItemSerializer(tenders, many=True).data,
            'recent_jobs': CollectedItemSerializer(jobs, many=True).data,
            'healthcare_intelligence': CollectedItemSerializer(healthcare, many=True).data,
            'recent_activity': CollectedItemSerializer(recent, many=True).data,
        })


class WebhookViewSet(viewsets.ModelViewSet):
    queryset = Webhook.objects.all()
    serializer_class = WebhookSerializer
