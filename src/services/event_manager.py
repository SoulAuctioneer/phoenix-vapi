import asyncio
import logging
from typing import Dict, Set, Any, Callable, Awaitable
from collections import defaultdict

EventHandler = Callable[[Dict[str, Any]], Awaitable[None]]

class EventManager:
    """Manages event publishing and subscription"""
    def __init__(self):
        self._subscribers: Dict[str, Set[EventHandler]] = defaultdict(set)
        self._lock = asyncio.Lock()
        
    async def subscribe(self, event_type: str, handler: EventHandler):
        """Subscribe to an event type"""
        async with self._lock:
            self._subscribers[event_type].add(handler)
            
    async def unsubscribe(self, event_type: str, handler: EventHandler):
        """Unsubscribe from an event type"""
        async with self._lock:
            if event_type in self._subscribers:
                self._subscribers[event_type].discard(handler)
                if not self._subscribers[event_type]:
                    del self._subscribers[event_type]
                    
    async def publish(self, event: Dict[str, Any]):
        """Publish an event to all subscribers"""
        event_type = event.get("type")
        if not event_type:
            logging.warning("Received event without type")
            return
            
        async with self._lock:
            handlers = self._subscribers.get(event_type, set()).copy()
            
        if not handlers:
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
                    logging.error(f"Error in event handler: {result}")
                    
    async def _safe_handle_event(self, handler: EventHandler, event: Dict[str, Any]):
        """Safely execute an event handler"""
        try:
            await handler(event)
        except Exception as e:
            logging.error(f"Error in event handler {handler.__name__}: {e}")
            # Re-raise to be caught by gather
            raise 