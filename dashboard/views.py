import os
import shutil
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.utils import timezone
from django.conf import settings
from connectors.models import Connector, ConnectedAccount, InformationSource, CollectionRun
from intelligence.models import CollectedItem, Category, ExtractedEntity, AIAnalysis, DuplicateGroup, AIDailyUsageTracker, ContentVersion, TranscribedContent
from publishing.models import Webhook, Publication, PublishChannel
from publishing.publishers import PublishingManager, TelegramDispatcher, FacebookDispatcher, LinkedInDispatcher
from publishing.alerts import TelegramAlertDispatcher
from core.models import DatabaseLock, AuditLog, SystemSetting
from workflows.engine import PipelineEngine

def login_view(request):
    """Secure administrative authentication view."""
    if request.user.is_authenticated:
        return redirect('dashboard_overview')

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '').strip()
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            next_url = request.GET.get('next') or 'dashboard_overview'
            messages.success(request, f"Welcome back, {user.username}!")
            return redirect(next_url)
        else:
            messages.error(request, "Invalid username or password.")

    return render(request, 'dashboard/login.html')

def logout_view(request):
    """Terminates session securely."""
    logout(request)
    messages.info(request, "You have been logged out.")
    return redirect('login')

@login_required(login_url='login')
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
    recent_items = CollectedItem.objects.select_related('source', 'ai_analysis', 'entities').prefetch_related('categories')[:6]
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

@login_required(login_url='login')
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

            # Advanced web crawling options
            item_selector = request.POST.get('item_selector', '').strip()
            title_selector = request.POST.get('title_selector', '').strip()
            link_selector = request.POST.get('link_selector', '').strip()
            max_pages = int(request.POST.get('max_pages', 1) or 1)
            crawl_detail = request.POST.get('crawl_detail') == 'on'
            render_js = request.POST.get('render_js') == 'on'

            config = {}
            if item_selector:
                config['item_selector'] = item_selector
            if title_selector:
                config['title_selector'] = title_selector
            if link_selector:
                config['link_selector'] = link_selector
            if max_pages > 1:
                config['max_pages'] = max_pages
            if crawl_detail:
                config['crawl_detail'] = True
            if render_js:
                config['render_js'] = True

            connector = get_object_or_404(Connector, id=connector_id)
            InformationSource.objects.create(
                connector=connector,
                name=name,
                endpoint_url=endpoint,
                source_type=source_type,
                collection_frequency_minutes=freq,
                priority=priority,
                config=config,
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


@login_required(login_url='login')
def source_preview_api(request):
    """
    Live test and inspection endpoint for web and feed scrapers.
    Does a dry-run extraction (up to 4 items) without persisting to DB or running AI pipeline,
    and returns structured JSON showing what elements, titles, detail pages, and media were found.
    """
    from django.http import JsonResponse
    import time
    from unittest.mock import MagicMock
    from connectors.base import registry

    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'POST method required.'}, status=405)

    source_id = request.POST.get('source_id')
    endpoint_url = request.POST.get('endpoint_url', '').strip()
    source_type = request.POST.get('source_type', 'website')
    connector_type = request.POST.get('connector_type', 'web')

    item_selector = request.POST.get('item_selector', '').strip()
    title_selector = request.POST.get('title_selector', '').strip()
    link_selector = request.POST.get('link_selector', '').strip()
    crawl_detail = request.POST.get('crawl_detail') in ['on', 'true', '1', True]
    render_js = request.POST.get('render_js') in ['on', 'true', '1', True]
    max_pages = int(request.POST.get('max_pages', 1) or 1)

    # If testing an existing source from dashboard
    if source_id:
        src = get_object_or_404(InformationSource, id=source_id)
        endpoint_url = src.endpoint_url
        source_type = src.source_type
        connector_type = src.connector.connector_type
        cfg = src.config or {}
        item_selector = cfg.get('item_selector', item_selector)
        title_selector = cfg.get('title_selector', title_selector)
        link_selector = cfg.get('link_selector', link_selector)
        crawl_detail = cfg.get('crawl_detail', crawl_detail)
        render_js = cfg.get('render_js', render_js)
        max_pages = cfg.get('max_pages', max_pages)

    if not endpoint_url:
        return JsonResponse({'status': 'error', 'message': 'Endpoint URL or Identifier is required.'}, status=400)

    # Prepare transient config
    config = {
        'item_selector': item_selector or None,
        'title_selector': title_selector or None,
        'link_selector': link_selector or None,
        'crawl_detail': crawl_detail,
        'render_js': render_js,
        'max_pages': min(max_pages, 2),
        'timeout': 30,
        'detail_timeout': 25,
    }

    transient_source = MagicMock()
    transient_source.id = None
    transient_source.name = "Preview Test Source"
    transient_source.endpoint_url = endpoint_url
    transient_source.source_type = source_type
    transient_source.config = config

    connector_cls = registry.get(connector_type)
    if not connector_cls:
        from connectors.web import UniversalWebConnector
        connector_cls = UniversalWebConnector

    connector = connector_cls()

    start_time = time.time()
    try:
        extracted = connector.fetch_new_items(transient_source, limit=4)
        duration = round(time.time() - start_time, 2)

        items_data = []
        for it in extracted:
            snippet = (it.content_text or '')[:350]
            items_data.append({
                'title': it.title or 'Untitled Item',
                'url': it.url,
                'author': it.author or '',
                'content_snippet': snippet + ('...' if len(it.content_text or '') > 350 else ''),
                'content_length': len(it.content_text or ''),
                'media_urls': it.media_urls[:4],
                'media_count': len(it.media_urls),
                'is_detail_crawled': bool(it.metadata.get('two_level_crawled')),
            })

        return JsonResponse({
            'status': 'ok',
            'endpoint_url': endpoint_url,
            'selector_used': item_selector or 'Auto-detected (Tables / RSS / Full page)',
            'count': len(items_data),
            'duration_seconds': duration,
            'items': items_data,
        })
    except Exception as e:
        duration = round(time.time() - start_time, 2)
        return JsonResponse({
            'status': 'error',
            'endpoint_url': endpoint_url,
            'selector_used': item_selector,
            'duration_seconds': duration,
            'message': str(e),
        }, status=400)

