import logging
import gc
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from django import db
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.conf import settings
from core.models import DatabaseLock, AuditLog
from connectors.models import InformationSource, CollectionRun
from connectors.base import registry
from intelligence.models import CollectedItem
from workflows.engine import PipelineEngine

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = "Runs a bounded collection cycle for active sources. Designed specifically for cPanel cron jobs."

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=getattr(settings, 'BATCH_COLLECTION_LIMIT', 30), help='Maximum items per source')
        parser.add_argument('--source-id', type=int, default=None, help='Sync a specific source ID only')
        parser.add_argument('--force', action='store_true', help='Bypass frequency check')

    def handle(self, *args, **options):
        limit = options['limit']
        source_id = options['source_id']
        force = options['force']
        lock_key = "cron_collection_batch_lock"
        timeout = getattr(settings, 'CRON_LOCK_TIMEOUT_SECONDS', 300)

        # 1. Acquire Distributed Atomic Lock
        if not DatabaseLock.acquire(lock_key, timeout_seconds=timeout):
            self.stdout.write(self.style.WARNING("Collection job already running or locked. Exiting gracefully."))
            return

        self.stdout.write(self.style.SUCCESS(f"Acquired lock '{lock_key}'. Starting collection batch..."))

        try:
            sources_qs = InformationSource.objects.filter(is_active=True).select_related('connector', 'account')
            if source_id:
                sources_qs = sources_qs.filter(id=source_id)

            now = timezone.now()
            eligible_sources = []

            for src in sources_qs:
                if force or not src.last_synced_at:
                    eligible_sources.append(src)
                else:
                    due_time = src.last_synced_at + timedelta(minutes=src.collection_frequency_minutes)
                    if now >= due_time:
                        eligible_sources.append(src)

            self.stdout.write(f"Found {len(eligible_sources)} eligible sources ready for synchronization.")

            if not eligible_sources:
                return

            def process_source(source):
                # Each thread needs its own fresh DB connection
                db.close_old_connections()

                self.stdout.write(f"--- Synchronizing: {source.name} [{source.connector.name}] ---")
                run = CollectionRun.objects.create(
                    source=source,
                    execution_mode='cpanel_cron',
                    status='running'
                )

                try:
                    connector_cls = registry.get(source.connector.connector_type)
                    if not connector_cls:
                        raise Exception(f"No connector registered for '{source.connector.connector_type}'")

                    connector = connector_cls(account=source.account)
                    new_items = connector.fetch_new_items(source, since=source.last_synced_at, limit=limit)

                    run.items_discovered = len(new_items)
                    saved_count = 0
                    dup_count = 0
                    stale_count = 0

                    max_age_days = (source.config or {}).get('max_age_days', 3)
                    cutoff_date = timezone.now() - timedelta(days=max_age_days)

                    for raw in new_items:
                        # Drop stale items older than max_age_days (default 3 days)
                        if raw.published_at and raw.published_at < cutoff_date:
                            stale_count += 1
                            self.stdout.write(f"  -> Skipping late item '{raw.title[:50]}' ({raw.published_at.strftime('%Y-%m-%d')}) > {max_age_days}d old.")
                            continue

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
                                'media_urls': raw.media_urls or [],
                            }
                        )

                        if created:
                            # Process item through intelligence pipeline (Dedup -> AI -> Review)
                            processed = PipelineEngine.process_item(item)
                            if processed.status == 'duplicate':
                                dup_count += 1
                            else:
                                saved_count += 1
                        else:
                            dup_count += 1

                    run.items_saved = saved_count
                    run.duplicates_skipped = dup_count
                    run.status = 'success'
                    run.finished_at = timezone.now()
                    run.save()

                    source.last_synced_at = timezone.now()
                    source.health_status = 'healthy'
                    source.error_message = ''
                    source.save(update_fields=['last_synced_at', 'health_status', 'error_message'])

                    self.stdout.write(self.style.SUCCESS(
                        f"  -> {source.name}: {saved_count} new items saved, {dup_count} duplicates skipped, {stale_count} stale dropped."
                    ))
                    return {'source': source.name, 'status': 'success', 'saved': saved_count, 'duplicates': dup_count}

                except Exception as e:
                    logger.error(f"Failed collection for source {source.name}: {e}")
                    run.status = 'failed'
                    run.error_details = str(e)
                    run.finished_at = timezone.now()
                    run.save()

                    source.health_status = 'failing'
                    source.error_message = str(e)[:250]
                    source.save(update_fields=['health_status', 'error_message'])
                    self.stdout.write(self.style.ERROR(f"  -> Error on {source.name}: {e}"))
                    return {'source': source.name, 'status': 'failed', 'error': str(e)}

            # 2. Run all sources in parallel (capped at 3 workers for cPanel shared hosting)
            max_workers = min(3, len(eligible_sources))
            results = []

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(process_source, source): source for source in eligible_sources}
                for future in as_completed(futures):
                    try:
                        result = future.result()
                        results.append(result)
                    except Exception as e:
                        source = futures[future]
                        logger.error(f"Unhandled exception in thread for source {source.name}: {e}")
                        results.append({'source': source.name, 'status': 'failed', 'error': str(e)})

            # 3. Summary
            succeeded = [r for r in results if r.get('status') == 'success']
            failed = [r for r in results if r.get('status') == 'failed']
            total_saved = sum(r.get('saved', 0) for r in succeeded)
            total_dups = sum(r.get('duplicates', 0) for r in succeeded)
            self.stdout.write(self.style.SUCCESS(
                f"Batch complete: {len(succeeded)}/{len(eligible_sources)} sources succeeded. "
                f"{total_saved} items saved, {total_dups} duplicates skipped."
            ))
            if failed:
                self.stdout.write(self.style.ERROR(
                    f"{len(failed)} source(s) failed: {', '.join(r['source'] for r in failed)}"
                ))

            # 4. Garbage collection after all threads complete (not inside threads)
            gc.collect()

        finally:
            DatabaseLock.release(lock_key)
            self.stdout.write(self.style.SUCCESS("Released lock. Collection batch complete."))
