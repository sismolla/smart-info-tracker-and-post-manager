from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('', views.overview_view, name='dashboard_overview'),
    path('sources/', views.sources_view, name='dashboard_sources'),
    path('items/', views.items_view, name='dashboard_items'),
    path('items/<int:item_id>/', views.item_detail_view, name='dashboard_item_detail'),
    path('ai-settings/', views.ai_settings_view, name='dashboard_ai_settings'),
    path('publishing/', views.publishing_view, name='dashboard_publishing'),
    path('health-status/', views.health_view, name='dashboard_health'),
]
