"""
Core framework for the Phoenix AI Companion Toy.

This package provides the fundamental components of the Phoenix architecture:
- Event system with typed event definitions
- Service registry and lifecycle management
- Configuration management
- Observability and tracing
"""

from .events import EventType, BaseEvent
from .registry import EventRegistry, ServiceRegistry
from .bus import EventBus
from .tracing import EventTracer
from .service import BaseService
from .config import get_config, ApplicationConfig

__all__ = [
    'EventType',
    'BaseEvent',
    'EventRegistry',
    'ServiceRegistry',
    'EventBus',
    'EventTracer',
    'BaseService',
    'get_config',
    'ApplicationConfig'
] 