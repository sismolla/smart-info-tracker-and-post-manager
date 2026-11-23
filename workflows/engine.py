import logging
from django.utils import timezone
from intelligence.models import CollectedItem
from intelligence.dedup import DeduplicationEngine
from intelligence.ai_client import AIEngine
from .models import Workflow, WorkflowExecution

logger = logging.getLogger(__name__)

class PipelineEngine:
    """
    Coordinates item ingestion, deduplication, AI processing, and editorial routing.
    """

    @classmethod
    def process_item(cls, item: CollectedItem, workflow: Workflow = None) -> CollectedItem:
        """
        Executes end-to-end intelligence processing on a single collected item.
        """
        # 1. Step 1: Deduplication Check
        is_dup, dup_group = DeduplicationEngine.check_and_cluster(item)
        if is_dup:
            logger.info(f"Item #{item.id} detected as duplicate. Skipping expensive AI processing.")
            return item

        # 2. Step 2: AI Intelligence Analysis
        ai_engine = AIEngine()
        analysis = ai_engine.analyze_item(item)

        # Freshness Gate: Auto-drop items older than max_age_days (default 3 days)
        max_age_days = (item.source.config or {}).get('max_age_days', 3) if item.source else 3
        if item.published_at:
            age_days = (timezone.now() - item.published_at).total_seconds() / 86400.0
            if age_days > max_age_days:
                item.status = 'rejected'
                item.editorial_notes = f"Auto-dropped: Article is {round(age_days, 1)} days old (published {item.published_at.strftime('%Y-%m-%d')}), exceeding {max_age_days}-day limit."
                item.save(update_fields=['status', 'editorial_notes'])
                logger.info(f"Item #{item.id} auto-rejected: {round(age_days, 1)}d old exceeds {max_age_days}d limit.")
                return item

        # 3. Step 3: Workflow Auto-Approval Check
        # Find workflow: prefer source-specific, then fall back to any active workflow
        if not workflow:
            workflow = (
                Workflow.objects.filter(is_active=True, source=item.source).first()
                or Workflow.objects.filter(is_active=True, source__isnull=True).first()
            )

        if workflow and workflow.auto_approve:
            if analysis.relevance_score >= workflow.auto_approve_min_score:
                item.status = 'approved'
                item.save(update_fields=['status'])
                logger.info(f"Item #{item.id} auto-approved by workflow '{workflow.name}' (score {analysis.relevance_score})")

                if workflow.auto_publish:
                    from publishing.publishers import PublishingManager
                    PublishingManager.publish_item(item, channel='auto_workflow')

        return item
