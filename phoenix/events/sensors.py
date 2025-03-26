"""
Sensor events for the Phoenix AI Companion Toy.

This module defines events related to sensors, including
touch, location, audio, and movement sensing.
"""

from typing import Dict, Any, Optional, Literal, List, Tuple, Union
from phoenix.core.events import BaseEvent, EventType
from phoenix.core.config import Distance

class LocationChangedEvent(BaseEvent):
    """
    Event published when the Phoenix's location changes.
    
    This event signals a detected change in location based on
    beacon proximity.
    """
    type: Literal[EventType.LOCATION_CHANGED] = EventType.LOCATION_CHANGED
    data: Dict[str, Any]  # Contains 'location' and 'previous_location'
    
class ProximityChangedEvent(BaseEvent):
    """
    Event published when proximity to a beacon changes.
    
    This event signals a detected change in proximity to a
    specific beacon.
    """
    type: Literal[EventType.PROXIMITY_CHANGED] = EventType.PROXIMITY_CHANGED
    data: Dict[str, Any]  # Contains 'location', 'distance', 'previous_distance', 'rssi'
    
class TouchStateEvent(BaseEvent):
    """
    Event published when touch state changes.
    
    This event signals whether the Phoenix is being touched.
    """
    type: Literal[EventType.TOUCH_STATE] = EventType.TOUCH_STATE
    is_touching: bool  # Whether the Phoenix is being touched
    
class TouchPositionEvent(BaseEvent):
    """
    Event published when touch position is detected.
    
    This event signals the position of touch on the Phoenix.
    """
    type: Literal[EventType.TOUCH_POSITION] = EventType.TOUCH_POSITION
    position: float  # Position of touch (0.0 to 1.0)
    
class TouchStrokeIntensityEvent(BaseEvent):
    """
    Event published when stroke intensity changes.
    
    This event signals the intensity of stroking motion on the Phoenix.
    """
    type: Literal[EventType.TOUCH_STROKE_INTENSITY] = EventType.TOUCH_STROKE_INTENSITY
    intensity: float  # Intensity of stroke (0.0 to 1.0)
    
class SensorDataEvent(BaseEvent):
    """
    Event published with generic sensor data.
    
    This event contains raw sensor readings for various sensors.
    """
    type: Literal[EventType.SENSOR_DATA] = EventType.SENSOR_DATA
    data: Dict[str, Any]  # Sensor data (specific to sensor type)
    
class VolumeChangedEvent(BaseEvent):
    """
    Event published when audio volume changes.
    
    This event signals a change in the system's audio output volume.
    """
    type: Literal[EventType.VOLUME_CHANGED] = EventType.VOLUME_CHANGED
    volume: float  # New volume level (0.0 to 1.0)
    
class MicrophoneStateEvent(BaseEvent):
    """
    Event published when microphone state changes.
    
    This event signals whether the microphone is muted.
    """
    type: Literal[EventType.MICROPHONE_STATE] = EventType.MICROPHONE_STATE
    is_muted: bool  # Whether the microphone is muted
    
class PlayEffectEvent(BaseEvent):
    """
    Event published to request playing a sound effect.
    
    This event triggers the special effect service to play
    the specified sound effect.
    """
    type: Literal[EventType.PLAY_EFFECT] = EventType.PLAY_EFFECT
    effect: str  # Name of the effect to play
    volume: Optional[float] = None  # Volume level for this effect (0.0 to 1.0)
    
class EffectPlayedEvent(BaseEvent):
    """
    Event published when a sound effect has been played.
    
    This event signals that the requested sound effect has
    been played.
    """
    type: Literal[EventType.EFFECT_PLAYED] = EventType.EFFECT_PLAYED
    effect: str  # Name of the effect that was played
    
class BatteryStateEvent(BaseEvent):
    """
    Event published with battery state information.
    
    This event contains information about the battery level
    and charging status.
    """
    type: Literal[EventType.BATTERY_STATE] = EventType.BATTERY_STATE
    level: float  # Battery level (0.0 to 1.0)
    is_charging: bool  # Whether the battery is charging
    voltage: Optional[float] = None  # Battery voltage if available
    
class MovementDetectedEvent(BaseEvent):
    """
    Event published when significant movement is detected.
    
    This event signals that the Phoenix has been moved or shaken.
    """
    type: Literal[EventType.MOVEMENT_DETECTED] = EventType.MOVEMENT_DETECTED
    magnitude: float  # Magnitude of movement
    direction: Optional[Tuple[float, float, float]] = None  # 3D direction vector if available 