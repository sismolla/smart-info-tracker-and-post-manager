from rest_framework import authentication, exceptions
from django.utils import timezone
from .models import APIClient

class APIKeyAuthentication(authentication.BaseAuthentication):
    """
    Authenticates external clients using X-API-KEY header or 'Api-Key <token>' Authorization header.
    """
    def authenticate(self, request):
        api_key = request.META.get('HTTP_X_API_KEY')
        if not api_key:
            auth_header = request.META.get('HTTP_AUTHORIZATION', '')
            if auth_header.startswith('Api-Key '):
                api_key = auth_header.split(' ')[1].strip()

        if not api_key:
            return None # Fallback to session authentication

        try:
            client = APIClient.objects.get(api_key=api_key, is_active=True)
            client.last_used_at = timezone.now()
            client.save(update_fields=['last_used_at'])
            
            user = client.user
            if not user:
                from django.contrib.auth import get_user_model
                User = get_user_model()
                user, _ = User.objects.get_or_create(
                    username='api_service_account',
                    defaults={'is_active': True, 'first_name': 'API Service Account'}
                )

            return (user, client)
        except APIClient.DoesNotExist:
            raise exceptions.AuthenticationFailed('Invalid or inactive API Key.')
