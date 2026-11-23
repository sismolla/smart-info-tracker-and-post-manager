"""
Multi-channel dispatcher for the Intelligent Social Media Manager.

Credentials live in PublishChannel DB records (not .env).
Callers pass a list of PublishChannel objects; this module handles routing.
"""
import json
import logging
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, List
from django import db
from django.utils import timezone
from .models import Webhook, WebhookDelivery, Publication, PublishChannel
from intelligence.models import CollectedItem

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Telegram broadcaster
# ---------------------------------------------------------------------------

class TelegramDispatcher:
    MAX_CAPTION = 1024
    MAX_TEXT    = 4096

    @classmethod
    def send(cls, item: CollectedItem, channel: PublishChannel, force: bool = False) -> bool:
        """Post item to a single Telegram PublishChannel (Channel or Group). Returns True on success."""
        bot_token = channel.bot_token
        chat_id   = str(channel.chat_id or "").strip()
        topic_id  = channel.topic_id
        if not bot_token or not chat_id:
            logger.warning(f"Telegram channel '{channel.name}' missing bot_token or chat_id.")
            return False

        # Clean public link to @handle if needed
        if chat_id.startswith('https://t.me/'):
            chat_id = '@' + chat_id.replace('https://t.me/', '').rstrip('/')
        elif chat_id.startswith('t.me/'):
            chat_id = '@' + chat_id.replace('t.me/', '').rstrip('/')

        # Relevance gate
        score = item.ai_analysis.relevance_score if hasattr(item, 'ai_analysis') and item.ai_analysis else 50
        if not force and score < channel.tg_min_score:
            logger.debug(f"Item #{item.id} score {score} below threshold {channel.tg_min_score} for '{channel.name}'.")
            return False

        body = cls._build_body(item)
        images = [u for u in (item.media_urls or []) if u and str(u).startswith('http')]

        ok, err_desc = cls._deliver(item, bot_token, chat_id, body, images, topic_id=topic_id)

        is_group = channel.channel_type == PublishChannel.TYPE_TELEGRAM_GROUP
        dest_prefix = "Group" if is_group else "Channel"
        topic_str = f" [Topic #{topic_id}]" if topic_id else ""
        pub_channel = 'telegram_group' if is_group else 'telegram'

        Publication.objects.create(
            item=item,
            channel=pub_channel,
            destination=f"{dest_prefix}: {channel.name} ({chat_id}){topic_str}",
            status='published' if ok else 'failed',
            formatted_payload={'channel_id': channel.id, 'channel_name': channel.name, 'score': score, 'topic_id': topic_id, 'error': err_desc}
        )

        if not ok and err_desc:
            channel.last_test_ok = False
            channel.last_test_message = f"Post failed: {err_desc}"[:300]
            channel.save(update_fields=['last_test_ok', 'last_test_message'])

        return ok

    @classmethod
    def _build_body(cls, item: CollectedItem) -> str:
        parts = []
        if item.editorial_notes and item.editorial_notes.strip():
            parts.append(item.editorial_notes.strip())
            parts.append("")
        article = (item.original_content or item.title or "").strip()
        if article:
            parts.append(article)
        source_name = item.source.name if item.source else ""
        if source_name:
            parts.append("")
            parts.append(source_name)
        return "\n".join(parts)

    @classmethod
    def _deliver(cls, item, bot_token, chat_id, body, images, topic_id=None) -> tuple:
        last_err = ""
        if images:
            if len(images) == 1:
                ok, err = cls._send_photo(bot_token, chat_id, images[0], body[:cls.MAX_CAPTION], item, topic_id=topic_id)
                if ok:
                    return True, ""
                last_err = err
                return cls._send_text(bot_token, chat_id, body, item, topic_id=topic_id)
            # Media group
            media_group = [
                {'type': 'photo', 'media': url, **(
                    {'caption': body[:cls.MAX_CAPTION], 'parse_mode': 'HTML'} if i == 0 else {}
                )}
                for i, url in enumerate(images[:10])
            ]
            try:
                payload = {'chat_id': chat_id, 'media': media_group}
                if topic_id:
                    try:
                        payload['message_thread_id'] = int(topic_id)
                    except (ValueError, TypeError):
                        pass
                resp = requests.post(
                    f"https://api.telegram.org/bot{bot_token}/sendMediaGroup",
                    json=payload, timeout=15
                )
                if resp.status_code == 200 and resp.json().get('ok'):
                    logger.info(f"TG media group ({len(images)}) sent for Item #{item.id}")
                    return True, ""
                else:
                    last_err = resp.json().get('description', resp.text[:120])
            except Exception as e:
                last_err = str(e)
                logger.warning(f"sendMediaGroup exception: {e}")
            # Fallback to single photo
            ok, err = cls._send_photo(bot_token, chat_id, images[0], body[:cls.MAX_CAPTION], item, topic_id=topic_id)
            if ok:
                return True, ""
            if err:
                last_err = err
            return cls._send_text(bot_token, chat_id, body, item, topic_id=topic_id)
        return cls._send_text(bot_token, chat_id, body, item, topic_id=topic_id)

    @classmethod
    def _send_text(cls, bot_token, chat_id, text, item, topic_id=None) -> tuple:
        endpoint = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        for chunk in cls._split(text, cls.MAX_TEXT):
            payload = {
                'chat_id': chat_id,
                'text': chunk,
                'parse_mode': 'HTML',
                'disable_web_page_preview': False
            }
            if topic_id:
                try:
                    payload['message_thread_id'] = int(topic_id)
                except (ValueError, TypeError):
                    pass
            try:
                resp = requests.post(endpoint, json=payload, timeout=10)
                if not (resp.status_code == 200 and resp.json().get('ok')):
                    # Fallback without HTML parse mode in case of malformed tag
                    plain_payload = dict(payload)
                    plain_payload.pop('parse_mode', None)
                    resp = requests.post(endpoint, json=plain_payload, timeout=10)
                if not (resp.status_code == 200 and resp.json().get('ok')):
                    err_desc = resp.json().get('description', resp.text[:200])
                    logger.warning(f"TG sendMessage failed for #{item.id}: {err_desc}")
                    return False, err_desc
            except Exception as e:
                logger.error(f"TG sendMessage exception for #{item.id}: {e}")
                return False, str(e)
        logger.info(f"TG text posted for Item #{item.id}")
        return True, ""

    @classmethod
    def _send_photo(cls, bot_token, chat_id, photo_url, caption, item, topic_id=None) -> tuple:
        endpoint = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
        last_err = ""
        for parse_mode in ['HTML', None]:
            try:
                payload = {'chat_id': chat_id, 'photo': photo_url, 'caption': caption}
                if parse_mode:
                    payload['parse_mode'] = parse_mode
                if topic_id:
                    try:
                        payload['message_thread_id'] = int(topic_id)
                    except (ValueError, TypeError):
                        pass
                resp = requests.post(endpoint, json=payload, timeout=12)
                if resp.status_code == 200 and resp.json().get('ok'):
                    logger.info(f"TG photo sent for Item #{item.id}")
                    return True, ""
                else:
                    last_err = resp.json().get('description', resp.text[:120])
            except Exception as e:
                last_err = str(e)
                logger.warning(f"TG sendPhoto exception: {e}")
        return False, last_err

    @staticmethod
    def _split(text, limit):
        if len(text) <= limit:
            return [text]
        chunks = []
        while text:
            if len(text) <= limit:
                chunks.append(text); break
            cut = text.rfind('\n\n', 0, limit)
            if cut == -1: cut = text.rfind('\n', 0, limit)
            if cut == -1: cut = limit
            chunks.append(text[:cut].rstrip())
            text = text[cut:].lstrip()
        return [c for c in chunks if c]


