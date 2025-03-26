"""
Event bus for the Phoenix AI Companion Toy.

This module provides the event bus that delivers events between services.
It handles event validation, tracing, and delivery to subscribers.
"""

import asyncio
import logging
from typing import Dict, List, Optional, Any, Callable, Awaitable, Set
from .events import EventType, BaseEvent
from .registry import EventRegistry
from .tracing import EventTracer

# Type aliases
EventHandler = Callable[[BaseEvent], Awaitable[None]]

class EventBus:
    """
    Central event bus for delivering typed events between services.
    
    The event bus is responsible for:
    - Validating events against their registered schemas
    - Tracking event producers and consumers
    - Routing events to subscribers
    - Handling errors during event delivery
    - Providing observability through tracing
    """
    
    def __init__(self, registry: EventRegistry, tracer: Optional[EventTracer] = None):
        """
        Initialize the event bus.
        
        Args:
            registry: The event registry for validation and tracking
            tracer: Optional event tracer for observability
        """
        self.registry = registry
        self.tracer = tracer
        self.subscribers: Dict[EventType, List[EventHandler]] = {}
        self.wildcard_subscribers: List[EventHandler] = []
        self.logger = logging.getLogger(__name__)
        
    async def publish(self, event: BaseEvent, sender: str) -> None:
        """
        Publish an event to all subscribers.
        
        Args:
            event: The event to publish
            sender: Name of the service publishing the event
        """
        # Set producer name if not set
        if not event.producer_name:
            event.producer_name = sender
            
        # Validate event against registry
        try:
            self.registry.validate_schema(event)
        except (ValueError, TypeError) as e:
            self.logger.error(f"Event validation failed: {e}")
            return
            
        # Trace the event
        if self.tracer:
            self.tracer.record_event(event)
            
        # Get event type and find subscribers
        event_type = event.type
        specific_subscribers = self.subscribers.get(event_type, [])
        all_subscribers = specific_subscribers + self.wildcard_subscribers
        
        if not all_subscribers:
            self.logger.debug(f"No subscribers for event type: {event_type}")
            return
            
        # Deliver to subscribers
        tasks = []
        for subscriber in all_subscribers:
            task = asyncio.create_task(self._deliver_event(subscriber, event))
            tasks.append(task)
            
        # Wait for all handlers to complete
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Log any errors
            for result in results:
                if isinstance(result, Exception):
                    self.logger.error(f"Error in event handler: {result}", exc_info=True)
    
    async def _deliver_event(self, handler: EventHandler, event: BaseEvent) -> None:
        """
        Deliver an event to a single handler with error handling.
        
        Args:
            handler: The event handler function
            event: The event to deliver
        """
        try:
            await handler(event)
        except asyncio.CancelledError:
            # Re-raise cancellation to allow proper cleanup
            raise
        except Exception as e:
            self.logger.error(f"Error delivering event {event.type} to {handler.__qualname__}: {e}")
            # Do not propagate exceptions from event handlers to avoid
            # crashing the entire event delivery system
                
    def subscribe(self, event_type: Optional[EventType], handler: EventHandler, service_name: str) -> None:
        """
        Subscribe a handler to events of a specific type, or all events if None.
        
        Args:
            event_type: The event type to subscribe to, or None for all events
            handler: The handler function to call when events arrive
            service_name: Name of the service subscribing
        """
        if event_type is None:
            # Subscribe to all events (wildcard)
            self.wildcard_subscribers.append(handler)
            self.logger.debug(f"Service {service_name} subscribed to all events")
        else:
            # Subscribe to specific event type
            if event_type not in self.subscribers:
                self.subscribers[event_type] = []
            self.subscribers[event_type].append(handler)
            
            # Update registry
            self.registry.register_consumer(service_name, event_type)
            self.logger.debug(f"Service {service_name} subscribed to {event_type}")
            
    def unsubscribe(self, event_type: Optional[EventType], handler: EventHandler) -> None:
        """
        Unsubscribe a handler from events of a specific type, or all events if None.
        
        Args:
            event_type: The event type to unsubscribe from, or None for all events
            handler: The handler function to unsubscribe
        """
        if event_type is None:
            # Unsubscribe from all events
            if handler in self.wildcard_subscribers:
                self.wildcard_subscribers.remove(handler)
                self.logger.debug(f"Handler {handler.__qualname__} unsubscribed from all events")
        elif event_type in self.subscribers:
            # Unsubscribe from specific event type
            if handler in self.subscribers[event_type]:
                self.subscribers[event_type].remove(handler)
                if not self.subscribers[event_type]:
                    del self.subscribers[event_type]
                self.logger.debug(f"Handler {handler.__qualname__} unsubscribed from {event_type}")
                
    def get_subscribers(self, event_type: EventType) -> Set[EventHandler]:
        """
        Get all subscribers for an event type.
        
        Args:
            event_type: The event type to get subscribers for
            
        Returns:
            Set of event handlers subscribed to the event type
        """
        # Return both specific subscribers and wildcard subscribers
        specific = set(self.subscribers.get(event_type, []))
        wildcards = set(self.wildcard_subscribers)
        return specific.union(wildcards) 