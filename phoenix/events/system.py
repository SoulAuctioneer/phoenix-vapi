"""
System events for the Phoenix AI Companion Toy.

This module defines events related to application lifecycle, service state,
and system-level operations.
"""

from typing import Dict, Any, Optional, Literal
from phoenix.core.events import BaseEvent, EventType

class ApplicationStartupCompletedEvent(BaseEvent):
    """
    Event published when application startup has completed.
    
    This event signals that all core services have been initialized
    and the application is ready to begin normal operation.
    """
    type: Literal[EventType.APPLICATION_STARTUP_COMPLETED] = EventType.APPLICATION_STARTUP_COMPLETED

class ServiceStateChangedEvent(BaseEvent):
    """
    Event published when a service changes state.
    
    This event is used to communicate service lifecycle changes
    (starting, running, stopping, stopped, etc.).
    """
    type: Literal[EventType.SERVICE_STATE_CHANGED] = EventType.SERVICE_STATE_CHANGED
    service_name: str
    state: str  # 'registered', 'starting', 'running', 'stopping', 'stopped', 'error'
    error: Optional[str] = None  # Present only if state is 'error'

class ServiceErrorEvent(BaseEvent):
    """
    Event published when a service encounters an error.
    
    This event provides details about the error condition to allow
    other services to potentially recover or adapt.
    """
    type: Literal[EventType.SERVICE_ERROR] = EventType.SERVICE_ERROR
    service_name: str
    error_type: str
    error_message: str
    details: Optional[Dict[str, Any]] = None

class HardwareErrorEvent(BaseEvent):
    """
    Event published when hardware encounters an error.
    
    This event provides details about hardware issues that may require
    manual intervention or degraded operation modes.
    """
    type: Literal[EventType.HARDWARE_ERROR] = EventType.HARDWARE_ERROR
    component: str  # 'audio', 'led', 'sensor', etc.
    error_type: str
    error_message: str
    details: Optional[Dict[str, Any]] = None 