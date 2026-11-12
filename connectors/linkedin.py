import logging
import requests
from datetime import datetime
from typing import List, Dict, Any, Optional
from django.conf import settings
from .base import BaseConnector, NormalizedItem

logger = logging.getLogger(__name__)

class LinkedInConnector(BaseConnector):
    """
    Official LinkedIn REST API v2 Connector.
    Focused on authorized organization pages, company updates, and hiring/recruitment intelligence.
    Enforces compliance with LinkedIn API policies (no personal profile scraping).
    """

    API_BASE = "https://api.linkedin.com/v2"

    def __init__(self, account=None):
        super().__init__(account)
        creds = account.get_credentials() if account else {}
        self.access_token = creds.get('access_token') or getattr(settings, 'LINKEDIN_ACCESS_TOKEN', '')
        self.client_id = creds.get('client_id') or getattr(settings, 'LINKEDIN_CLIENT_ID', '')
        self.client_secret = creds.get('client_secret') or getattr(settings, 'LINKEDIN_CLIENT_SECRET', '')

    def authenticate(self) -> bool:
        if self.access_token:
            self.is_authenticated = True
            return True
        return False

    def validate_connection(self) -> Dict[str, Any]:
        """Tests OAuth2 token against LinkedIn /userinfo or /me endpoint."""
        if not self.authenticate():
            return {
                'status': 'error',
                'authenticated': False,
                'message': 'LinkedIn OAuth2 Access Token missing in Connected Account or settings.',
                'documentation': 'Requires OAuth 2.0 with r_organization_social or r_liteprofile scopes.'
            }

        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'X-Restli-Protocol-Version': '2.0.0',
        }
        try:
            resp = requests.get(f"{self.API_BASE}/me", headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                return {
                    'status': 'ok',
                    'authenticated': True,
                    'account_id': data.get('id'),
                    'first_name': data.get('localizedFirstName'),
                    'last_name': data.get('localizedLastName'),
                }
            else:
                return {
                    'status': 'error',
                    'authenticated': False,
                    'message': f"LinkedIn API returned {resp.status_code}: {resp.text}"
                }
        except Exception as e:
            return {'status': 'error', 'authenticated': False, 'message': str(e)}

    def fetch_new_items(self, source, since: Optional[datetime] = None, limit: int = 25) -> List[NormalizedItem]:
        """
        Fetches organization posts and hiring announcements via LinkedIn REST API.
        Target endpoint can be organization URN (e.g. 'urn:li:organization:1234567').
        """
        org_urn = source.endpoint_url.strip()
        if not org_urn.startswith('urn:li:organization:'):
            org_urn = f"urn:li:organization:{org_urn}"

        if not self.authenticate():
            logger.warning(f"LinkedIn connector not authenticated for {org_urn}")
            return []

        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'X-Restli-Protocol-Version': '2.0.0',
            'LinkedIn-Version': '202401',
        }
        url = f"{self.API_BASE}/ugcPosts"
        params = {
            'q': 'authors',
            'authors': f"List({org_urn})",
            'count': min(limit, 50),
        }

        items = []
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                elements = data.get('elements', [])
                for el in elements:
                    items.append(self.normalize(el))
            else:
                logger.error(f"LinkedIn UGC post fetch failed: {resp.status_code} - {resp.text}")
                source.health_status = 'rate_limited' if resp.status_code == 429 else 'failing'
                source.error_message = resp.text[:200]
                source.save(update_fields=['health_status', 'error_message'])
        except Exception as e:
            logger.error(f"Error connecting to LinkedIn API: {e}")
            source.health_status = 'failing'
            source.error_message = str(e)[:200]
            source.save(update_fields=['health_status', 'error_message'])

        return items

    def normalize(self, raw_data: Any) -> NormalizedItem:
        """Transforms LinkedIn UGC post into NormalizedItem."""
        post_urn = raw_data.get('id', '')
        author_urn = raw_data.get('author', '')
        
        specific_content = raw_data.get('specificContent', {}).get('com.linkedin.ugc.ShareContent', {})
        text = specific_content.get('shareCommentary', {}).get('text', '') or ''
        title = text.strip().split('\n')[0][:120] if text else "LinkedIn Business Update"
        
        media_urls = []
        for media_item in specific_content.get('media', []):
            if media_item.get('originalUrl'):
                media_urls.append(media_item['originalUrl'])

        created_ts = raw_data.get('created', {}).get('time')
        pub_date = datetime.fromtimestamp(created_ts / 1000) if created_ts else None

        permalink = f"https://www.linkedin.com/feed/update/{post_urn}"

        return NormalizedItem(
            external_id=f"li_{post_urn.replace(':', '_')}",
            title=title,
            content_text=text,
            url=permalink,
            author=author_urn,
            published_at=pub_date,
            media_urls=media_urls,
            raw_payload=raw_data,
            metadata={'platform': 'linkedin', 'author_urn': author_urn}
        )
