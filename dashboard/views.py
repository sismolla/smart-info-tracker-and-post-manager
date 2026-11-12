import os
import shutil
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.db.models import Count, Q
from django.utils import timezone
from connectors.models import Connector, ConnectedAccount, InformationSource, CollectionRun
from intelligence.models import CollectedItem, Category, ExtractedEntity, AIAnalysis, DuplicateGroup
from publishing.models import Webhook, Publication
from publishing.publishers import PublishingManager
from core.models import DatabaseLock, AuditLog, SystemSetting
from workflows.engine import PipelineEngine

def overview_view(request):
    """Main executive dashboard view."""
    now = timezone.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # Metrics
    total_sources = InformationSource.objects.count()
    active_sources = InformationSource.objects.filter(is_active=True).count()
    total_items = CollectedItem.objects.count()
    today_items = CollectedItem.objects.filter(collected_at__gte=today_start).count()
    pending_approval = CollectedItem.objects.filter(status='ai_processed').count()
    duplicates_detected = CollectedItem.objects.filter(is_primary_duplicate=False).count()
    recent_runs = CollectionRun.objects.select_related('source')[:8]
    failed_runs = CollectionRun.objects.filter(status='failed').count()
    recent_items = CollectedItem.objects.select_related('source', 'ai_analysis').prefetch_related('categories')[:6]
    categories = Category.objects.annotate(item_count=Count('items')).order_by('-item_count')[:6]

    context = {
        'total_sources': total_sources,
        'active_sources': active_sources,
        'total_items': total_items,
        'today_items': today_items,
        'pending_approval': pending_approval,
        'duplicates_detected': duplicates_detected,
        'failed_runs': failed_runs,
        'recent_runs': recent_runs,
        'recent_items': recent_items,
        'categories': categories,
    }
    return render(request, 'dashboard/overview.html', context)

def sources_view(request):
    """Source configuration, monitoring and connectivity testing."""
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'add_source':
            connector_id = request.POST.get('connector_id')
            name = request.POST.get('name')
            endpoint = request.POST.get('endpoint_url')
            source_type = request.POST.get('source_type', 'channel')
            freq = int(request.POST.get('frequency', 30))
            priority = int(request.POST.get('priority', 3))

            connector = get_object_or_404(Connector, id=connector_id)
            InformationSource.objects.create(
                connector=connector,
                name=name,
                endpoint_url=endpoint,
                source_type=source_type,
                collection_frequency_minutes=freq,
                priority=priority
            )
            messages.success(request, f"Source '{name}' added successfully.")
            return redirect('dashboard_sources')

        elif action == 'toggle_status':
            source_id = request.POST.get('source_id')
            source = get_object_or_404(InformationSource, id=source_id)
            source.is_active = not source.is_active
            source.health_status = 'healthy' if source.is_active else 'paused'
            source.save(update_fields=['is_active', 'health_status'])
            messages.info(request, f"Source '{source.name}' status toggled to {'Active' if source.is_active else 'Paused'}.")
            return redirect('dashboard_sources')

    sources = InformationSource.objects.select_related('connector', 'account').annotate(
        items_count=Count('items')
    ).all()
    connectors = Connector.objects.filter(is_active=True)

    context = {
        'sources': sources,
        'connectors': connectors,
    }
    return render(request, 'dashboard/sources.html', context)

def items_view(request):
    """Searchable, filterable repository of collected intelligence."""
    qs = CollectedItem.objects.select_related('source', 'entities', 'ai_analysis').prefetch_related('categories')

    status_filter = request.GET.get('status')
    if status_filter:
        qs = qs.filter(status=status_filter)

    cat_filter = request.GET.get('category')
    if cat_filter:
        qs = qs.filter(categories__slug=cat_filter)

    source_filter = request.GET.get('source')
    if source_filter:
        qs = qs.filter(source_id=source_filter)

    search = request.GET.get('q')
    if search:
        qs = qs.filter(
            Q(title__icontains=search) |
            Q(original_content__icontains=search) |
            Q(entities__organization__icontains=search)
        )

    items = qs[:50]
    categories = Category.objects.all()
    sources = InformationSource.objects.all()

    context = {
        'items': items,
        'categories': categories,
        'sources': sources,
        'selected_status': status_filter,
        'selected_cat': cat_filter,
        'search_query': search or '',
    }
    return render(request, 'dashboard/items.html', context)

