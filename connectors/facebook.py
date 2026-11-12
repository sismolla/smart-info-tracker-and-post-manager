import logging
import requests
from datetime import datetime
from typing import List, Dict, Any, Optional
from django.conf import settings
from .base import BaseConnector, NormalizedItem

logger = logging.getLogger(__name__)

class FacebookConnector(BaseConnector):
    """
    Official Meta Facebook Graph API v19+ Connector.
    Supports authorized Pages and business accounts via approved Page Access Tokens.
    Does NOT use unauthorized personal account scraping or session cookie extraction.
    """

    GRAPH_API_BASE = "https://graph.facebook.com/v19.0"

    def __init__(self, account=None):
        super().__init__(account)
        creds = account.get_credentials() if account else {}
        self.access_token = creds.get('access_token') or getattr(settings, 'FACEBOOK_PAGE_ACCESS_TOKEN', '')
        self.app_id = creds.get('app_id') or getattr(settings, 'FACEBOOK_APP_ID', '')
        self.app_secret = creds.get('app_secret') or getattr(settings, 'FACEBOOK_APP_SECRET', '')

    def authenticate(self) -> bool:
        if self.access_token:
            self.is_authenticated = True
            return True
        return False

    def validate_connection(self) -> Dict[str, Any]:
        """Tests Page token validity against Meta Graph API /me endpoint."""
        if not self.authenticate():
            return {
                'status': 'error',
                'authenticated': False,
                'message': 'Facebook Page Access Token missing.',
                'documentation': 'Requires Page Access Token with pages_read_engagement permission.'
            }

        try:
            url = f"{self.GRAPH_API_BASE}/me"
            params = {'access_token': self.access_token, 'fields': 'id,name'}
            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                return {
                    'status': 'ok',
                    'authenticated': True,
                    'account_id': data.get('id'),
                    'account_name': data.get('name'),
                    'api_version': 'v19.0',
                    'rate_limit': resp.headers.get('x-app-usage', 'normal'),
                }
            else:
                return {
                    'status': 'error',
                    'authenticated': False,
                    'message': f"Meta API error: {resp.text}",
                }
        except Exception as e:
            return {'status': 'error', 'authenticated': False, 'message': str(e)}

    def fetch_new_items(self, source, since: Optional[datetime] = None, limit: int = 25) -> List[NormalizedItem]:
        """
        Fetches published posts from the authorized Page endpoint.
        """
        page_id = source.endpoint_url.strip()
        if not self.authenticate():
            logger.warning(f"Facebook connector not authenticated for {page_id}")
            return []

        url = f"{self.GRAPH_API_BASE}/{page_id}/feed"
        params = {
            'access_token': self.access_token,
            'fields': 'id,message,created_time,full_picture,permalink_url,shares',
            'limit': min(limit, 50),
        }
        if since:
            params['since'] = int(since.timestamp())

        items = []
        try:
            resp = requests.get(url, params=params, timeout=15)
            if resp.status_code == 200:
                payload = resp.json()
                posts = payload.get('data', [])
                for post in posts:
                    items.append(self.normalize(post))
            else:
                logger.error(f"Facebook API request failed: {resp.status_code} - {resp.text}")
                source.health_status = 'rate_limited' if resp.status_code == 429 else 'failing'
                source.error_message = resp.text[:200]
                if getattr(source, 'id', None):
                    source.save(update_fields=['health_status', 'error_message'])
        except Exception as e:
            logger.error(f"Error connecting to Facebook API: {e}")
            source.health_status = 'failing'
            source.error_message = str(e)[:200]
            if getattr(source, 'id', None):
                source.save(update_fields=['health_status', 'error_message'])

        return items

    def normalize(self, raw_data: Any) -> NormalizedItem:
        """
        Transforms Facebook Graph post payload into NormalizedItem.
        """
        message = raw_data.get('message', '') or ''
        title = message.strip().split('\n')[0][:120] if message else "Facebook Page Update"
        post_id = raw_data.get('id', '')
        permalink = raw_data.get('permalink_url', f"https://facebook.com/{post_id}")
        
        media_urls = []
        if raw_data.get('full_picture'):
            media_urls.append(raw_data['full_picture'])

        created_time = None
        if raw_data.get('created_time'):
            try:
                created_time = datetime.fromisoformat(raw_data['created_time'].replace('Z', '+00:00'))
            except Exception:
                pass

        shares = raw_data.get('shares', {}).get('count', 0) if isinstance(raw_data.get('shares'), dict) else 0

        return NormalizedItem(
            external_id=f"fb_{post_id}",
            title=title,
            content_text=message,
            url=permalink,
            author=post_id.split('_')[0] if '_' in post_id else 'Facebook Page',
            published_at=created_time,
            media_urls=media_urls,
            raw_payload=raw_data,
            metadata={'shares': shares, 'platform': 'facebook'}
        )
