"""
Voice interaction events for the Phoenix AI Companion Toy.

This module defines events related to voice interaction, including
wake word detection, intent detection, and conversation flow.
"""

from typing import Dict, Any, Optional, Literal, List
from phoenix.core.events import BaseEvent, EventType

class WakeWordDetectedEvent(BaseEvent):
    """
    Event published when a wake word is detected.
    
    This event triggers the intent detection process.
    """
    type: Literal[EventType.WAKE_WORD_DETECTED] = EventType.WAKE_WORD_DETECTED
    confidence: Optional[float] = None  # Detection confidence if available
    
class IntentDetectionStartedEvent(BaseEvent):
    """
    Event published when intent detection starts.
    
    This event signals the beginning of the intent detection phase
    after a wake word has been detected.
    """
    type: Literal[EventType.INTENT_DETECTION_STARTED] = EventType.INTENT_DETECTION_STARTED
    timeout: float  # Detection timeout in seconds
    
class IntentDetectionTimeoutEvent(BaseEvent):
    """
    Event published when intent detection times out.
    
    This event indicates that no intent was detected within the timeout period.
    """
    type: Literal[EventType.INTENT_DETECTION_TIMEOUT] = EventType.INTENT_DETECTION_TIMEOUT
    
class IntentDetectedEvent(BaseEvent):
    """
    Event published when an intent is detected.
    
    This event contains information about the detected intent,
    including any extracted slots (parameters).
    """
    type: Literal[EventType.INTENT_DETECTED] = EventType.INTENT_DETECTED
    intent: str  # Name of the detected intent
    slots: Dict[str, Any] = {}  # Extracted parameters
    confidence: float  # Detection confidence
    raw_text: Optional[str] = None  # Original text if available
    
class ConversationStartingEvent(BaseEvent):
    """
    Event published when a conversation is about to begin.
    
    This event signals that the conversation service is initializing
    a new conversation.
    """
    type: Literal[EventType.CONVERSATION_STARTING] = EventType.CONVERSATION_STARTING
    
class ConversationStartedEvent(BaseEvent):
    """
    Event published when a conversation has started.
    
    This event indicates that the conversation is active and ready
    for interaction.
    """
    type: Literal[EventType.CONVERSATION_STARTED] = EventType.CONVERSATION_STARTED
    conversation_id: Optional[str] = None
    
class ConversationEndedEvent(BaseEvent):
    """
    Event published when a conversation has ended.
    
    This event indicates that the conversation has completed,
    either normally or due to an error.
    """
    type: Literal[EventType.CONVERSATION_ENDED] = EventType.CONVERSATION_ENDED
    conversation_id: Optional[str] = None
    reason: Optional[str] = None  # Reason for ending ('completed', 'timeout', 'error', etc.)
    
class ConversationErrorEvent(BaseEvent):
    """
    Event published when a conversation encounters an error.
    
    This event provides details about conversation errors to allow
    other services to potentially recover or adapt.
    """
    type: Literal[EventType.CONVERSATION_ERROR] = EventType.CONVERSATION_ERROR
    error: str
    conversation_id: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    
class ConversationJoiningEvent(BaseEvent):
    """
    Event published when joining a conversation service.
    
    This event indicates that the system is connecting to the
    conversation service.
    """
    type: Literal[EventType.CONVERSATION_JOINING] = EventType.CONVERSATION_JOINING
    
class SpeechUpdateEvent(BaseEvent):
    """
    Event published to update speech status during conversation.
    
    This event indicates speech activity changes during a conversation,
    such as when the user or assistant starts or stops speaking.
    """
    type: Literal[EventType.SPEECH_UPDATE] = EventType.SPEECH_UPDATE
    role: str  # 'user' or 'assistant'
    status: str  # 'started' or 'stopped'
    
class CallStateEvent(BaseEvent):
    """
    Event published to report call state changes.
    
    This event indicates changes in the underlying call connection
    status.
    """
    type: Literal[EventType.CALL_STATE] = EventType.CALL_STATE
    state: str  # 'connecting', 'connected', 'disconnected', 'ended', 'error'
    error: Optional[str] = None  # Present only if state is 'error' 