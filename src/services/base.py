import logging
import asyncio
from typing import Dict, Any

class ServiceManager:
    """Manages the lifecycle of all services"""
    def __init__(self):
        self.services = {}
        self.event_bus = asyncio.Queue()
        self._should_run = True
        
    async def start_service(self, name: str, service: 'BaseService'):
        """Start a service and store it in the manager"""
        await service.start()
        self.services[name] = service
        
    async def stop_service(self, name: str):
        """Stop a service and remove it from the manager"""
        if name in self.services:
            await self.services[name].stop()
            del self.services[name]
            
    async def stop_all(self):
        """Stop all services"""
        self._should_run = False
        # Cancel any pending events
        while not self.event_bus.empty():
            try:
                self.event_bus.get_nowait()
                self.event_bus.task_done()
            except asyncio.QueueEmpty:
                break
        
        for name in list(self.services.keys()):
            await self.stop_service(name)
            
    async def publish_event(self, event: Dict[str, Any]):
        """Publish an event to the event bus"""
        if self._should_run:
            await self.event_bus.put(event)
        
    async def process_events(self):
        """Process events from the event bus"""
        try:
            while self._should_run:
                try:
                    event = await asyncio.wait_for(self.event_bus.get(), timeout=0.1)
                    for service in self.services.values():
                        await service.handle_event(event)
                    self.event_bus.task_done()
                except asyncio.TimeoutError:
                    continue
                except asyncio.CancelledError:
                    break
        finally:
            self._should_run = False

class BaseService:
    """Base class for all services"""
    def __init__(self, manager: ServiceManager):
        self.manager = manager
        self._running = False
        
    async def start(self):
        """Start the service"""
        self._running = True
        
    async def stop(self):
        """Stop the service"""
        self._running = False
        
    async def handle_event(self, event: Dict[str, Any]):
        """Handle events from other services"""
        pass 