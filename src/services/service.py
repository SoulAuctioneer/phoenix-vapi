import logging
import asyncio
from typing import Dict, Any, Set, Callable, Awaitable, Optional
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum


EventHandler = Callable[[Dict[str, Any]], Awaitable[None]]


class GlobalState:
    """Immutable container for global application state"""
    def __init__(self):
        # Location state
        self.current_location: str = "unknown"
        self.location_beacons: Dict[str, Dict[str, Any]] = {}
        
        # Conversation state
        self.conversation_active: bool = False
        self.assistant_speaking: bool = False
        self.user_speaking: bool = False
        self.is_muted: bool = False
        
        # Audio state
        self.volume: float = 1.0
        
        # Sensor states
        self.acceleration: Optional[tuple] = None
        self.gyro: Optional[tuple] = None
        self.temperature: Optional[float] = None
        self.touch_state: bool = False
        self.touch_position: Optional[float] = None
        self.touch_intensity: Optional[float] = None


class ServiceManager:
    """Manages service lifecycle and event distribution"""
    def __init__(self):
        self.services = {}
        self._subscribers: Dict[str, Set[EventHandler]] = defaultdict(set)
        self._should_run = True
        self._lock = asyncio.Lock()
        self.logger = logging.getLogger(__name__)
        
    async def start_service(self, name: str, service: 'BaseService'):
        """Start a service and store it in the manager"""
        await service.start()
        self.services[name] = service
        
        # Auto-subscribe the service's handle_event method
        await self.subscribe("*", service.handle_event)
        self.logger.debug(f"Started service: {name}")
        
    async def stop_service(self, name: str):
        """Stop a service and remove it from the manager"""
        if name in self.services:
            service = self.services[name]
            # Unsubscribe from all events
            await self.unsubscribe("*", service.handle_event)
            await service.stop()                
            del self.services[name]
            self.logger.debug(f"Stopped service: {name}")
            
    async def stop_all(self):
        """Stop all services"""
        self._should_run = False
        self.logger.info("Stopping all services...")
        for name in list(self.services.keys()):
            await self.stop_service(name)
            
    async def subscribe(self, event_type: str, handler: EventHandler):
        """Subscribe to an event type. Use '*' for all events."""
        async with self._lock:
            self._subscribers[event_type].add(handler)
            self.logger.debug(f"Subscribed to {event_type}: {handler.__qualname__}")
            
    async def unsubscribe(self, event_type: str, handler: EventHandler):
        """Unsubscribe from an event type"""
        async with self._lock:
            if event_type in self._subscribers:
                self._subscribers[event_type].discard(handler)
                if not self._subscribers[event_type]:
                    del self._subscribers[event_type]
                self.logger.debug(f"Unsubscribed from {event_type}: {handler.__qualname__}")
                
    async def publish(self, event: Dict[str, Any]):
        """Publish an event to subscribers"""
        if not self._should_run:
            return
            
        event_type = event.get("type")
        if not event_type:
            self.logger.warning("Received event without type")
            return
            
        self.logger.debug(f"Publishing event: {event}")
        
        async with self._lock:
            # Get both specific handlers and wildcard handlers
            handlers = self._subscribers.get(event_type, set()) | self._subscribers.get("*", set())
            
        if not handlers:
            self.logger.debug(f"No handlers for event type: {event_type}")
            return
            
        # Create tasks for all handlers
        tasks = []
        for handler in handlers:
            task = asyncio.create_task(self._safe_handle_event(handler, event))
            tasks.append(task)
            
        # Wait for all handlers to complete
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Log any errors
            for result in results:
                if isinstance(result, Exception):
                    self.logger.error(f"Error in event handler: {result}", exc_info=True)
                    
    async def _safe_handle_event(self, handler: EventHandler, event: Dict[str, Any]):
        """Safely execute an event handler"""
        try:
            await handler(event)
        except Exception as e:
            self.logger.error(f"Error in event handler {handler.__qualname__}: {e}", exc_info=True)
            raise


class BaseService:
    """Base class for all services"""
    def __init__(self, manager: ServiceManager):
        self.manager = manager
        self._running = False
        # Create a logger with the full module path and class name
        self.logger = logging.getLogger(f"{self.__class__.__module__}.{self.__class__.__name__}")
        self.global_state = GlobalState()
        
    async def start(self):
        """Start the service"""
        self._running = True
        
    async def stop(self):
        """Stop the service"""
        self._running = False
        
    async def publish(self, event: Dict[str, Any]):
        """Helper method to publish events"""
        await self.manager.publish(event) 

    async def handle_event(self, event: Dict[str, Any]):
        """Handle events from other services
           This base class updates the global state based on received events"""
        event_type = event.get("type")
        
        async with self._state_lock:
            if event_type == "location_changed":
                self._state.current_location = event["data"]["location"]
                
            elif event_type == "proximity_changed":
                location = event["data"]["location"]
                if event["data"]["distance"] == "UNKNOWN":
                    self._state.location_beacons.pop(location, None)
                else:
                    self._state.location_beacons[location] = {
                        "distance": event["data"]["distance"],
                        "rssi": event["data"]["rssi"]
                    }
                    
            elif event_type == "conversation_starting":
                self._state.conversation_active = True
                self._state.conversation_error = None  # Clear any previous error
                
            elif event_type == "conversation_ended":
                self._state.conversation_active = False
                self._state.assistant_speaking = False
                self._state.user_speaking = False
                
            elif event_type == "conversation_error":
                self._state.conversation_active = False  # Conversation ends on error
                self._state.assistant_speaking = False
                self._state.user_speaking = False
                
            elif event_type == "speech-update":
                role = event["role"]
                is_speaking = event["status"] == "started"
                if role == "assistant":
                    self._state.assistant_speaking = is_speaking
                elif role == "user":
                    self._state.user_speaking = is_speaking
                    
            elif event_type == "sensor_data":
                if event["sensor"] == "accelerometer":
                    self._state.acceleration = event["data"]["acceleration"]
                    self._state.gyro = event["data"]["gyro"]
                    self._state.temperature = event["data"]["temperature"]
                    
            elif event_type == "touch_state":
                self._state.touch_state = event["is_touching"]
                
            elif event_type == "touch_position":
                self._state.touch_position = event["position"]
                
            elif event_type == "touch_intensity":
                self._state.touch_intensity = event["intensity"]
                
            elif event_type == "volume_changed":
                self._state.volume = event["volume"]
                
            elif event_type == "microphone_state":
                self._state.is_muted = event["is_muted"]