# ---------------------------------------------------------------------------
# Facebook broadcaster
# ---------------------------------------------------------------------------

class FacebookDispatcher:

    @classmethod
    def send(cls, item: CollectedItem, channel: PublishChannel) -> bool:
        token   = channel.page_access_token
        page_id = channel.page_id
        if not token or not page_id:
            logger.warning(f"Facebook channel '{channel.name}' missing credentials.")
            return False

        entities      = getattr(item, 'entities', None)
        editorial     = f"💡 {item.editorial_notes.strip()}\n\n" if item.editorial_notes else ""
        article       = (item.original_content or item.title or "").strip()
        source_line   = f"\n\n{item.source.name}" if item.source else ""
        message       = f"{editorial}{article}{source_line}"

        payload = {
            'message':      message[:4000],
            'access_token': token,
        }
        if item.canonical_url and item.canonical_url.startswith('http'):
            payload['link'] = item.canonical_url
        if item.media_urls:
            first = next((u for u in item.media_urls if u and str(u).startswith('http')), None)
            if first:
                payload['picture'] = first

        try:
            resp = requests.post(f"https://graph.facebook.com/v19.0/{page_id}/feed",
                                 data=payload, timeout=15)
            ok = resp.status_code == 200
            Publication.objects.create(
                item=item, channel='facebook',
                destination=f"{channel.name} ({page_id})",
                status='published' if ok else 'failed',
                formatted_payload={'channel_id': channel.id, 'status_code': resp.status_code,
                                   'response': resp.text[:300]}
            )
            if ok:
                logger.info(f"FB posted Item #{item.id} via channel '{channel.name}'")
            else:
                logger.warning(f"FB post failed for #{item.id}: {resp.text[:200]}")
            return ok
        except Exception as e:
            logger.error(f"FB exception for #{item.id}: {e}")
            Publication.objects.create(item=item, channel='facebook',
                                       destination=channel.name, status='failed',
                                       formatted_payload={'error': str(e)[:300]})
            return False


