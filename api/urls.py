from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    CollectedItemViewSet, InformationSourceViewSet,
    WebhookViewSet, IntelligenceSummaryView
)

router = DefaultRouter()
router.register(r'items', CollectedItemViewSet, basename='items')
router.register(r'sources', InformationSourceViewSet, basename='sources')
router.register(r'webhooks', WebhookViewSet, basename='webhooks')

urlpatterns = [
    path('v1/', include(router.urls)),
    path('v1/summary/', IntelligenceSummaryView.as_view(), name='api_summary'),
]