@login_required(login_url='login')
def items_view(request):
    """
    Searchable, filterable repository with high-efficiency Bulk Curation Actions
    (Bulk Approve, Bulk Reject, Bulk Archive, Bulk Publish).
    """
    if request.method == 'POST':
        bulk_action = request.POST.get('bulk_action')
        selected_ids = request.POST.getlist('selected_items')

        if not selected_ids:
            messages.warning(request, "No items were selected.")
            return redirect('dashboard_items')

        items_qs = CollectedItem.objects.filter(id__in=selected_ids)
        count = items_qs.count()

        if bulk_action == 'approve':
            items_qs.update(status='approved')
            # Trigger push alerts for approved high-priority items
            for item in items_qs.select_related('ai_analysis', 'entities', 'source'):
                TelegramAlertDispatcher.send_alert(item)
            messages.success(request, f"Successfully approved {count} items.")

        elif bulk_action == 'reject':
            items_qs.update(status='rejected')
            messages.warning(request, f"Successfully rejected {count} items.")

        elif bulk_action == 'archive':
            items_qs.update(status='archived')
            messages.info(request, f"Successfully archived {count} items.")

        elif bulk_action == 'publish':
            for item in items_qs.select_related('ai_analysis', 'entities', 'source'):
                PublishingManager.publish_item(item, channel='dashboard_bulk')
                TelegramAlertDispatcher.send_alert(item, force=True)
            messages.success(request, f"Successfully published {count} items to webhooks and alert bots.")

        return redirect('dashboard_items')

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
            Q(entities__organization__icontains=search) |
            Q(entities__reference_number__icontains=search)
        )

    items = qs[:60]
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