# ---------------------------------------------------------------------------
# LinkedIn broadcaster
# ---------------------------------------------------------------------------

class LinkedInDispatcher:

    @classmethod
    def send(cls, item: CollectedItem, channel: PublishChannel) -> bool:
        token   = channel.access_token
        org_urn = channel.org_urn
        if not token or not org_urn:
            logger.warning(f"LinkedIn channel '{channel.name}' missing credentials.")
            return False

        editorial   = f"💡 {item.editorial_notes.strip()}\n\n" if item.editorial_notes else ""
        analysis    = getattr(item, 'ai_analysis', None)
        summary     = analysis.short_summary if analysis and analysis.short_summary else item.title
        source_line = f"\n\n{item.source.name}" if item.source else ""
        commentary  = f"{editorial}{summary}{source_line}"

        first_img = next((u for u in (item.media_urls or []) if u and str(u).startswith('http')), None)
        if first_img and item.canonical_url:
            share_content = {
                "shareCommentary": {"text": commentary[:2900]},
                "shareMediaCategory": "ARTICLE",
                "media": [{"status": "READY", "originalUrl": item.canonical_url,
                            "thumbnails": [{"url": first_img}], "title": {"text": item.title[:200]}}]
            }
        else:
            share_content = {
                "shareCommentary": {"text": commentary[:2900]},
                "shareMediaCategory": "NONE"
            }

        payload = {
            "author": org_urn, "lifecycleState": "PUBLISHED",
            "specificContent": {"com.linkedin.ugc.ShareContent": share_content},
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"}
        }
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
            'X-Restli-Protocol-Version': '2.0.0',
        }
        try:
            resp = requests.post("https://api.linkedin.com/v2/ugcPosts",
                                 headers=headers, json=payload, timeout=15)
            ok = resp.status_code == 201
            Publication.objects.create(
                item=item, channel='linkedin',
                destination=f"{channel.name} ({org_urn})",
                status='published' if ok else 'failed',
                formatted_payload={'channel_id': channel.id, 'status_code': resp.status_code,
                                   'response': resp.text[:300]}
            )
            if ok:
                logger.info(f"LI posted Item #{item.id} via channel '{channel.name}'")
            else:
                logger.warning(f"LI post failed for #{item.id}: {resp.status_code} {resp.text[:200]}")
            return ok
        except Exception as e:
            logger.error(f"LI exception for #{item.id}: {e}")
            Publication.objects.create(item=item, channel='linkedin',
                                       destination=channel.name, status='failed',
                                       formatted_payload={'error': str(e)[:300]})
            return False


