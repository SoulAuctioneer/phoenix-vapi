"""
Event tracing system for the Phoenix AI Companion Toy.

This module provides observability into the event flow through the system,
facilitating debugging, monitoring, and performance analysis.
"""

import time
import logging
import threading
import uuid
from typing import Dict, List, Optional, Any, Deque
from collections import deque
from .events import BaseEvent

class EventTracer:
    """
    Traces event flow through the system for debugging and observability.
    
    This tracer records events as they're published and delivered, maintaining
    a buffer of recent events for analysis. It can also generate trace visualizations
    and statistics.
    """
    
    def __init__(self, max_events: int = 1000):
        """
        Initialize the event tracer.
        
        Args:
            max_events: Maximum number of events to keep in the buffer
        """
        self.max_events = max_events
        self.events: Deque[Dict[str, Any]] = deque(maxlen=max_events)
        self.current_trace_id = threading.local()
        self.logger = logging.getLogger(__name__)
        
    def record_event(self, event: BaseEvent) -> None:
        """
        Record an event in the trace buffer.
        
        Args:
            event: The event to record
        """
        # Extract relevant information from the event
        trace_data = {
            'timestamp': time.time(),
            'trace_id': event.trace_id,
            'type': event.type,
            'producer': event.producer_name,
            'event_data': event.dict(exclude={'trace_id', 'type', 'producer_name'})
        }
        
        # Add to the buffer
        self.events.append(trace_data)
        self.logger.debug(f"Recorded event {event.type} from {event.producer_name}")
        
    def get_current_trace_id(self) -> str:
        """
        Get the current trace ID for the thread or generate a new one.
        
        Returns:
            The current trace ID
        """
        if not hasattr(self.current_trace_id, 'value'):
            self.current_trace_id.value = str(uuid.uuid4())
        return self.current_trace_id.value
        
    def set_trace_id(self, trace_id: str) -> None:
        """
        Set the current trace ID for the thread.
        
        Args:
            trace_id: The trace ID to set
        """
        self.current_trace_id.value = trace_id
        
    def clear_trace_id(self) -> None:
        """Clear the current trace ID for the thread."""
        if hasattr(self.current_trace_id, 'value'):
            delattr(self.current_trace_id, 'value')
            
    def get_trace(self, trace_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get all events for a specific trace ID.
        
        Args:
            trace_id: The trace ID to filter by, or None for all events
            
        Returns:
            List of events matching the trace ID
        """
        if trace_id is None:
            return list(self.events)
        return [e for e in self.events if e['trace_id'] == trace_id]
        
    def get_events_by_type(self, event_type: str) -> List[Dict[str, Any]]:
        """
        Get all events of a specific type.
        
        Args:
            event_type: The event type to filter by
            
        Returns:
            List of events matching the type
        """
        return [e for e in self.events if e['type'] == event_type]
        
    def get_events_by_producer(self, producer_name: str) -> List[Dict[str, Any]]:
        """
        Get all events from a specific producer.
        
        Args:
            producer_name: The producer name to filter by
            
        Returns:
            List of events matching the producer
        """
        return [e for e in self.events if e['producer'] == producer_name]
        
    def get_event_count(self) -> int:
        """
        Get the total number of events recorded.
        
        Returns:
            The total event count
        """
        return len(self.events)
        
    def clear(self) -> None:
        """Clear all recorded events."""
        self.events.clear()
        
    def get_event_rate(self, window_seconds: int = 60) -> float:
        """
        Calculate the event rate over a time window.
        
        Args:
            window_seconds: Time window in seconds
            
        Returns:
            Events per second over the window
        """
        if not self.events:
            return 0.0
            
        now = time.time()
        window_start = now - window_seconds
        events_in_window = [e for e in self.events if e['timestamp'] >= window_start]
        
        if not events_in_window:
            return 0.0
            
        return len(events_in_window) / window_seconds
        
    def get_event_stats(self) -> Dict[str, Any]:
        """
        Get statistics about recorded events.
        
        Returns:
            Dictionary with event statistics
        """
        if not self.events:
            return {
                'total_events': 0,
                'event_types': {},
                'producers': {},
                'rate_per_second': 0.0
            }
            
        # Calculate stats
        event_types = {}
        producers = {}
        
        for event in self.events:
            event_type = event['type']
            producer = event['producer']
            
            # Count by type
            if event_type in event_types:
                event_types[event_type] += 1
            else:
                event_types[event_type] = 1
                
            # Count by producer
            if producer in producers:
                producers[producer] += 1
            else:
                producers[producer] = 1
                
        return {
            'total_events': len(self.events),
            'event_types': event_types,
            'producers': producers,
            'rate_per_second': self.get_event_rate()
        } 