@login_required(login_url='login')
def item_detail_view(request, item_id):
    """
    Detailed intelligence view with AI synthesis, visual media gallery,
    interactive editorial editing studio, and multi-channel publication triggers.
    """
    item = get_object_or_404(CollectedItem.objects.select_related('source', 'entities', 'ai_analysis'), id=item_id)

    if request.method == 'POST':
        action = request.POST.get('action')

        # Check if form submitted editorial edits
        if action in ['save_edit', 'post_telegram', 'post_facebook', 'post_linkedin', 'post_all', 'post_selected']:
            new_title = request.POST.get('title', '').strip()
            new_content = request.POST.get('original_content', '').strip()
            new_editorial_notes = request.POST.get('editorial_notes', '').strip()
            new_summary = request.POST.get('short_summary', '').strip()
            media_input = request.POST.get('media_urls', '').strip()

            media_urls = []
            if media_input:
                for line in media_input.replace(',', '\n').splitlines():
                    cleaned = line.strip()
                    if cleaned and cleaned.startswith('http'):
                        if cleaned not in media_urls:
                            media_urls.append(cleaned)

            if new_title:
                item.title = new_title
            if new_content:
                item.original_content = new_content
            item.editorial_notes = new_editorial_notes
            item.media_urls = media_urls
            item.save()

            if new_summary and hasattr(item, 'ai_analysis') and item.ai_analysis:
                item.ai_analysis.short_summary = new_summary
                item.ai_analysis.save(update_fields=['short_summary'])

            # Log version history
            current_v = item.versions.count()
            ContentVersion.objects.create(
                item=item,
                version_number=current_v + 1,
                edited_by=request.user if request.user.is_authenticated else None,
                title=item.title,
                content_text=item.original_content,
                change_summary=f"Editorial update before {action}" if action != 'save_edit' else "Editorial update"
            )

            if action == 'save_edit':
                messages.success(request, f"Item #{item.id} editorial updates saved (Revision v{current_v + 1}).")

            elif action == 'post_selected':
                # Multi-channel post: user selected specific channel IDs
                selected_ids = request.POST.getlist('publish_channels')
                if not selected_ids:
                    messages.warning(request, "No channels selected. Tick at least one channel to publish to.")
                else:
                    channels = list(PublishChannel.objects.filter(id__in=selected_ids, is_active=True))
                    results = PublishingManager.publish_to_channels(item, channels, force=True)
                    success_names = [n for n, ok in results.items() if ok]
                    fail_names = []
                    for ch in channels:
                        if not results.get(ch.name):
                            ch.refresh_from_db(fields=['last_test_ok', 'last_test_message'])
                            err = ch.last_test_message.replace("Post failed: ", "") if not ch.last_test_ok and ch.last_test_message else "check channel credentials"
                            fail_names.append(f"{ch.name} ({err})")
                    if success_names:
                        item.status = 'published'
                        item.save(update_fields=['status'])
                        messages.success(request, f"✅ Published to: {', '.join(success_names)}")
                    if fail_names:
                        messages.error(request, f"❌ Failed for: {', '.join(fail_names)}")

            elif action == 'post_all':
                results = PublishingManager.publish_to_all_active(item, force=True)
                PublishingManager.dispatch_active_webhooks(item)
                success_names = [n for n, ok in results.items() if ok]
                fail_names = []
                for ch in PublishChannel.objects.filter(is_active=True):
                    if not results.get(ch.name):
                        ch.refresh_from_db(fields=['last_test_ok', 'last_test_message'])
                        err = ch.last_test_message.replace("Post failed: ", "") if not ch.last_test_ok and ch.last_test_message else "check credentials"
                        fail_names.append(f"{ch.name} ({err})")
                if results:
                    item.status = 'published'
                    item.save(update_fields=['status'])
                    messages.success(request, f"🚀 Published to all channels: {', '.join(success_names or ['(none active)'])}.")
                else:
                    messages.warning(request, "No active publish channels configured. Add channels in Channels Manager.")

            # Legacy single-type shims kept for backward compatibility
            elif action == 'post_telegram':
                success = TelegramAlertDispatcher.send_alert(item, force=True)
                if success:
                    item.status = 'published'
                    item.save(update_fields=['status'])
                    messages.success(request, f"Item #{item.id} broadcast to Telegram!")
                else:
                    messages.error(request, "Failed to broadcast to Telegram. Add a Telegram channel in Channels Manager.")

            elif action == 'post_facebook':
                success = PublishingManager.publish_to_facebook(item)
                if success:
                    item.status = 'published'
                    item.save(update_fields=['status'])
                    messages.success(request, f"Item #{item.id} posted to Facebook!")
                else:
                    messages.error(request, "Failed to post to Facebook. Add a Facebook channel in Channels Manager.")

            elif action == 'post_linkedin':
                success = PublishingManager.publish_to_linkedin(item)
                if success:
                    item.status = 'published'
                    item.save(update_fields=['status'])
                    messages.success(request, f"Item #{item.id} posted to LinkedIn!")
                else:
                    messages.error(request, "Failed to post to LinkedIn. Add a LinkedIn channel in Channels Manager.")

        elif action == 'approve':
            item.status = 'approved'
            item.save(update_fields=['status'])
            TelegramAlertDispatcher.send_alert(item)
            messages.success(request, f"Item #{item.id} approved and Telegram alert evaluated.")
        elif action == 'reject':
            item.status = 'rejected'
            item.save(update_fields=['status'])
            messages.warning(request, f"Item #{item.id} rejected.")
        elif action == 'publish':
            PublishingManager.publish_item(item, channel='dashboard')
            TelegramAlertDispatcher.send_alert(item, force=True)
            messages.success(request, f"Item #{item.id} published and broadcast.")
        elif action == 'reanalyze':
            from intelligence.ai_client import AIEngine
            AIEngine().analyze_item(item)
            messages.info(request, f"Item #{item.id} re-analyzed by AI Engine.")

        elif action in ['transcribe_both', 'transcribe_en', 'transcribe_am', 'translate_to_am', 'translate_to_en']:
            from intelligence.transcriber import NewsTranscriber
            tc = getattr(item, 'transcription', None)
            existing_en = tc.english_text if tc else ""
            existing_am = tc.amharic_text if tc else ""

            mode_map = {
                'transcribe_both': 'both',
                'transcribe_en': 'news_en',
                'transcribe_am': 'news_am',
                'translate_to_am': 'translate_am',
                'translate_to_en': 'translate_en',
            }
            mode = mode_map.get(action, 'both')

            transcriber = NewsTranscriber()
            res = transcriber.transcribe(
                content=item.original_content,
                mode=mode,
                existing_en=existing_en,
                existing_am=existing_am
            )

            if res['success']:
                TranscribedContent.objects.update_or_create(
                    item=item,
                    defaults={
                        'mode': mode,
                        'english_text': res['english'],
                        'amharic_text': res['amharic'],
                        'model_used': res['model_used'],
                    }
                )
                action_names = {
                    'transcribe_both': 'Bilingual News (English & Amharic)',
                    'transcribe_en': 'English News Article',
                    'transcribe_am': 'Amharic News Article',
                    'translate_to_am': 'Amharic Translation',
                    'translate_to_en': 'English Translation',
                }
                messages.success(request, f"✨ Successfully generated {action_names.get(action, 'News')} using {res['model_used']}!")
            else:
                messages.error(request, "Failed to generate news transcription. Verify your GEMINI_API_KEY in .env.")

        elif action == 'apply_transcription':
            target_lang = request.POST.get('target_lang', 'en')
            tc = getattr(item, 'transcription', None)
            if tc:
                if target_lang == 'en' and tc.english_text:
                    lines = [l.strip() for l in tc.english_text.splitlines() if l.strip()]
                    if lines:
                        item.title = lines[0][:280]
                    item.original_content = tc.english_text
                    item.language = 'en'
                    item.save()
                    # Log version history
                    current_v = item.versions.count()
                    ContentVersion.objects.create(
                        item=item,
                        version_number=current_v + 1,
                        edited_by=request.user if request.user.is_authenticated else None,
                        title=item.title,
                        content_text=item.original_content,
                        change_summary="Applied English News Article to Editorial Studio"
                    )
                    messages.success(request, "Applied English News Article to the Editorial Studio!")

                elif target_lang == 'am' and tc.amharic_text:
                    lines = [l.strip() for l in tc.amharic_text.splitlines() if l.strip()]
                    if lines:
                        item.title = lines[0][:280]
                    item.original_content = tc.amharic_text
                    item.language = 'am'
                    item.save()
                    current_v = item.versions.count()
                    ContentVersion.objects.create(
                        item=item,
                        version_number=current_v + 1,
                        edited_by=request.user if request.user.is_authenticated else None,
                        title=item.title,
                        content_text=item.original_content,
                        change_summary="Applied Amharic News Article to Editorial Studio"
                    )
                    messages.success(request, "Applied Amharic News Article to the Editorial Studio!")

                elif target_lang == 'bilingual' and (tc.english_text or tc.amharic_text):
                    bilingual_text = f"🇪🇹 በአማርኛ:\n{tc.amharic_text}\n\n====================\n\n🇬🇧 IN ENGLISH:\n{tc.english_text}"
                    lines = [l.strip() for l in tc.amharic_text.splitlines() if l.strip()] or [l.strip() for l in tc.english_text.splitlines() if l.strip()]
                    if lines:
                        item.title = lines[0][:280]
                    item.original_content = bilingual_text
                    item.save()
                    current_v = item.versions.count()
                    ContentVersion.objects.create(
                        item=item,
                        version_number=current_v + 1,
                        edited_by=request.user if request.user.is_authenticated else None,
                        title=item.title,
                        content_text=item.original_content,
                        change_summary="Applied Bilingual (Amharic & English) News Article to Editorial Studio"
                    )
                    messages.success(request, "Applied Bilingual (Amharic & English) News Article to Editorial Studio!")
                else:
                    messages.warning(request, f"No transcribed text available for target: {target_lang}")
            else:
                messages.warning(request, "No transcription available yet. Generate one first using the buttons above!")

        return redirect('dashboard_item_detail', item_id=item.id)

    duplicates = item.duplicate_group.items.exclude(id=item.id) if item.duplicate_group else []
    versions = item.versions.select_related('edited_by')[:5]
    transcription = getattr(item, 'transcription', None)
    publish_channels = PublishChannel.objects.filter(is_active=True).order_by('channel_type', 'name')

    context = {
        'item': item,
        'duplicates': duplicates,
        'versions': versions,
        'transcription': transcription,
        'media_urls_text': "\n".join(item.media_urls) if item.media_urls else "",
        'publish_channels': publish_channels,
    }
    return render(request, 'dashboard/item_detail.html', context)

