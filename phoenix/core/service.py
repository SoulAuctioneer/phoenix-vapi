"""
Base service implementation for the Phoenix AI Companion Toy.

This module provides the BaseService class that all services should inherit from,
defining the core service lifecycle and event handling interfaces.
"""

import asyncio
import logging
import structlog
from abc import ABC, abstractmethod
from typing import Dict, Set, Any, Optional, ClassVar, Type, Mapping
from .events import EventType, BaseEvent
from .registry import EventRegistry, ServiceRegistry
from .bus import EventBus

class BaseService(ABC):
    """
    Base class for all services with improved event handling.
    
    This class provides:
    - Service lifecycle management (start/stop)
    - Typed event publishing and handling
    - Service registration and dependency management
    - Structured logging with context
    
    All services should inherit from this class and define their produced and consumed events.
    """
    
    # Define events produced by this service
    # Map of EventType to event class and description
    PRODUCES_EVENTS: ClassVar[Dict[EventType, Dict[str, Any]]] = {}
    
    # Define events consumed by this service
    # Map of EventType to handler method name
    CONSUMES_EVENTS: ClassVar[Dict[EventType, str]] = {}
    
    # Define required services
    REQUIRED_SERVICES: ClassVar[Set[str]] = set()
    
    def __init__(self, 
                 event_bus: EventBus, 
                 service_registry: ServiceRegistry,
                 name: Optional[str] = None,
                 config: Optional[Any] = None):
        """
        Initialize the service.
        
        Args:
            event_bus: The event bus for publishing and subscribing to events
            service_registry: The service registry for service lifecycle management
            name: Optional service name (defaults to class name)
            config: Optional service configuration
        """
        self.event_bus = event_bus
        self.service_registry = service_registry
        self.name = name or self.__class__.__name__
        self.config = config
        
        # Set up structured logging with service context
        self.logger = structlog.get_logger(service=self.name)
        
        # Service state
        self._running = False
        self._lock = asyncio.Lock()
        
        # Register events this service produces
        for event_type, event_info in self.PRODUCES_EVENTS.items():
            event_bus.registry.register_producer(self.name, event_type)
            # Register the event schema if defined
            if 'schema' in event_info and 'description' in event_info:
                event_bus.registry.register_event(
                    event_type, 
                    event_info['schema'], 
                    event_info['description']
                )
            
        # Register with service registry
        self.service_registry.register_service(self.name, self)
        
        # Register dependencies
        for dependency in self.REQUIRED_SERVICES:
            self.service_registry.register_dependency(self.name, dependency)
            
    async def start(self) -> None:
        """
        Start the service.
        
        This method:
        1. Checks all required services are running
        2. Subscribes to events
        3. Performs service-specific initialization
        
        Implementations should call super().start() first.
        """
        async with self._lock:
            if self._running:
                self.logger.warning("Service already running")
                return
                
            # Check required services
            for dependency in self.REQUIRED_SERVICES:
                if self.service_registry.get_service_state(dependency) != 'running':
                    raise RuntimeError(f"Required service {dependency} is not running")
            
            # Subscribe to events
            for event_type, handler_name in self.CONSUMES_EVENTS.items():
                handler = getattr(self, handler_name)
                self.event_bus.subscribe(event_type, handler, self.name)
                
            # Set running state
            self._running = True
            self.service_registry.set_service_state(self.name, 'running')
            self.logger.info("Service started")
            
            # Publish service state event
            await self.publish_service_state('started')
            
    async def stop(self) -> None:
        """
        Stop the service.
        
        This method:
        1. Unsubscribes from events
        2. Performs service-specific cleanup
        3. Marks the service as stopped
        
        Implementations should call super().stop() at the end.
        """
        async with self._lock:
            if not self._running:
                self.logger.warning("Service already stopped")
                return
                
            # Publish service state event before stopping
            await self.publish_service_state('stopping')
                
            # Unsubscribe from events
            for event_type in self.CONSUMES_EVENTS.keys():
                handler = getattr(self, self.CONSUMES_EVENTS[event_type])
                self.event_bus.unsubscribe(event_type, handler)
                
            # Set stopped state
            self._running = False
            self.service_registry.set_service_state(self.name, 'stopped')
            self.logger.info("Service stopped")
            
            # Publish final service state event
            await self.publish_service_state('stopped')
            
    async def publish(self, event: BaseEvent) -> None:
        """
        Publish an event through the bus.
        
        Args:
            event: The event to publish
        """
        if not self._running:
            self.logger.warning("Attempted publish while stopped", 
                                event_type=event.type)
            return
            
        # Set producer name if not already set
        if not event.producer_name:
            event.producer_name = self.name
            
        await self.event_bus.publish(event, self.name)
        
    async def publish_service_state(self, state: str) -> None:
        """
        Publish a service state change event.
        
        Args:
            state: New state of the service
        """
        from phoenix.events.system import ServiceStateChangedEvent
        
        event = ServiceStateChangedEvent(
            producer_name=self.name,
            service_name=self.name,
            state=state
        )
        await self.event_bus.publish(event, self.name)
        
    @abstractmethod
    async def handle_event(self, event: BaseEvent) -> None:
        """
        Handle an event from the event bus.
        
        This method is called by the event handlers when an event is received.
        When a service registers a handler in CONSUMES_EVENTS, the handler should
        call this method to standardize event handling.
        
        Args:
            event: The event to handle
        """
        pass 