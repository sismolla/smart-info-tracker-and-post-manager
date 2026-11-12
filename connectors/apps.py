from django.apps import AppConfig

class ConnectorsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'connectors'
    verbose_name = 'Universal Connectors'

    def ready(self):
        # Register default connectors into registry
        try:
            from .base import registry
            from .telegram import TelegramConnector
            from .facebook import FacebookConnector
            from .linkedin import LinkedInConnector
            from .web import UniversalWebConnector

            registry.register('telegram', TelegramConnector)
            registry.register('facebook', FacebookConnector)
            registry.register('linkedin', LinkedInConnector)
            registry.register('web', UniversalWebConnector)
            registry.register('rss', UniversalWebConnector)
        except Exception:
            pass