@login_required(login_url='login')
def ai_settings_view(request):
    """AI Provider configuration, token metrics, and circuit breaker status."""
    has_gemini = bool(getattr(settings, 'GEMINI_API_KEY', ''))
    model_name = getattr(settings, 'GEMINI_MODEL', 'gemini-1.5-flash')

    analyzed_count = AIAnalysis.objects.count()
    avg_score = 0
    if analyzed_count > 0:
        total_score = sum(AIAnalysis.objects.values_list('relevance_score', flat=True))
        avg_score = round(total_score / analyzed_count, 1)

    today = timezone.now().date()
    today_tracker = AIDailyUsageTracker.objects.filter(date=today).first()
    spend_limit = getattr(settings, 'AI_DAILY_SPEND_LIMIT_USD', 2.00)
    max_calls = getattr(settings, 'AI_DAILY_MAX_CALLS', 500)

    context = {
        'has_gemini_key': has_gemini,
        'model_name': model_name,
        'analyzed_count': analyzed_count,
        'avg_score': avg_score,
        'today_tracker': today_tracker,
        'spend_limit': spend_limit,
        'max_calls': max_calls,
    }
    return render(request, 'dashboard/ai_settings.html', context)

@login_required(login_url='login')
def publishing_view(request):
    """Editorial publishing queue, webhooks, and push alerts."""
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'add_webhook':
            name = request.POST.get('name')
            url = request.POST.get('target_url')
            secret = request.POST.get('secret_token', '')
            Webhook.objects.create(name=name, target_url=url, secret_token=secret)
            messages.success(request, f"Webhook '{name}' registered.")
            return redirect('dashboard_publishing')

        elif action == 'test_telegram_alert':
            # Send test alert using most recent item
            sample_item = CollectedItem.objects.select_related('source', 'entities', 'ai_analysis').first()
            if sample_item:
                success = TelegramAlertDispatcher.send_alert(sample_item, force=True)
                if success:
                    messages.success(request, "Test Telegram Alert sent successfully to configured chat!")
                else:
                    messages.error(request, "Failed to send Telegram alert. Verify TELEGRAM_BOT_TOKEN and TELEGRAM_ALERT_CHAT_ID in .env.")
            else:
                messages.warning(request, "No intelligence items available to send test alert.")
            return redirect('dashboard_publishing')

        elif action == 'test_facebook_post':
            sample_item = CollectedItem.objects.select_related('source', 'entities', 'ai_analysis').first()
            if sample_item:
                success = PublishingManager.publish_to_facebook(sample_item)
                if success:
                    messages.success(request, "Test Post published successfully to Facebook Page!")
                else:
                    messages.error(request, "Facebook post failed. Verify FACEBOOK_PAGE_ACCESS_TOKEN and FACEBOOK_PAGE_ID in .env.")
            else:
                messages.warning(request, "No intelligence items available to send test post.")
            return redirect('dashboard_publishing')

        elif action == 'test_linkedin_post':
            sample_item = CollectedItem.objects.select_related('source', 'entities', 'ai_analysis').first()
            if sample_item:
                success = PublishingManager.publish_to_linkedin(sample_item)
                if success:
                    messages.success(request, "Test Post published successfully to LinkedIn Organization!")
                else:
                    messages.error(request, "LinkedIn post failed. Verify LINKEDIN_ACCESS_TOKEN and LINKEDIN_ORG_URN in .env.")
            else:
                messages.warning(request, "No intelligence items available to send test post.")
            return redirect('dashboard_publishing')

    publications = Publication.objects.select_related('item')[:20]
    webhooks = Webhook.objects.all()

    context = {
        'publications': publications,
        'webhooks': webhooks,
        'alert_chat_id': getattr(settings, 'TELEGRAM_ALERT_CHAT_ID', ''),
        'alert_min_score': getattr(settings, 'TELEGRAM_ALERT_MIN_SCORE', 75),
        'has_bot_token': bool(getattr(settings, 'TELEGRAM_BOT_TOKEN', '')),
        'has_facebook_token': bool(getattr(settings, 'FACEBOOK_PAGE_ACCESS_TOKEN', '')),
        'facebook_page_id': getattr(settings, 'FACEBOOK_PAGE_ID', ''),
        'has_linkedin_token': bool(getattr(settings, 'LINKEDIN_ACCESS_TOKEN', '')),
        'linkedin_org_urn': getattr(settings, 'LINKEDIN_ORG_URN', ''),
    }
    return render(request, 'dashboard/publishing.html', context)

