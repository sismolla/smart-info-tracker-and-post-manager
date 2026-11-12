import os
import sys
import shutil
from django.http import JsonResponse
from django.db import connection
from django.conf import settings
from django.utils import timezone
from .models import DatabaseLock, SystemSetting

def health_check_view(request):
    """
    Comprehensive system diagnostic view suitable for cPanel uptime monitors,
    deployment validation, and container health probes.
    """
    health = {
        'status': 'ok',
        'timestamp': timezone.now().isoformat(),
        'platform': {
            'python_version': sys.version.split(' ')[0],
            'os': os.name,
            'execution_mode': getattr(settings, 'EXECUTION_MODE', 'cpanel_cron'),
            'debug': settings.DEBUG,
        },
        'services': {},
        'locks': {},
        'storage': {},
    }

    # 1. Database Check
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        health['services']['database'] = {
            'status': 'healthy',
            'engine': settings.DATABASES['default']['ENGINE'].split('.')[-1],
        }
    except Exception as e:
        health['status'] = 'degraded'
        health['services']['database'] = {
            'status': 'unhealthy',
            'error': str(e),
        }

    # 2. Database Lock Status
    try:
        active_locks = list(DatabaseLock.objects.filter(expires_at__gt=timezone.now()).values('lock_key', 'acquired_at', 'expires_at', 'holder_pid'))
        health['locks'] = {
            'active_locks_count': len(active_locks),
            'locks': active_locks,
        }
    except Exception as e:
        health['locks'] = {'error': str(e)}

    # 3. Storage & Media Check
    try:
        media_writable = os.access(settings.MEDIA_ROOT, os.W_OK) if os.path.exists(settings.MEDIA_ROOT) else False
        total, used, free = shutil.disk_usage(settings.BASE_DIR)
        health['storage'] = {
            'media_root_writable': media_writable,
            'free_disk_mb': round(free / (1024 * 1024), 2),
            'total_disk_mb': round(total / (1024 * 1024), 2),
        }
    except Exception as e:
        health['storage'] = {'error': str(e)}

    # 4. AI Readiness Check
    has_gemini_key = bool(getattr(settings, 'GEMINI_API_KEY', ''))
    health['services']['ai_engine'] = {
        'provider': 'Google Gemini',
        'model': getattr(settings, 'GEMINI_MODEL', 'gemini-1.5-flash'),
        'api_key_configured': has_gemini_key,
        'fallback_mode_available': True,
    }

    status_code = 200 if health['status'] == 'ok' else 503
    return JsonResponse(health, status=status_code)
