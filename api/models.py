import secrets
from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()

class APIClient(models.Model):
    """
    Authorized consumer application or partner granted API access.
    """
    name = models.CharField(max_length=150)
    api_key = models.CharField(max_length=64, unique=True, db_index=True)
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    is_active = models.BooleanField(default=True)
    rate_limit_per_minute = models.PositiveIntegerField(default=120)
    allowed_ips = models.CharField(max_length=255, blank=True, help_text="Comma-separated IP addresses or leave blank for any")
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.name} ({self.api_key[:8]}...)"

    @classmethod
    def generate_key(cls) -> str:
        return f"mkt_{secrets.token_urlsafe(32)}"

    def save(self, *args, **kwargs):
        if not self.api_key:
            self.api_key = self.generate_key()
        super().save(*args, **kwargs)