# ---------------------------------------------------------------------------
# Main publishing manager
# ---------------------------------------------------------------------------

class PublishingManager:
    """
    Routes items to one or many PublishChannel objects + legacy webhooks.
    """

    @classmethod
    def publish_to_channels(cls, item: CollectedItem,
                             channels: List[PublishChannel],
                             force: bool = True) -> Dict[str, bool]:
        """
        Dispatch item to a list of PublishChannel objects in parallel.
        Returns {channel_name: bool} result map.
        """
        if not channels:
            return {}

        def _dispatch_one(ch: PublishChannel) -> tuple[str, bool]:
            db.close_old_connections()
            if not ch.is_active:
                return ch.name, False
            if ch.channel_type in (PublishChannel.TYPE_TELEGRAM, PublishChannel.TYPE_TELEGRAM_GROUP):
                return ch.name, TelegramDispatcher.send(item, ch, force=force)
            elif ch.channel_type == PublishChannel.TYPE_FACEBOOK:
                return ch.name, FacebookDispatcher.send(item, ch)
            elif ch.channel_type == PublishChannel.TYPE_LINKEDIN:
                return ch.name, LinkedInDispatcher.send(item, ch)
            else:
                logger.warning(f"Unknown channel type: {ch.channel_type}")
                return ch.name, False

        if len(channels) == 1:
            name, ok = _dispatch_one(channels[0])
            return {name: ok}

        results: Dict[str, bool] = {}
        max_workers = min(len(channels), 4)  # cPanel-safe: 4 channels max parallel
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {executor.submit(_dispatch_one, ch): ch for ch in channels}
            for future in as_completed(future_map):
                try:
                    name, ok = future.result()
                    results[name] = ok
                except Exception as exc:
                    ch = future_map[future]
                    logger.error(f"Channel '{ch.name}' dispatch raised: {exc}")
                    results[ch.name] = False
        return results

    @classmethod
    def publish_to_all_active(cls, item: CollectedItem, force: bool = True) -> Dict[str, bool]:
        """Dispatch to every active PublishChannel in the database."""
        channels = list(PublishChannel.objects.filter(is_active=True))
        return cls.publish_to_channels(item, channels, force=force)

    @classmethod
    def test_channel(cls, channel: PublishChannel) -> tuple[bool, str]:
        """
        Send a test ping to verify credentials.
        Returns (ok: bool, message: str).
        """
        try:
            if channel.channel_type in (PublishChannel.TYPE_TELEGRAM, PublishChannel.TYPE_TELEGRAM_GROUP):
                token = channel.bot_token
                chat_id = str(channel.chat_id or "").strip()
                topic_id = channel.topic_id
                if not token:
                    return False, "Missing bot_token"
                if chat_id.startswith('https://t.me/'):
                    chat_id = '@' + chat_id.replace('https://t.me/', '').rstrip('/')
                elif chat_id.startswith('t.me/'):
                    chat_id = '@' + chat_id.replace('t.me/', '').rstrip('/')

                resp = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=8)
                ok = resp.status_code == 200 and resp.json().get('ok')
                bot_info = resp.json().get('result', {}) if ok else {}
                bot_id = bot_info.get('id')
                bot_name = bot_info.get('username', '?')
                if not ok:
                    return False, f"Bot auth failed: {resp.text[:120]}"

                if chat_id:
                    chat_resp = requests.get(
                        f"https://api.telegram.org/bot{token}/getChat",
                        params={'chat_id': chat_id},
                        timeout=8
                    )
                    if chat_resp.status_code == 200 and chat_resp.json().get('ok'):
                        chat_info = chat_resp.json().get('result', {})
                        chat_title = chat_info.get('title') or chat_info.get('username') or chat_id
                        chat_type = chat_info.get('type', 'chat').title()
                        topic_str = f" [Topic #{topic_id}]" if topic_id else ""

                        # Check bot's admin membership and rights in this chat
                        if bot_id:
                            m_resp = requests.get(
                                f"https://api.telegram.org/bot{token}/getChatMember",
                                params={'chat_id': chat_id, 'user_id': bot_id},
                                timeout=8
                            )
                            if m_resp.status_code == 200 and m_resp.json().get('ok'):
                                m_info = m_resp.json().get('result', {})
                                m_status = m_info.get('status')
                                if m_status not in ('administrator', 'creator'):
                                    ok = False
                                    msg = f"Connected to {chat_type} '{chat_title}', BUT @{bot_name} is only a '{m_status}'. Add @{bot_name} as an Administrator with 'Post Messages' enabled!"
                                elif m_status == 'administrator' and m_info.get('can_post_messages') is False:
                                    ok = False
                                    msg = f"Connected to {chat_type} '{chat_title}', BUT @{bot_name} does not have 'Post Messages' admin permission! Enable it in Telegram."
                                else:
                                    ok = True
                                    msg = f"Connected as @{bot_name} (Admin with Post rights) to {chat_type}: '{chat_title}'{topic_str}"
                            else:
                                ok = True
                                msg = f"Connected as @{bot_name} to {chat_type}: '{chat_title}'{topic_str} (Ensure @{bot_name} is added as Admin)"
                        else:
                            ok = True
                            msg = f"Connected as @{bot_name} to {chat_type}: '{chat_title}'{topic_str}"
                    else:
                        err_desc = chat_resp.json().get('description', chat_resp.text[:100]) if chat_resp.status_code in (400, 403) else chat_resp.text[:100]
                        msg = f"Connected as @{bot_name}, but chat check failed ({err_desc}). Ensure bot is added to the {channel.get_channel_type_display()}."
                else:
                    msg = f"Connected as @{bot_name} (No Chat ID specified)"

            elif channel.channel_type == PublishChannel.TYPE_FACEBOOK:
                token   = channel.page_access_token
                page_id = channel.page_id
                if not token or not page_id:
                    return False, "Missing page_access_token or page_id"
                resp = requests.get(
                    f"https://graph.facebook.com/v19.0/{page_id}",
                    params={'access_token': token, 'fields': 'name,id'}, timeout=8
                )
                ok = resp.status_code == 200
                page_name = resp.json().get('name', '?') if ok else '?'
                msg = f"Connected to page: {page_name}" if ok else f"Auth failed: {resp.text[:120]}"

            elif channel.channel_type == PublishChannel.TYPE_LINKEDIN:
                token = channel.access_token
                if not token:
                    return False, "Missing access_token"
                resp = requests.get("https://api.linkedin.com/v2/userinfo",
                                    headers={'Authorization': f'Bearer {token}'}, timeout=8)
                ok = resp.status_code == 200
                name = resp.json().get('name', '?') if ok else '?'
                msg = f"Connected as: {name}" if ok else f"Auth failed: {resp.status_code} {resp.text[:120]}"
            else:
                return False, "Unknown channel type"

            channel.last_tested_at    = timezone.now()
            channel.last_test_ok      = ok
            channel.last_test_message = msg
            channel.save(update_fields=['last_tested_at', 'last_test_ok', 'last_test_message'])
            return ok, msg

        except Exception as e:
            msg = f"Connection error: {e}"
            channel.last_tested_at    = timezone.now()
            channel.last_test_ok      = False
            channel.last_test_message = msg[:300]
            channel.save(update_fields=['last_tested_at', 'last_test_ok', 'last_test_message'])
            return False, msg

    # --- Legacy webhook dispatch (unchanged) ----------------------------

    @classmethod
    def format_item_payload(cls, item: CollectedItem) -> Dict[str, Any]:
        entities = getattr(item, 'entities', None)
        analysis = getattr(item, 'ai_analysis', None)
        return {
            'id': item.id, 'title': item.title,
            'original_content': item.original_content,
            'canonical_url': item.canonical_url,
            'source': {'name': item.source.name, 'type': item.source.source_type,
                       'connector': item.source.connector.name},
            'published_at': item.published_at.isoformat() if item.published_at else None,
            'collected_at': item.collected_at.isoformat(),
            'categories': [c.name for c in item.categories.all()],
            'tags': [t.name for t in item.tags.all()],
            'ai_summary': {
                'short': analysis.short_summary if analysis else '',
                'relevance_score': analysis.relevance_score if analysis else 50,
            } if analysis else {},
        }

    @classmethod
    def dispatch_webhook(cls, webhook, event_type: str, payload: Dict[str, Any]) -> bool:
        import hmac as hmac_mod, hashlib as hl
        body_bytes = json.dumps(payload, default=str).encode('utf-8')
        signature = webhook.generate_signature(body_bytes)
        headers = {'Content-Type': 'application/json', 'User-Agent': 'MarketIntel-Webhook/1.0',
                   'X-Event-Type': event_type}
        if signature:
            headers['X-Hub-Signature-256'] = f"sha256={signature}"
        try:
            resp = requests.post(webhook.target_url, data=body_bytes, headers=headers, timeout=8)
            ok = 200 <= resp.status_code < 300
            WebhookDelivery.objects.create(webhook=webhook, event_type=event_type, payload=payload,
                                           response_status=resp.status_code, response_body=resp.text[:500],
                                           is_success=ok, attempt_count=1)
            return ok
        except Exception as e:
            logger.error(f"Webhook delivery failed to {webhook.target_url}: {e}")
            WebhookDelivery.objects.create(webhook=webhook, event_type=event_type, payload=payload,
                                           response_status=0, response_body=str(e)[:500],
                                           is_success=False, attempt_count=1)
            return False

    @classmethod
    def dispatch_active_webhooks(cls, item: CollectedItem):
        payload = cls.format_item_payload(item)
        webhooks = list(Webhook.objects.filter(is_active=True))
        if not webhooks:
            return

        def _fire(wh) -> bool:
            db.close_old_connections()
            return cls.dispatch_webhook(wh, 'item.published', payload)

        if len(webhooks) == 1:
            _fire(webhooks[0])
            return

        max_workers = min(len(webhooks), 4)  # cPanel-safe: 4 webhooks max parallel
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_fire, wh): wh for wh in webhooks}
            for future in as_completed(futures):
                wh = futures[future]
                try:
                    future.result()
                except Exception as exc:
                    logger.error(f"Webhook '{wh.target_url}' dispatch raised: {exc}")

    # Backward-compat shim for old views / tests that call publish_item
    @classmethod
    def publish_item(cls, item: CollectedItem, channel: str = 'webhook',
                     dispatch_social: bool = False) -> 'Publication':
        payload = cls.format_item_payload(item)
        pub = Publication.objects.create(item=item, channel=channel,
                                         status='published', formatted_payload=payload)
        item.status = 'published'
        item.save(update_fields=['status'])
        cls.dispatch_active_webhooks(item)
        if dispatch_social:
            cls.publish_to_all_active(item, force=True)
        return pub

    # Backward-compat shims for old .env-based publishers
    @classmethod
    def publish_to_facebook(cls, item: CollectedItem) -> bool:
        from django.conf import settings
        token   = getattr(settings, 'FACEBOOK_PAGE_ACCESS_TOKEN', '')
        page_id = getattr(settings, 'FACEBOOK_PAGE_ID', '')
        if not token or not page_id:
            return False
        ch = PublishChannel(name='legacy-env-facebook', channel_type='facebook')
        ch._credentials = {'page_access_token': token, 'page_id': page_id}
        return FacebookDispatcher.send(item, ch)

    @classmethod
    def publish_to_linkedin(cls, item: CollectedItem) -> bool:
        from django.conf import settings
        token   = getattr(settings, 'LINKEDIN_ACCESS_TOKEN', '')
        org_urn = getattr(settings, 'LINKEDIN_ORG_URN', '')
        if not token or not org_urn:
            return False
        ch = PublishChannel(name='legacy-env-linkedin', channel_type='linkedin')
        ch._credentials = {'access_token': token, 'org_urn': org_urn}
        return LinkedInDispatcher.send(item, ch)