@login_required(login_url='login')
def health_view(request):
    """cPanel diagnostic and operational health monitoring."""
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


@login_required(login_url='login')
def channels_view(request):
    """
    Publish Channels Manager — connect Telegram, Facebook, and LinkedIn
    destinations stored in the database instead of .env.
    """
    TYPE_FIELDS = {
        'telegram': ['bot_token', 'chat_id', 'topic_id', 'min_score'],
        'telegram_group': ['bot_token', 'chat_id', 'topic_id', 'min_score'],
        'facebook': ['page_access_token', 'page_id'],
        'linkedin': ['access_token', 'org_urn'],
    }

    if request.method == 'POST':
        action = request.POST.get('action')

        # --- Add new channel ---
        if action == 'add_channel':
            name         = request.POST.get('name', '').strip()
            channel_type = request.POST.get('channel_type', '').strip()
            description  = request.POST.get('description', '').strip()

            if not name or channel_type not in TYPE_FIELDS:
                messages.error(request, "Name and a valid channel type are required.")
                return redirect('dashboard_channels')

            ch = PublishChannel(name=name, channel_type=channel_type, description=description)
            cred_keys = TYPE_FIELDS[channel_type]
            creds = {k: request.POST.get(k, '').strip() for k in cred_keys}
            ch.set_credentials(creds)
            ch.save()
            messages.success(request, f"✅ Channel '{name}' connected successfully!")
            return redirect('dashboard_channels')

        # --- Toggle active / pause ---
        elif action == 'toggle_channel':
            ch = get_object_or_404(PublishChannel, id=request.POST.get('channel_id'))
            ch.is_active = not ch.is_active
            ch.save(update_fields=['is_active'])
            state = "activated" if ch.is_active else "paused"
            messages.info(request, f"Channel '{ch.name}' {state}.")
            return redirect('dashboard_channels')

        # --- Delete channel ---
        elif action == 'delete_channel':
            ch = get_object_or_404(PublishChannel, id=request.POST.get('channel_id'))
            name = ch.name
            ch.delete()
            messages.warning(request, f"Channel '{name}' removed.")
            return redirect('dashboard_channels')

        # --- Test / verify credentials ---
        elif action == 'test_channel':
            ch = get_object_or_404(PublishChannel, id=request.POST.get('channel_id'))
            ok, msg = PublishingManager.test_channel(ch)
            if ok:
                messages.success(request, f"✅ '{ch.name}' connected — {msg}")
            else:
                messages.error(request, f"❌ '{ch.name}' test failed — {msg}")
            return redirect('dashboard_channels')

        # --- Update credentials inline ---
        elif action == 'update_channel':
            ch = get_object_or_404(PublishChannel, id=request.POST.get('channel_id'))
            ch.name        = request.POST.get('name', ch.name).strip() or ch.name
            ch.description = request.POST.get('description', '').strip()
            cred_keys = TYPE_FIELDS.get(ch.channel_type, [])
            new_creds = {}
            old_creds = ch.get_credentials()
            for k in cred_keys:
                val = request.POST.get(k, '').strip()
                # Keep old value if field left blank (don't wipe secrets on partial edit)
                new_creds[k] = val if val else old_creds.get(k, '')
            ch.set_credentials(new_creds)
            ch.save()
            messages.success(request, f"Channel '{ch.name}' updated.")
            return redirect('dashboard_channels')

    channels = PublishChannel.objects.all().order_by('channel_type', 'name')
    recent_pubs = Publication.objects.select_related('item').filter(
        channel__in=['telegram', 'telegram_group', 'facebook', 'linkedin']
    ).order_by('-published_at')[:30]

    context = {
        'channels': channels,
        'recent_pubs': recent_pubs,
        'type_labels': {
            'telegram': ('📢', 'Telegram Channel', ['Bot Token', 'Channel ID / Username', 'Topic ID (Optional)', 'Min Relevance Score']),
            'telegram_group': ('👥', 'Telegram Group / Supergroup', ['Bot Token', 'Group ID / Chat ID', 'Topic ID (Optional)', 'Min Relevance Score']),
            'facebook': ('🌐', 'Facebook Page', ['Page Access Token', 'Facebook Page ID']),
            'linkedin': ('💼', 'LinkedIn Organization', ['Access Token', 'Organization URN or ID']),
        },
    }
    return render(request, 'dashboard/channels.html', context)