def item_detail_view(request, item_id):
    """Detailed view for single item with approval & publishing actions."""
    item = get_object_or_404(CollectedItem.objects.select_related('source', 'entities', 'ai_analysis'), id=item_id)

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'approve':
            item.status = 'approved'
            item.save(update_fields=['status'])
            messages.success(request, f"Item #{item.id} approved.")
        elif action == 'reject':
            item.status = 'rejected'
            item.save(update_fields=['status'])
            messages.warning(request, f"Item #{item.id} rejected.")
        elif action == 'publish':
            PublishingManager.publish_item(item, channel='dashboard')
            messages.success(request, f"Item #{item.id} published successfully.")
        elif action == 'reanalyze':
            from intelligence.ai_client import AIEngine
            AIEngine().analyze_item(item)
            messages.info(request, f"Item #{item.id} re-analyzed by AI Engine.")
        return redirect('dashboard_item_detail', item_id=item.id)

    duplicates = item.duplicate_group.items.exclude(id=item.id) if item.duplicate_group else []

    context = {
        'item': item,
        'duplicates': duplicates,
    }
    return render(request, 'dashboard/item_detail.html', context)

def ai_settings_view(request):
    """AI Provider configuration and usage statistics."""
    from django.conf import settings
    has_gemini = bool(getattr(settings, 'GEMINI_API_KEY', ''))
    model_name = getattr(settings, 'GEMINI_MODEL', 'gemini-1.5-flash')

    analyzed_count = AIAnalysis.objects.count()
    avg_score = 0
    if analyzed_count > 0:
        total_score = sum(AIAnalysis.objects.values_list('relevance_score', flat=True))
        avg_score = round(total_score / analyzed_count, 1)

    context = {
        'has_gemini_key': has_gemini,
        'model_name': model_name,
        'analyzed_count': analyzed_count,
        'avg_score': avg_score,
    }
    return render(request, 'dashboard/ai_settings.html', context)

def publishing_view(request):
    """Editorial publishing queue, webhooks, and syndication."""
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'add_webhook':
            name = request.POST.get('name')
            url = request.POST.get('target_url')
            secret = request.POST.get('secret_token', '')
            Webhook.objects.create(name=name, target_url=url, secret_token=secret)
            messages.success(request, f"Webhook '{name}' registered.")
            return redirect('dashboard_publishing')

    publications = Publication.objects.select_related('item')[:20]
    webhooks = Webhook.objects.all()

    context = {
        'publications': publications,
        'webhooks': webhooks,
    }
    return render(request, 'dashboard/publishing.html', context)

def health_view(request):
    """cPanel diagnostic and operational health monitoring."""
    from django.conf import settings
    total, used, free = shutil.disk_usage(settings.BASE_DIR)
    active_locks = DatabaseLock.objects.filter(expires_at__gt=timezone.now())

    context = {
        'execution_mode': getattr(settings, 'EXECUTION_MODE', 'cpanel_cron'),
        'batch_limit': getattr(settings, 'BATCH_COLLECTION_LIMIT', 30),
        'free_disk_gb': round(free / (1024**3), 2),
        'total_disk_gb': round(total / (1024**3), 2),
        'active_locks': active_locks,
        'media_writable': os.access(settings.MEDIA_ROOT, os.W_OK) if os.path.exists(settings.MEDIA_ROOT) else True,
        'python_version': os.sys.version,
    }
    return render(request, 'dashboard/health.html', context)
