import logging
import requests
from django.conf import settings
from intelligence.models import CollectedItem

logger = logging.getLogger(__name__)

TELEGRAM_MAX_CAPTION = 1024   # Telegram caption limit for sendPhoto
TELEGRAM_MAX_TEXT    = 4096   # Telegram message limit for sendMessage


class TelegramAlertDispatcher:
    """
    Dispatches posts to a Telegram channel in clean news-broadcast style.

    Format philosophy (like Tikvah Ethiopia):
      - If editorial_notes is set, it appears first as a lead-in line.
      - Then the full article body text (original_content).
      - Source attribution line at the bottom.
      - If media images are attached, the first image is sent as a photo
        with the text as caption (≤1024 chars). Additional images are sent
        as a follow-up media group. If no image, plain sendMessage is used.
      - No relevance scores, no budget fields, no structured metadata.
    """

    # ------------------------------------------------------------------ #
    #  Public entry-point                                                  #
    # ------------------------------------------------------------------ #

    @classmethod
    def send_alert(cls, item: CollectedItem, force: bool = False) -> bool:
        bot_token = getattr(settings, 'TELEGRAM_BOT_TOKEN', '')
        chat_id   = getattr(settings, 'TELEGRAM_ALERT_CHAT_ID', '')
        min_score = getattr(settings, 'TELEGRAM_ALERT_MIN_SCORE', 75)

        if not bot_token or not chat_id:
            logger.debug("Telegram post skipped: bot_token or chat_id not configured.")
            return False

        # Relevance gate (bypass with force=True, e.g. from Editorial Studio)
        score = item.ai_analysis.relevance_score if hasattr(item, 'ai_analysis') and item.ai_analysis else 50
        if not force and score < min_score:
            logger.debug(f"Item #{item.id} score {score} below threshold {min_score} — skipped.")
            return False

        # Build the clean broadcast text
        body_text = cls._build_body(item)

        # Collect valid http image URLs
        images = [
            u for u in (item.media_urls or [])
            if u and isinstance(u, str) and u.startswith('http')
        ]

        if images:
            return cls._send_with_media(item, bot_token, chat_id, body_text, images)
        else:
            return cls._send_text(bot_token, chat_id, body_text, item)

    # ------------------------------------------------------------------ #
    #  Message construction                                                #
    # ------------------------------------------------------------------ #

    @classmethod
    def _build_body(cls, item: CollectedItem) -> str:
        """
        Constructs the final broadcast text:
          [editorial note if present]
          [article body text]
          [source attribution]
        """
        parts = []

        # Optional editorial lead-in (admin's custom note)
        if item.editorial_notes and item.editorial_notes.strip():
            parts.append(item.editorial_notes.strip())
            parts.append("")   # blank line separator

        # Article body — the full original_content the admin edited
        article = (item.original_content or item.title or "").strip()
        if article:
            parts.append(article)

        # Source attribution line
        source_name = item.source.name if item.source else ""
        if source_name:
            parts.append("")
            parts.append(f"{source_name}")

        return "\n".join(parts)

    # ------------------------------------------------------------------ #
    #  Delivery helpers                                                    #
    # ------------------------------------------------------------------ #

    @classmethod
    def _send_text(cls, bot_token: str, chat_id: str, text: str, item: CollectedItem) -> bool:
        """Plain text message, split if needed."""
        endpoint = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        # Telegram hard-limit is 4096 chars per message
        for chunk in cls._split(text, TELEGRAM_MAX_TEXT):
            try:
                resp = requests.post(endpoint, json={
                    'chat_id':                  chat_id,
                    'text':                     chunk,
                    'parse_mode':               'HTML',
                    'disable_web_page_preview': False,
                }, timeout=10)
                if not (resp.status_code == 200 and resp.json().get('ok')):
                    # Retry without parse_mode in case of HTML entity issues
                    resp = requests.post(endpoint, json={
                        'chat_id': chat_id,
                        'text':    chunk,
                        'disable_web_page_preview': False,
                    }, timeout=10)
                ok = resp.status_code == 200 and resp.json().get('ok')
                if not ok:
                    logger.warning(f"Telegram sendMessage failed for Item #{item.id}: {resp.text[:200]}")
                    return False
            except Exception as e:
                logger.error(f"Telegram sendMessage exception for Item #{item.id}: {e}")
                return False
        logger.info(f"Telegram text post sent for Item #{item.id} to {chat_id}")
        return True

    @classmethod
    def _send_with_media(cls, item: CollectedItem, bot_token: str, chat_id: str,
                         text: str, images: list) -> bool:
        """
        Send up to 10 images as a media group.
        The article text goes as the caption of the first photo.
        If only one image: use sendPhoto for simpler delivery.
        Falls back to plain sendMessage if photo delivery fails.
        """
        # Caption is limited to 1024 chars for sendPhoto / media group
        caption = text[:TELEGRAM_MAX_CAPTION]

        # --- Single image: sendPhoto ---
        if len(images) == 1:
            ok = cls._send_photo(bot_token, chat_id, images[0], caption, item)
            if ok:
                return True
            # Fall back to text-only
            logger.warning(f"Item #{item.id}: sendPhoto failed, falling back to sendMessage.")
            return cls._send_text(bot_token, chat_id, text, item)

        # --- Multiple images: sendMediaGroup (up to 10) ---
        media_group = []
        for idx, url in enumerate(images[:10]):
            entry = {
                'type':       'photo',
                'media':      url,
            }
            if idx == 0:
                entry['caption']    = caption
                entry['parse_mode'] = 'HTML'
            media_group.append(entry)

        endpoint = f"https://api.telegram.org/bot{bot_token}/sendMediaGroup"
        try:
            resp = requests.post(endpoint, json={
                'chat_id': chat_id,
                'media':   media_group,
            }, timeout=15)
            if resp.status_code == 200 and resp.json().get('ok'):
                logger.info(f"Telegram media group ({len(media_group)} photos) sent for Item #{item.id}")
                return True
            else:
                logger.warning(f"sendMediaGroup failed for Item #{item.id}: {resp.text[:200]}")
        except Exception as e:
            logger.warning(f"sendMediaGroup exception for Item #{item.id}: {e}")

        # Fallback: send first image as plain sendPhoto
        ok = cls._send_photo(bot_token, chat_id, images[0], caption, item)
        if ok:
            return True
        # Final fallback: plain text
        return cls._send_text(bot_token, chat_id, text, item)

    @classmethod
    def _send_photo(cls, bot_token: str, chat_id: str, photo_url: str,
                    caption: str, item: CollectedItem) -> bool:
        endpoint = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
        try:
            resp = requests.post(endpoint, json={
                'chat_id':    chat_id,
                'photo':      photo_url,
                'caption':    caption[:TELEGRAM_MAX_CAPTION],
                'parse_mode': 'HTML',
            }, timeout=12)
            if resp.status_code == 200 and resp.json().get('ok'):
                logger.info(f"Telegram photo sent for Item #{item.id}")
                return True
            # Retry without parse_mode (handles Amharic / special chars)
            resp = requests.post(endpoint, json={
                'chat_id': chat_id,
                'photo':   photo_url,
                'caption': caption[:TELEGRAM_MAX_CAPTION],
            }, timeout=12)
            ok = resp.status_code == 200 and resp.json().get('ok')
            if not ok:
                logger.warning(f"sendPhoto failed for Item #{item.id}: {resp.text[:200]}")
            return ok
        except Exception as e:
            logger.warning(f"sendPhoto exception for Item #{item.id}: {e}")
            return False

    # ------------------------------------------------------------------ #
    #  Utility                                                             #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _split(text: str, limit: int) -> list:
        """Split text into chunks of at most `limit` characters at a paragraph boundary."""
        if len(text) <= limit:
            return [text]
        chunks = []
        while text:
            if len(text) <= limit:
                chunks.append(text)
                break
            # Try to split at the last double-newline within limit
            cut = text.rfind('\n\n', 0, limit)
            if cut == -1:
                cut = text.rfind('\n', 0, limit)
            if cut == -1:
                cut = limit
            chunks.append(text[:cut].rstrip())
            text = text[cut:].lstrip()
        return [c for c in chunks if c]
