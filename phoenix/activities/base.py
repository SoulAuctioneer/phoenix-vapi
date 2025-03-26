"""
Base activity implementation for the Phoenix AI Companion Toy.

This module provides the BaseActivity class that all activities should inherit from,
defining the core activity lifecycle and event handling interfaces.
"""

import asyncio
import structlog
from abc import ABC, abstractmethod
from typing import Dict, Set, Any, Optional, ClassVar, Type, List
from enum import Enum, auto
from phoenix.core.service import BaseService
from phoenix.core.events import BaseEvent, EventType
from phoenix.events.activities import ActivityStartedEvent, ActivityStoppedEvent

class ActivityState(Enum):
    """Possible states for an activity."""
    INITIALIZING = auto()  # Activity is being initialized
    ACTIVE = auto()        # Activity is running
    PAUSED = auto()        # Activity is paused
    STOPPING = auto()      # Activity is being stopped
    STOPPED = auto()       # Activity is stopped
    ERROR = auto()         # Activity encountered an error

class BaseActivity(BaseService, ABC):
    """
    Base class for all activities.
    
    Activities are special types of services that represent interactive modes
    of operation for the Phoenix. They coordinate the use of other services
    to provide specific experiences.
    
    Activities manage their own lifecycle through state transitions and can
    be started, paused, resumed, and stopped.
    """
    
    # Define a unique name for this activity type
    ACTIVITY_NAME: ClassVar[str] = ""
    
    # Define services required by this activity
    REQUIRED_SERVICES: ClassVar[Set[str]] = set()
    
    def __init__(self, *args, **kwargs):
        """Initialize the activity."""
        super().__init__(*args, **kwargs)
        self.state = ActivityState.STOPPED
        self.state_lock = asyncio.Lock()
        self.params = {}  # Activity-specific parameters
        
    async def handle_event(self, event: BaseEvent) -> None:
        """
        Handle an event from the event bus.
        
        This method dispatches to state-specific event handlers based on
        the current activity state.
        
        Args:
            event: The event to handle
        """
        if self.state == ActivityState.INITIALIZING:
            await self._handle_event_initializing(event)
        elif self.state == ActivityState.ACTIVE:
            await self._handle_event_active(event)
        elif self.state == ActivityState.PAUSED:
            await self._handle_event_paused(event)
        elif self.state == ActivityState.STOPPING:
            await self._handle_event_stopping(event)
        # Ignore events when stopped or in error state
        
    async def _handle_event_initializing(self, event: BaseEvent) -> None:
        """
        Handle events when in the INITIALIZING state.
        
        Args:
            event: The event to handle
        """
        # Default implementation does nothing
        pass
        
    async def _handle_event_active(self, event: BaseEvent) -> None:
        """
        Handle events when in the ACTIVE state.
        
        Args:
            event: The event to handle
        """
        # Default implementation does nothing
        pass
        
    async def _handle_event_paused(self, event: BaseEvent) -> None:
        """
        Handle events when in the PAUSED state.
        
        Args:
            event: The event to handle
        """
        # Default implementation does nothing
        pass
        
    async def _handle_event_stopping(self, event: BaseEvent) -> None:
        """
        Handle events when in the STOPPING state.
        
        Args:
            event: The event to handle
        """
        # Default implementation does nothing
        pass
    
    async def start_activity(self, params: Optional[Dict[str, Any]] = None) -> None:
        """
        Start the activity.
        
        This method transitions the activity to the ACTIVE state and
        publishes an ActivityStartedEvent.
        
        Args:
            params: Optional parameters for the activity
        """
        async with self.state_lock:
            if self.state != ActivityState.STOPPED:
                self.logger.warning(f"Cannot start activity from state {self.state}")
                return
                
            self.state = ActivityState.INITIALIZING
            self.params = params or {}
            
            try:
                # Initialize the activity (implementation-specific)
                await self._initialize()
                
                # Transition to active state
                self.state = ActivityState.ACTIVE
                
                # Publish activity started event
                await self.publish(ActivityStartedEvent(
                    producer_name=self.name,
                    activity=self.ACTIVITY_NAME,
                    params=self.params
                ))
                
                self.logger.info(f"Activity {self.ACTIVITY_NAME} started")
                
            except Exception as e:
                self.logger.error(f"Error starting activity: {e}")
                self.state = ActivityState.ERROR
                raise
    
    async def pause_activity(self) -> None:
        """
        Pause the activity.
        
        This method transitions the activity to the PAUSED state.
        """
        async with self.state_lock:
            if self.state != ActivityState.ACTIVE:
                self.logger.warning(f"Cannot pause activity from state {self.state}")
                return
                
            try:
                # Pause the activity (implementation-specific)
                await self._pause()
                
                # Transition to paused state
                self.state = ActivityState.PAUSED
                
                self.logger.info(f"Activity {self.ACTIVITY_NAME} paused")
                
            except Exception as e:
                self.logger.error(f"Error pausing activity: {e}")
                self.state = ActivityState.ERROR
                raise
    
    async def resume_activity(self) -> None:
        """
        Resume the activity.
        
        This method transitions the activity from PAUSED to ACTIVE state.
        """
        async with self.state_lock:
            if self.state != ActivityState.PAUSED:
                self.logger.warning(f"Cannot resume activity from state {self.state}")
                return
                
            try:
                # Resume the activity (implementation-specific)
                await self._resume()
                
                # Transition to active state
                self.state = ActivityState.ACTIVE
                
                self.logger.info(f"Activity {self.ACTIVITY_NAME} resumed")
                
            except Exception as e:
                self.logger.error(f"Error resuming activity: {e}")
                self.state = ActivityState.ERROR
                raise
    
    async def stop_activity(self, reason: Optional[str] = None) -> None:
        """
        Stop the activity.
        
        This method transitions the activity to the STOPPED state and
        publishes an ActivityStoppedEvent.
        
        Args:
            reason: Optional reason for stopping
        """
        async with self.state_lock:
            if self.state == ActivityState.STOPPED:
                self.logger.warning("Activity already stopped")
                return
                
            previous_state = self.state
            self.state = ActivityState.STOPPING
            
            try:
                # Stop the activity (implementation-specific)
                await self._cleanup()
                
                # Transition to stopped state
                self.state = ActivityState.STOPPED
                
                # Publish activity stopped event
                await self.publish(ActivityStoppedEvent(
                    producer_name=self.name,
                    activity=self.ACTIVITY_NAME,
                    reason=reason
                ))
                
                self.logger.info(f"Activity {self.ACTIVITY_NAME} stopped")
                
            except Exception as e:
                self.logger.error(f"Error stopping activity: {e}")
                self.state = ActivityState.ERROR
                raise
    
    @abstractmethod
    async def _initialize(self) -> None:
        """
        Initialize the activity (implementation-specific).
        
        This method is called during activity start and should perform
        any setup required for the activity.
        """
        pass
    
    async def _pause(self) -> None:
        """
        Pause the activity (implementation-specific).
        
        This method is called during activity pause and should perform
        any actions required to pause the activity.
        """
        # Default implementation does nothing
        pass
    
    async def _resume(self) -> None:
        """
        Resume the activity (implementation-specific).
        
        This method is called during activity resume and should perform
        any actions required to resume the activity.
        """
        # Default implementation does nothing
        pass
    
    @abstractmethod
    async def _cleanup(self) -> None:
        """
        Clean up the activity (implementation-specific).
        
        This method is called during activity stop and should perform
        any cleanup required for the activity.
        """
        pass 