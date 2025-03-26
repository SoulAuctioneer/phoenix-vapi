"""
Core event system for the Phoenix AI Companion Toy.

This module defines the base event models and event type enum that form the foundation
of the typed event system. All events in the system should inherit from BaseEvent.
"""

from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Any, Literal, Union
from enum import Enum, auto
import time
import uuid

class EventType(str, Enum):
    """
    Enum defining all event types in the system.
    
    Using string-based enum to ensure JSON serialization works properly.
    """
    # Wake word and intent events
    WAKE_WORD_DETECTED = "wake_word_detected"
    INTENT_DETECTION_STARTED = "intent_detection_started"
    INTENT_DETECTION_TIMEOUT = "intent_detection_timeout"
    INTENT_DETECTED = "intent_detected"
    
    # Application lifecycle events
    APPLICATION_STARTUP_COMPLETED = "application_startup_completed"
    
    # Conversation events
    CONVERSATION_STARTING = "conversation_starting"
    CONVERSATION_STARTED = "conversation_started"
    CONVERSATION_ENDED = "conversation_ended"
    CONVERSATION_ERROR = "conversation_error"
    CONVERSATION_JOINING = "conversation_joining"
    SPEECH_UPDATE = "speech_update"
    CALL_STATE = "call_state"
    
    # Activity events
    ACTIVITY_STARTED = "activity_started"
    ACTIVITY_STOPPED = "activity_stopped"
    
    # Location events
    LOCATION_CHANGED = "location_changed"
    PROXIMITY_CHANGED = "proximity_changed"
    START_SENSING_PHOENIX_DISTANCE = "start_sensing_phoenix_distance"
    STOP_SENSING_PHOENIX_DISTANCE = "stop_sensing_phoenix_distance"
    
    # Hide and seek events
    HIDE_SEEK_WON = "hide_seek_won"
    HIDE_SEEK_FOUND = "hide_seek_found"
    HIDE_SEEK_HINT = "hide_seek_hint"
    
    # Sensor events
    TOUCH_STATE = "touch_state"
    TOUCH_POSITION = "touch_position"
    TOUCH_STROKE_INTENSITY = "touch_stroke_intensity"
    SENSOR_DATA = "sensor_data"
    VOLUME_CHANGED = "volume_changed"
    MICROPHONE_STATE = "microphone_state"
    
    # Effect events
    PLAY_EFFECT = "play_effect"
    EFFECT_PLAYED = "effect_played"
    
    # Battery events
    BATTERY_STATE = "battery_state"
    
    # Movement events
    MOVEMENT_DETECTED = "movement_detected"
    
    # Sleep events
    SLEEP_MODE_ENTERED = "sleep_mode_entered"
    SLEEP_MODE_EXITED = "sleep_mode_exited"
    
    # System events
    SERVICE_ERROR = "service_error"
    HARDWARE_ERROR = "hardware_error"
    SERVICE_STATE_CHANGED = "service_state_changed"

def generate_trace_id() -> str:
    """Generate a unique trace ID for event tracing."""
    return str(uuid.uuid4())

class BaseEvent(BaseModel):
    """
    Base model for all events with common metadata.
    
    All events in the system should inherit from this class and specify the event type
    and any additional payload fields required for that event.
    """
    type: EventType
    producer_name: str
    timestamp: float = Field(default_factory=time.time)
    trace_id: Optional[str] = Field(default_factory=generate_trace_id)
    
    class Config:
        """Pydantic configuration"""
        # Allow extra attributes to be specified (useful for future compatibility)
        extra = "allow"
        # Use enum values rather than the enum objects themselves
        use_enum_values = True 