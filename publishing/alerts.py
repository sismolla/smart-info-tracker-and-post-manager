"""
Backward-compatibility shim for TelegramAlertDispatcher.
New code should call publishing.publishers.TelegramDispatcher directly
with a PublishChannel object.

This module preserves the legacy send_alert(item, force) API so existing
views and tests continue to work. It automatically picks the first active
Telegram PublishChannel, or falls back to .env credentials if none are
configured yet.
"""
import logging
import requests
from django.conf import settings
from intelligence.models import CollectedItem

logger = logging.getLogger(__name__)


class TelegramAlertDispatcher:

    @classmethod
    def send_alert(cls, item: CollectedItem, force: bool = False) -> bool:
        from publishing.models import PublishChannel
        from publishing.publishers import TelegramDispatcher

        # Prefer DB-managed channels (both channels and groups)
        tg_channels = list(PublishChannel.objects.filter(
            channel_type__in=[PublishChannel.TYPE_TELEGRAM, PublishChannel.TYPE_TELEGRAM_GROUP],
            is_active=True
        ).order_by('id'))

        if tg_channels:
            # Dispatch to all active Telegram channels
            any_ok = False
            for ch in tg_channels:
                ok = TelegramDispatcher.send(item, ch, force=force)
                any_ok = any_ok or ok
            return any_ok

        # Legacy .env fallback
        bot_token = getattr(settings, 'TELEGRAM_BOT_TOKEN', '')
        chat_id   = getattr(settings, 'TELEGRAM_ALERT_CHAT_ID', '')
        min_score = getattr(settings, 'TELEGRAM_ALERT_MIN_SCORE', 75)

        if not bot_token or not chat_id:
            logger.debug("Telegram alert skipped: no DB channels and no .env credentials configured.")
            return False

        # Build a transient channel object from .env
        ch = PublishChannel(name='env-fallback', channel_type=PublishChannel.TYPE_TELEGRAM)
        ch._credentials = {'bot_token': bot_token, 'chat_id': chat_id, 'min_score': str(min_score)}
        return TelegramDispatcher.send(item, ch, force=force)
