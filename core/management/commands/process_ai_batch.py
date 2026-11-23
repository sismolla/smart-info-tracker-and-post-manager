import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from django import db
from django.core.management.base import BaseCommand
from intelligence.models import CollectedItem
from intelligence.ai_client import AIEngine

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = "Processes pending or un-analyzed collected items using the AI Engine."

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=20, help='Max items to analyze in this batch')

    def handle(self, *args, **options):
        limit = options['limit']
        pending_items = list(CollectedItem.objects.filter(
            status__in=['ingested', 'dedup_checked']
        ).select_related('source')[:limit])

        self.stdout.write(f"Found {len(pending_items)} items requiring AI analysis...")
        ai_engine = AIEngine()

        def process_item(item):
            db.close_old_connections()
            try:
                analysis = ai_engine.analyze_item(item)
                return (item, analysis, None)
            except Exception as e:
                return (item, None, e)

        count = 0
        max_workers = min(2, limit)  # cPanel-safe: 2 threads max for AI calls
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(process_item, item): item for item in pending_items}
            for future in as_completed(futures):
                item, analysis, error = future.result()
                if error is not None:
                    self.stdout.write(self.style.ERROR(f"Failed analysis on #{item.id}: {error}"))
                else:
                    self.stdout.write(self.style.SUCCESS(
                        f"Analyzed #{item.id} - Score: {analysis.relevance_score}/100 [{analysis.provider}]"
                    ))
                    count += 1

        self.stdout.write(self.style.SUCCESS(f"Completed AI processing batch: {count} items processed."))
