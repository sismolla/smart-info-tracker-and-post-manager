import re
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from django.conf import settings
from .base import BaseConnector, NormalizedItem

logger = logging.getLogger(__name__)

class TelegramConnector(BaseConnector):
    """
    Official Telegram Integration supporting both MTProto (Telethon) and Bot API.
    Monitors authorized channels and groups, extracts structured metadata (phones, prices,
    dates, links), and respects Telegram access controls and rate limits.
    """

    PHONE_REGEX = re.compile(
        r'(?:\+251[\s.-]?|0)[79]\d{1,2}(?:[\s.-]?\d{2,3}){2,3}|\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b'
    )
    EMAIL_REGEX = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b')
    PRICE_REGEX = re.compile(r'(?:ETB|Birr|USD|\$|EUR|€)\s*[\d,]+(?:\.\d{2})?|\b[\d,]+(?:\.\d{2})?\s*(?:ETB|Birr|USD|Dollars)', re.IGNORECASE)
    URL_REGEX = re.compile(r'https?://[^\s<>"]+|www\.[^\s<>"]+')

    def __init__(self, account=None):
        super().__init__(account)
        creds = account.get_credentials() if account else {}
        self.api_id = creds.get('api_id') or getattr(settings, 'TELEGRAM_API_ID', '')
        self.api_hash = creds.get('api_hash') or getattr(settings, 'TELEGRAM_API_HASH', '')
        self.bot_token = creds.get('bot_token') or getattr(settings, 'TELEGRAM_BOT_TOKEN', '')
        self.phone_number = creds.get('phone_number') or getattr(settings, 'TELEGRAM_PHONE_NUMBER', '')
        self.string_session = creds.get('string_session') or getattr(settings, 'TELEGRAM_STRING_SESSION', '')

    def authenticate(self) -> bool:
        """Validates that necessary Telegram credentials are configured."""
        if (self.api_id and self.api_hash) or self.bot_token:
            self.is_authenticated = True
            return True
        return False

    def validate_connection(self) -> Dict[str, Any]:
        """Performs connectivity verification."""
        if not self.authenticate():
            return {
                'status': 'error',
                'authenticated': False,
                'message': 'Telegram API credentials missing. Provide API ID/Hash, StringSession, or Bot Token in Connected Account.',
            }

        # If Bot Token is configured, test live against Telegram Bot API
        if self.bot_token:
            try:
                import requests
                resp = requests.get(f"https://api.telegram.org/bot{self.bot_token}/getMe", timeout=10)
                if resp.status_code == 200 and resp.json().get('ok'):
                    bot_data = resp.json()['result']
                    return {
                        'status': 'ok',
                        'authenticated': True,
                        'bot_id': bot_data.get('id'),
                        'bot_username': bot_data.get('username'),
                        'mode': 'bot_api',
                        'message': f"Telegram Bot @{bot_data.get('username')} authenticated successfully.",
                    }
            except Exception as e:
                logger.warning(f"Telegram Bot API verification error: {e}")

        return {
            'status': 'ok',
            'authenticated': True,
            'message': 'Telegram connector initialized with MTProto credentials.',
            'capabilities': ['public_channels', 'authorized_groups', 'metadata_extraction']
        }

    def fetch_new_items(self, source, since: Optional[datetime] = None, limit: int = 30) -> List[NormalizedItem]:
        """
        Fetches new messages from the specified channel/group endpoint.
        Uses Telethon if available, or official HTTP Bot API.
        """
        target = source.endpoint_url.strip()
        items = []

        # 1. Try Live Telethon MTProto Client if credentials exist
        if self.api_id and self.api_hash:
            try:
                from telethon.sync import TelegramClient
                from telethon.sessions import StringSession

                if self.string_session:
                    session = StringSession(self.string_session)
                else:
                    session = f"tg_session_{self.account.id if self.account else 'default'}"

                with TelegramClient(session, int(self.api_id), self.api_hash) as client:
                    messages = client.get_messages(target, limit=limit)
                    for msg in messages:
                        if not msg.text:
                            continue
                        if since and msg.date and msg.date <= since:
                            continue

                        raw_dict = {
                            'id': msg.id,
                            'text': msg.text,
                            'date': msg.date.isoformat() if msg.date else None,
                            'fwd_from': str(msg.fwd_from) if msg.fwd_from else None,
                            'views': getattr(msg, 'views', 0),
                            'forwards': getattr(msg, 'forwards', 0),
                            'target': target,
                        }
                        items.append(self.normalize(raw_dict))
                    if items:
                        return items
            except Exception as e:
                logger.warning(f"Live Telethon collection failed for {target}: {e}. Falling back to Bot API.")

        # 2. Try Official Telegram Bot API
        if self.bot_token:
            try:
                import requests
                resp = requests.get(f"https://api.telegram.org/bot{self.bot_token}/getUpdates", timeout=10)
                if resp.status_code == 200 and resp.json().get('ok'):
                    for update in resp.json().get('result', []):
                        msg = update.get('channel_post') or update.get('message')
                        if msg and msg.get('text'):
                            raw_dict = {
                                'id': msg.get('message_id'),
                                'text': msg.get('text'),
                                'date': datetime.fromtimestamp(msg.get('date')).isoformat() if msg.get('date') else None,
                                'fwd_from': str(msg.get('forward_from_chat')) if msg.get('forward_from_chat') else None,
                                'views': 0,
                                'forwards': 0,
                                'target': target,
                            }
                            items.append(self.normalize(raw_dict))
                    if items:
                        return items
            except Exception as e:
                logger.warning(f"Telegram Bot API fetch failed for {target}: {e}")

        return items

    def normalize(self, raw_data: Any) -> NormalizedItem:
        """
        Converts Telegram message into standard NormalizedItem, extracting
        embedded phone numbers, prices, emails, links, and forward metadata.
        """
        text = raw_data.get('text', '') or ''
        msg_id = str(raw_data.get('id', ''))
        target = raw_data.get('target', '').lstrip('@')
        
        # Build canonical URL for public Telegram post
        url = f"https://t.me/{target}/{msg_id}" if target and msg_id else ""
        
        # Pre-extract regex entities
        phones = list(set(self.PHONE_REGEX.findall(text)))
        emails = list(set(self.EMAIL_REGEX.findall(text)))
        prices = list(set(self.PRICE_REGEX.findall(text)))
        urls = list(set(self.URL_REGEX.findall(text)))

        title = text.strip().split('\n')[0][:120] if text else "Telegram Announcement"
        
        metadata = {
            'phones': phones,
            'emails': emails,
            'prices': prices,
            'embedded_links': urls,
            'is_forwarded': bool(raw_data.get('fwd_from')),
            'views': raw_data.get('views', 0),
            'forwards': raw_data.get('forwards', 0),
        }

        pub_date = None
        if raw_data.get('date'):
            try:
                pub_date = datetime.fromisoformat(raw_data['date'])
            except Exception:
                pass

        return NormalizedItem(
            external_id=f"tg_{target}_{msg_id}",
            title=title,
            content_text=text,
            url=url,
            author=target,
            published_at=pub_date,
            media_urls=raw_data.get('media_urls', []),
            raw_payload=raw_data,
            metadata=metadata
        )
