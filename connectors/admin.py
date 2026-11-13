from django.contrib import admin
from .models import Connector, ConnectedAccount, InformationSource, CollectionRun

@admin.register(Connector)
class ConnectorAdmin(admin.ModelAdmin):
    list_display = ('name', 'connector_type', 'is_active', 'created_at')
    list_filter = ('connector_type', 'is_active')
    search_fields = ('name', 'slug')

@admin.register(ConnectedAccount)
class ConnectedAccountAdmin(admin.ModelAdmin):
    list_display = ('name', 'connector', 'account_identifier', 'is_active', 'updated_at')
    list_filter = ('connector', 'is_active')
    search_fields = ('name', 'account_identifier')

@admin.register(InformationSource)
class InformationSourceAdmin(admin.ModelAdmin):
    list_display = ('name', 'connector', 'source_type', 'endpoint_url', 'health_status', 'is_active', 'last_synced_at')
    list_filter = ('connector', 'source_type', 'health_status', 'is_active')
    search_fields = ('name', 'endpoint_url')

@admin.register(CollectionRun)
class CollectionRunAdmin(admin.ModelAdmin):
    list_display = ('source', 'status', 'items_discovered', 'items_saved', 'started_at', 'finished_at')
    list_filter = ('status',)
    search_fields = ('source__name',)
