"""
Activity events for the Phoenix AI Companion Toy.

This module defines events related to activities, including
activity changes, hide and seek, sleep mode, and other interactive modes.
"""

from typing import Dict, Any, Optional, Literal, List
from phoenix.core.events import BaseEvent, EventType

class ActivityStartedEvent(BaseEvent):
    """
    Event published when an activity has started.
    
    This event signals that a new activity is now active.
    """
    type: Literal[EventType.ACTIVITY_STARTED] = EventType.ACTIVITY_STARTED
    activity: str  # Name of the activity ('conversation', 'hide_seek', 'sleep', etc.)
    params: Optional[Dict[str, Any]] = None  # Additional activity parameters
    
class ActivityStoppedEvent(BaseEvent):
    """
    Event published when an activity has stopped.
    
    This event signals that an activity is no longer active.
    """
    type: Literal[EventType.ACTIVITY_STOPPED] = EventType.ACTIVITY_STOPPED
    activity: str  # Name of the activity ('conversation', 'hide_seek', 'sleep', etc.)
    reason: Optional[str] = None  # Reason for stopping ('completed', 'interrupted', 'error', etc.)
    
class HideSeekWonEvent(BaseEvent):
    """
    Event published when the hide and seek game is won.
    
    This event signals that the player has successfully found the Phoenix.
    """
    type: Literal[EventType.HIDE_SEEK_WON] = EventType.HIDE_SEEK_WON
    duration: Optional[float] = None  # Duration of the game in seconds
    
class HideSeekFoundEvent(BaseEvent):
    """
    Event published when the player is found during hide and seek.
    
    This event signals that the Phoenix has found the player.
    """
    type: Literal[EventType.HIDE_SEEK_FOUND] = EventType.HIDE_SEEK_FOUND
    duration: Optional[float] = None  # Duration of the game in seconds
    
class HideSeekHintEvent(BaseEvent):
    """
    Event published to provide a hint during hide and seek.
    
    This event signals that a hint should be given to help the player.
    """
    type: Literal[EventType.HIDE_SEEK_HINT] = EventType.HIDE_SEEK_HINT
    hint_type: str  # Type of hint ('sound', 'direction', 'distance', etc.)
    hint_data: Optional[Dict[str, Any]] = None  # Additional hint data
    
class StartSensingPhoenixDistanceEvent(BaseEvent):
    """
    Event published to request distance sensing to start.
    
    This event triggers the location service to start monitoring
    the distance to the Phoenix.
    """
    type: Literal[EventType.START_SENSING_PHOENIX_DISTANCE] = EventType.START_SENSING_PHOENIX_DISTANCE
    
class StopSensingPhoenixDistanceEvent(BaseEvent):
    """
    Event published to request distance sensing to stop.
    
    This event triggers the location service to stop monitoring
    the distance to the Phoenix.
    """
    type: Literal[EventType.STOP_SENSING_PHOENIX_DISTANCE] = EventType.STOP_SENSING_PHOENIX_DISTANCE
    
class SleepModeEnteredEvent(BaseEvent):
    """
    Event published when sleep mode is entered.
    
    This event signals that the Phoenix has entered a low-power,
    ambient awareness mode.
    """
    type: Literal[EventType.SLEEP_MODE_ENTERED] = EventType.SLEEP_MODE_ENTERED
    
class SleepModeExitedEvent(BaseEvent):
    """
    Event published when sleep mode is exited.
    
    This event signals that the Phoenix has exited sleep mode
    and is becoming more active.
    """
    type: Literal[EventType.SLEEP_MODE_EXITED] = EventType.SLEEP_MODE_EXITED
    reason: Optional[str] = None  # Reason for exiting ('wake_word', 'touch', 'movement', etc.) 