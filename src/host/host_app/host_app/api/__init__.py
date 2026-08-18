"""FastAPI adapter for Flutter and other local Host clients."""

from .app import API_PREFIX, create_app
from .events import EventHub
from .service import HostApiService, ResourceNotFoundError

__all__ = [
    "API_PREFIX",
    "EventHub",
    "HostApiService",
    "ResourceNotFoundError",
    "create_app",
]
