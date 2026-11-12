import json
import logging
import requests
from typing import Dict, Any
from django.utils import timezone
from .models import Webhook, WebhookDelivery, Publication
from intelligence.models import CollectedItem

logger = logging.getLogger(__name__)

class PublishingManager:
    """
    Handles editorial publishing, format transformations, and syndication webhooks.
    """

    @classmethod
    def format_item_payload(cls, item: CollectedItem) -> Dict[str, Any]:
        """Formats item into standard external distribution payload."""
        entities = getattr(item, 'entities', None)
        analysis = getattr(item, 'ai_analysis', None)

        return {
            'id': item.id,
            'title': item.title,
            'original_content': item.original_content,
            'canonical_url': item.canonical_url,
            'source': {
                'name': item.source.name,
                'type': item.source.source_type,
                'connector': item.source.connector.name,
            },
            'published_at': item.published_at.isoformat() if item.published_at else None,
            'collected_at': item.collected_at.isoformat(),
            'categories': [c.name for c in item.categories.all()],
            'tags': [t.name for t in item.tags.all()],
            'entities': {
                'organization': entities.organization if entities else None,
                'reference_number': entities.reference_number if entities else None,
                'contact_person': entities.contact_person if entities else None,
                'phone_number': entities.phone_number if entities else None,
                'email': entities.email if entities else None,
                'location': entities.location if entities else None,
                'opportunity_type': entities.opportunity_type if entities else None,
                'financials': {
                    'estimated_budget': entities.estimated_budget if entities else None,
                    'bid_bond_amount': entities.bid_bond_amount if entities else None,
                    'document_fee': entities.document_fee if entities else None,
                    'salary_min': entities.salary_min if entities else None,
                    'salary_max': entities.salary_max if entities else None,
                    'currency': entities.currency if entities else 'ETB',
                } if entities else {},
                'dates': {
                    'deadline_iso': entities.deadline_iso if entities else None,
                    'deadline_original': entities.deadline_original if entities else None,
                } if entities else {},
                'price': entities.price if entities else None,
                'application_deadline': entities.application_deadline if entities else None,
                'tender_deadline': entities.tender_deadline if entities else None,
            } if entities else {},
            'ai_summary': {
                'short': analysis.short_summary if analysis else '',
                'detailed': analysis.detailed_summary if analysis else '',
                'implications': analysis.business_implications if analysis else '',
                'relevance_score': analysis.relevance_score if analysis else 50,
            } if analysis else {},
        }

    @classmethod
    def publish_item(cls, item: CollectedItem, channel: str = 'webhook') -> Publication:
        """
        Publishes an approved item and dispatches to registered active webhooks.
        """
        payload = cls.format_item_payload(item)
        
        # 1. Record Publication
        pub = Publication.objects.create(
            item=item,
            channel=channel,
            status='published',
            formatted_payload=payload
        )

        item.status = 'published'
        item.save(update_fields=['status'])

        # 2. Dispatch to Active Webhooks
        active_webhooks = Webhook.objects.filter(is_active=True)
        for wh in active_webhooks:
            cls.dispatch_webhook(wh, event_type='item.published', payload=payload)

        return pub

    @classmethod
    def dispatch_webhook(cls, webhook: Webhook, event_type: str, payload: Dict[str, Any]) -> bool:
        """Dispatches an HTTP POST payload to subscriber with HMAC signature."""
        body_bytes = json.dumps(payload, default=str).encode('utf-8')
        signature = webhook.generate_signature(body_bytes)

        headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'MarketIntel-Webhook/1.0',
            'X-Event-Type': event_type,
        }
        if signature:
            headers['X-Hub-Signature-256'] = f"sha256={signature}"

        try:
            resp = requests.post(webhook.target_url, data=body_bytes, headers=headers, timeout=8)
            is_success = (200 <= resp.status_code < 300)
            
            WebhookDelivery.objects.create(
                webhook=webhook,
                event_type=event_type,
                payload=payload,
                response_status=resp.status_code,
                response_body=resp.text[:500],
                is_success=is_success,
                attempt_count=1
            )
            return is_success
        except Exception as e:
            logger.error(f"Webhook delivery failed to {webhook.target_url}: {e}")
            WebhookDelivery.objects.create(
                webhook=webhook,
                event_type=event_type,
                payload=payload,
                response_status=0,
                response_body=str(e)[:500],
                is_success=False,
                attempt_count=1
            )
            return False
