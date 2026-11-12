import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

@dataclass
class NormalizedItem:
    """
    Standardized data payload produced by all connectors before ingestion.
    Ensures complete decoupling between external platform formats and internal intelligence models.
    """
    external_id: str
    title: str
    content_text: str
    url: str
    author: str = ""
    published_at: Optional[datetime] = None
    media_urls: List[str] = field(default_factory=list)
    raw_payload: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    language_hint: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            'external_id': self.external_id,
            'title': self.title,
            'content_text': self.content_text,
            'url': self.url,
            'author': self.author,
            'published_at': self.published_at.isoformat() if self.published_at else None,
            'media_urls': self.media_urls,
            'raw_payload': self.raw_payload,
            'metadata': self.metadata,
            'language_hint': self.language_hint,
        }


class BaseConnector(ABC):
    """
    Universal connector interface required by all source integrations.
    """
    def __init__(self, account=None):
        self.account = account
        self.is_authenticated = False

    @abstractmethod
    def authenticate(self) -> bool:
        """Connects and validates credentials for this integration."""
        pass

    @abstractmethod
    def validate_connection(self) -> Dict[str, Any]:
        """Tests live connectivity and returns health/status metadata."""
        pass

    @abstractmethod
    def fetch_new_items(self, source, since: Optional[datetime] = None, limit: int = 30) -> List[NormalizedItem]:
        """Fetches newly published items since the given timestamp up to the limit."""
        pass

    @abstractmethod
    def normalize(self, raw_data: Any) -> NormalizedItem:
        """Transforms platform-specific payload into a normalized data structure."""
        pass

    def disconnect(self) -> bool:
        """Revokes access or closes active connections."""
        self.is_authenticated = False
        return True


class ConnectorRegistry:
    """
    Central registry for dynamic connector discovery and instantiation.
    """
    def __init__(self):
        self._registry: Dict[str, type] = {}

    def register(self, connector_type: str, connector_class: type):
        self._registry[connector_type.lower()] = connector_class
        logger.debug(f"Registered connector: {connector_type} -> {connector_class.__name__}")

    def get(self, connector_type: str) -> Optional[type]:
        return self._registry.get(connector_type.lower())

    def list_connectors(self) -> List[str]:
        return list(self._registry.keys())

    def create_instance(self, connector_type: str, account=None) -> Optional[BaseConnector]:
        cls = self.get(connector_type)
        if cls:
            return cls(account=account)
        return None

# Singleton registry
registry = ConnectorRegistry()
