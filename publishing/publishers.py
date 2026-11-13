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
    def publish_item(cls, item: CollectedItem, channel: str = 'webhook', dispatch_social: bool = True) -> Publication:
        """
        Publishes an approved item and dispatches to registered active webhooks,
        as well as LinkedIn and Facebook if credentials are configured.
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

        # 3. Dispatch to Social Channels if enabled
        if dispatch_social:
            cls.publish_to_linkedin(item)
            cls.publish_to_facebook(item)

        return pub

    @classmethod
    def publish_to_linkedin(cls, item: CollectedItem) -> bool:
        """
        Publishes formatted intelligence post to authorized LinkedIn Company / Organization page
        via LinkedIn UGC Posts API v2.
        """
        from django.conf import settings
        token = getattr(settings, 'LINKEDIN_ACCESS_TOKEN', '')
        org_urn = getattr(settings, 'LINKEDIN_ORG_URN', '')
        if not token or not org_urn:
            logger.debug("LinkedIn publishing skipped: LINKEDIN_ACCESS_TOKEN or LINKEDIN_ORG_URN not configured.")
            return False

        if not org_urn.startswith('urn:li:organization:'):
            org_urn = f"urn:li:organization:{org_urn}"

        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
            'X-Restli-Protocol-Version': '2.0.0',
        }

        entities = getattr(item, 'entities', None)
        org_text = f"🏢 Organization: {entities.organization}\n" if entities and entities.organization else ""
        ref_text = f"🏷️ Ref: {entities.reference_number}\n" if entities and entities.reference_number else ""
        budget_text = f"💰 Budget: {entities.estimated_budget}\n" if entities and entities.estimated_budget else ""
        deadline_text = f"⏰ Deadline: {entities.deadline_iso or entities.tender_deadline}\n" if entities and (entities.deadline_iso or entities.tender_deadline) else ""

        editorial_note_block = f"💡 Editorial Note:\n{item.editorial_notes}\n\n" if item.editorial_notes else ""
        summary_text = item.ai_analysis.short_summary if hasattr(item, 'ai_analysis') and item.ai_analysis else item.original_content[:800]
        commentary = (
            f"📢 {item.title}\n\n"
            f"{org_text}{ref_text}{budget_text}{deadline_text}\n"
            f"{editorial_note_block}"
            f"{summary_text}\n\n"
            f"🔗 Full Details: {item.canonical_url or 'https://marketintel.org'}"
        )

        first_img = next((u for u in item.media_urls if u and u.startswith('http')), None) if item.media_urls else None
        if first_img and item.canonical_url:
            share_content = {
                "shareCommentary": {"text": commentary[:2900]},
                "shareMediaCategory": "ARTICLE",
                "media": [{
                    "status": "READY",
                    "originalUrl": item.canonical_url,
                    "thumbnails": [{"url": first_img}],
                    "title": {"text": item.title[:200]}
                }]
            }
        else:
            share_content = {
                "shareCommentary": {"text": commentary[:2900]},
                "shareMediaCategory": "NONE"
            }

        payload = {
            "author": org_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": share_content
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"}
        }

        try:
            resp = requests.post("https://api.linkedin.com/v2/ugcPosts", headers=headers, json=payload, timeout=15)
            is_success = (resp.status_code == 201)
            Publication.objects.create(
                item=item,
                channel='linkedin',
                destination=org_urn,
                status='published' if is_success else 'failed',
                formatted_payload={'status_code': resp.status_code, 'response': resp.text[:500]}
            )
            if is_success:
                logger.info(f"Published Item #{item.id} to LinkedIn {org_urn}")
            else:
                logger.warning(f"LinkedIn publishing failed: {resp.status_code} - {resp.text}")
            return is_success
        except Exception as e:
            logger.error(f"Error publishing Item #{item.id} to LinkedIn: {e}")
            Publication.objects.create(
                item=item,
                channel='linkedin',
                destination=org_urn,
                status='failed',
                formatted_payload={'error': str(e)[:500]}
            )
            return False

    @classmethod
    def publish_to_facebook(cls, item: CollectedItem) -> bool:
        """
        Publishes formatted post to authorized Meta Facebook Page feed via Graph API v19+.
        """
        from django.conf import settings
        token = getattr(settings, 'FACEBOOK_PAGE_ACCESS_TOKEN', '')
        page_id = getattr(settings, 'FACEBOOK_PAGE_ID', '')
        if not token or not page_id:
            logger.debug("Facebook publishing skipped: FACEBOOK_PAGE_ACCESS_TOKEN or FACEBOOK_PAGE_ID not configured.")
            return False

        url = f"https://graph.facebook.com/v19.0/{page_id}/feed"

        entities = getattr(item, 'entities', None)
        org_text = f"🏢 Organization: {entities.organization}\n" if entities and entities.organization else ""
        ref_text = f"🏷️ Ref: {entities.reference_number}\n" if entities and entities.reference_number else ""
        budget_text = f"💰 Budget: {entities.estimated_budget}\n" if entities and entities.estimated_budget else ""
        deadline_text = f"⏰ Deadline: {entities.deadline_iso or entities.tender_deadline}\n" if entities and (entities.deadline_iso or entities.tender_deadline) else ""

        editorial_note_block = f"💡 Editorial Note:\n{item.editorial_notes}\n\n" if item.editorial_notes else ""
        summary_text = item.ai_analysis.short_summary if hasattr(item, 'ai_analysis') and item.ai_analysis else item.original_content[:1000]
        message = (
            f"📢 {item.title}\n\n"
            f"{org_text}{ref_text}{budget_text}{deadline_text}\n"
            f"{editorial_note_block}"
            f"{summary_text}\n\n"
            f"🔗 Source: {item.canonical_url or 'https://marketintel.org'}"
        )

        payload = {
            'message': message[:4000],
            'access_token': token,
        }
        if item.canonical_url and item.canonical_url.startswith('http'):
            payload['link'] = item.canonical_url
        if item.media_urls and isinstance(item.media_urls, list):
            first_img = next((u for u in item.media_urls if u and u.startswith('http')), None)
            if first_img:
                payload['picture'] = first_img

        try:
            resp = requests.post(url, data=payload, timeout=15)
            is_success = (resp.status_code == 200)
            Publication.objects.create(
                item=item,
                channel='facebook',
                destination=page_id,
                status='published' if is_success else 'failed',
                formatted_payload={'status_code': resp.status_code, 'response': resp.text[:500]}
            )
            if is_success:
                logger.info(f"Published Item #{item.id} to Facebook Page {page_id}")
            else:
                logger.warning(f"Facebook publishing failed: {resp.status_code} - {resp.text}")
            return is_success
        except Exception as e:
            logger.error(f"Error publishing Item #{item.id} to Facebook: {e}")
            Publication.objects.create(
                item=item,
                channel='facebook',
                destination=page_id,
                status='failed',
                formatted_payload={'error': str(e)[:500]}
            )
            return False

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
