import logging
import asyncio
from typing import Dict, Any

class ServiceManager:
    """Manages the lifecycle of all services"""
    def __init__(self):
        self.services = {}
        self.event_bus = asyncio.Queue()
        
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
        for name in list(self.services.keys()):
            await self.stop_service(name)
            
    async def publish_event(self, event: Dict[str, Any]):
        """Publish an event to the event bus"""
        await self.event_bus.put(event)
        
    async def process_events(self):
        """Process events from the event bus"""
        while True:
            event = await self.event_bus.get()
            for service in self.services.values():
                await service.handle_event(event)
            self.event_bus.task_done()

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