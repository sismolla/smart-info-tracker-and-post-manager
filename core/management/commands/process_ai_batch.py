import logging
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
        pending_items = CollectedItem.objects.filter(
            status__in=['ingested', 'dedup_checked']
        ).select_related('source')[:limit]

        self.stdout.write(f"Found {len(pending_items)} items requiring AI analysis...")
        ai_engine = AIEngine()

        count = 0
        for item in pending_items:
            try:
                analysis = ai_engine.analyze_item(item)
                self.stdout.write(self.style.SUCCESS(
                    f"Analyzed #{item.id} - Score: {analysis.relevance_score}/100 [{analysis.provider}]"
                ))
                count += 1
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Failed analysis on #{item.id}: {e}"))

        self.stdout.write(self.style.SUCCESS(f"Completed AI processing batch: {count} items processed."))
