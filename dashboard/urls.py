from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('', views.overview_view, name='dashboard_overview'),
    path('sources/', views.sources_view, name='dashboard_sources'),
    path('sources/preview/', views.source_preview_api, name='dashboard_source_preview'),
    path('items/', views.items_view, name='dashboard_items'),
    path('items/<int:item_id>/', views.item_detail_view, name='dashboard_item_detail'),
    path('ai-settings/', views.ai_settings_view, name='dashboard_ai_settings'),
    path('publishing/', views.publishing_view, name='dashboard_publishing'),
    path('channels/', views.channels_view, name='dashboard_channels'),
    path('health-status/', views.health_view, name='dashboard_health'),
    # PWA endpoints
    path('sw.js', views.service_worker_view, name='pwa_sw'),
    path('manifest.json', views.manifest_view, name='pwa_manifest'),
    path('offline/', views.offline_view, name='pwa_offline'),
]
