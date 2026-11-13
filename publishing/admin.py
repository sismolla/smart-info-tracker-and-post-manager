from django.contrib import admin
from .models import Webhook, WebhookDelivery, Publication

@admin.register(Webhook)
class WebhookAdmin(admin.ModelAdmin):
    list_display = ('name', 'target_url', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('name', 'target_url')

@admin.register(WebhookDelivery)
class WebhookDeliveryAdmin(admin.ModelAdmin):
    list_display = ('webhook', 'event_type', 'response_status', 'is_success', 'created_at')
    list_filter = ('is_success', 'event_type')
    search_fields = ('webhook__name', 'event_type')

@admin.register(Publication)
class PublicationAdmin(admin.ModelAdmin):
    list_display = ('item', 'channel', 'destination', 'status', 'published_at')
    list_filter = ('channel', 'status')
    search_fields = ('item__title', 'destination')
