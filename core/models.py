import os
import uuid
from django.db import models, transaction
from django.utils import timezone
from django.contrib.auth import get_user_model

User = get_user_model()

class DatabaseLock(models.Model):
    """
    Atomic distributed lock specifically designed for cPanel shared hosting.
    Prevents scheduled cron jobs from running concurrently when previous jobs are slow.
    """
    lock_key = models.CharField(max_length=120, unique=True, db_index=True)
    acquired_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(db_index=True)
    holder_pid = models.CharField(max_length=100, blank=True)

    class Meta:
        verbose_name = 'Database Lock'
        verbose_name_plural = 'Database Locks'

    def __str__(self):
        return f"Lock({self.lock_key}) expires at {self.expires_at}"

    @classmethod
    def acquire(cls, lock_key: str, timeout_seconds: int = 300) -> bool:
        """
        Attempts to acquire an atomic lock. Returns True if acquired, False otherwise.
        Automatically cleans up expired locks.
        """
        now = timezone.now()
        expires = now + timezone.timedelta(seconds=timeout_seconds)
        pid = f"pid-{os.getpid()}-{uuid.uuid4().hex[:6]}"

        try:
            with transaction.atomic():
                # Clean expired locks for this key if any
                cls.objects.filter(lock_key=lock_key, expires_at__lte=now).delete()
                
                # Try creating the lock
                obj, created = cls.objects.get_or_create(
                    lock_key=lock_key,
                    defaults={'expires_at': expires, 'holder_pid': pid}
                )
                if not created:
                    # Check if expired again
                    if obj.expires_at <= now:
                        obj.expires_at = expires
                        obj.holder_pid = pid
                        obj.save()
                        return True
                    return False
                return True
        except Exception:
            return False

    @classmethod
    def release(cls, lock_key: str) -> bool:
        """Releases the specified lock."""
        try:
            cls.objects.filter(lock_key=lock_key).delete()
            return True
        except Exception:
            return False


class SystemSetting(models.Model):
    """
    Global dynamic configuration options editable from Dashboard or APIs.
    """
    SETTING_TYPES = [
        ('string', 'String'),
        ('integer', 'Integer'),
        ('float', 'Float'),
        ('boolean', 'Boolean'),
        ('json', 'JSON'),
    ]

    key = models.CharField(max_length=100, unique=True, db_index=True)
    value = models.TextField()
    setting_type = models.CharField(max_length=20, choices=SETTING_TYPES, default='string')
    description = models.CharField(max_length=255, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'System Setting'
        verbose_name_plural = 'System Settings'

    def __str__(self):
        return f"{self.key} = {self.value}"

    @classmethod
    def get_value(cls, key: str, default=None):
        try:
            item = cls.objects.get(key=key)
            if item.setting_type == 'boolean':
                return item.value.lower() in ('true', '1', 'yes')
            elif item.setting_type == 'integer':
                return int(item.value)
            elif item.setting_type == 'float':
                return float(item.value)
            return item.value
        except cls.DoesNotExist:
            return default


class AuditLog(models.Model):
    """
    Immutable audit trail for system events, editorial actions, and errors.
    """
    LEVEL_CHOICES = [
        ('info', 'Info'),
        ('warning', 'Warning'),
        ('error', 'Error'),
        ('security', 'Security'),
    ]

    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    level = models.CharField(max_length=20, choices=LEVEL_CHOICES, default='info')
    action = models.CharField(max_length=100, db_index=True)
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    target_model = models.CharField(max_length=100, blank=True)
    target_id = models.CharField(max_length=100, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'Audit Log'
        verbose_name_plural = 'Audit Logs'

    def __str__(self):
        return f"[{self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}] {self.level.upper()}: {self.action}"