# ─── PWA Service Worker & Manifest Views ──────────────────────────────────────
from django.http import FileResponse, HttpResponse

def service_worker_view(request):
    """Serves sw.js from the root URL with Service-Worker-Allowed header."""
    sw_path = os.path.join(settings.BASE_DIR, 'dashboard', 'static', 'sw.js')
    if os.path.exists(sw_path):
        response = FileResponse(open(sw_path, 'rb'), content_type='application/javascript')
        response['Service-Worker-Allowed'] = '/'
        response['Cache-Control'] = 'no-cache'
        return response
    return HttpResponse("// sw.js not found", content_type='application/javascript', status=404)

def manifest_view(request):
    """Serves manifest.json from the root URL."""
    manifest_path = os.path.join(settings.BASE_DIR, 'dashboard', 'static', 'manifest.json')
    if os.path.exists(manifest_path):
        response = FileResponse(open(manifest_path, 'rb'), content_type='application/manifest+json')
        response['Cache-Control'] = 'public, max-age=3600'
        return response
    return HttpResponse("{}", content_type='application/manifest+json', status=404)

def offline_view(request):
    """Serves the offline fallback page."""
    offline_path = os.path.join(settings.BASE_DIR, 'dashboard', 'static', 'offline.html')
    if os.path.exists(offline_path):
        return FileResponse(open(offline_path, 'rb'), content_type='text/html')
    return HttpResponse("<h1>You are offline</h1>", content_type='text/html', status=503)

