"""FastAPI adapter for Flutter and other local Host clients."""

from .business_plan_extension import install_business_plan_extensions

install_business_plan_extensions()

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
