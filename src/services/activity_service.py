import logging
from typing import Dict, Any, Optional, Type, List, Tuple
from enum import Enum
from services.service import BaseService
from services.conversation_service import ConversationService
from services.location_service import LocationService
from services.sensor_service import SensorService
from services.haptic_service import HapticService
from services.sleep_activity import SleepActivity
from services.hide_seek_service import HideSeekService
import asyncio

class ActivityType(Enum):
    """Types of activities the device can be in"""
    CONVERSATION = "conversation"
    HIDE_SEEK = "hide_seek"
    CUDDLE = "cuddle"
    SLEEP = "sleep"

# Map activities to their required supporting services and activity-specific service
# Format: (list of supporting services, activity service name if any)
ACTIVITY_REQUIREMENTS: Dict[ActivityType, Tuple[List[str], Optional[str]]] = {
    ActivityType.CONVERSATION: ([], 'conversation'),  # ConversationService is the activity implementation
    ActivityType.HIDE_SEEK: (['location'], 'hide_seek'),  # Requires HideSeekService
    ActivityType.CUDDLE: (['haptic', 'sensor'], 'cuddle'),  # Requires CuddleService
    ActivityType.SLEEP: ([], 'sleep')  # Uses SleepActivity service
}

class ActivityService(BaseService):
    """
    Service that manages the current activity state and transitions.
    Coordinates starting and stopping activities based on events from other services.
    Also manages the lifecycle of activity-specific services.
    """
    def __init__(self, manager):
        super().__init__(manager)
        self.current_activity: Optional[ActivityType] = None
        # Define available activity services
        self.activity_services = {
            'conversation': ConversationService,
            'location': LocationService,
            'sensor': SensorService,
            'haptic': HapticService,
            'sleep': SleepActivity,
            'hide_seek': HideSeekService,
        }
        self.initialized_services: Dict[str, BaseService] = {}
        self.active_services: Dict[str, BaseService] = {}
        self._activity_lock = asyncio.Lock()  # Add lock for activity transitions
        
    async def start(self):
        """Start the activity service. Initial activity will be started after receiving startup completed event."""
        await super().start()
        
    async def stop(self):
        """Stop the activity service and current activity"""
        if self.current_activity:
            await self._stop_activity(self.current_activity)
        await super().stop()
        
    async def _ensure_services(self, required_services: list[str]) -> bool:
        """Ensure all required services are initialized and running
        
        Args:
            required_services: List of service names that need to be running
            
        Returns:
            bool: True if all services were successfully started
        """
        try:
            for service_name in required_services:
                self.logger.debug(f"Ensuring service {service_name} is running (active services: {list(self.active_services.keys())})")
                # Skip if service is already active
                if service_name in self.active_services:
                    self.logger.debug(f"Service {service_name} is already active")
                    continue
                    
                # Initialize service if needed
                if service_name not in self.initialized_services:
                    self.logger.info(f"Initializing service: {service_name}")
                    service_class = self.activity_services[service_name]
                    service = service_class(self.manager)
                    self.initialized_services[service_name] = service
                else:
                    self.logger.debug(f"Service {service_name} already initialized")
                    
                # Start the service
                service = self.initialized_services[service_name]
                self.logger.info(f"Starting service: {service_name}")
                try:
                    await self.manager.start_service(service_name, service)
                    self.active_services[service_name] = service
                    self.logger.info(f"Successfully started service: {service_name}")
                except Exception as e:
                    self.logger.error(f"Failed to start service {service_name}: {e}")
                    raise
                
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to start required services: {e}")
            return False
            
    async def _cleanup_services(self, services_to_stop: list[str]):
        """Stop services that are no longer needed
        
        Args:
            services_to_stop: List of service names to stop
        """
        for service_name in services_to_stop:
            if service_name in self.active_services:
                service = self.active_services[service_name]
                self.logger.info(f"Stopping service: {service_name}")
                await self.manager.stop_service(service_name)
                del self.active_services[service_name]
        
    async def _start_activity(self, activity: ActivityType, direct_transition: bool = False):
        """Start a new activity
        
        Args:
            activity: The activity to start
            direct_transition: If True, skip stopping current activity (used for direct transitions)
        """
        if activity == self.current_activity:
            self.logger.debug(f"Activity {activity.name} already active")
            return
            
        # Get required supporting services and activity service
        supporting_services, activity_service_name = ACTIVITY_REQUIREMENTS[activity]
        
        # Ensure supporting services are running
        if not await self._ensure_services(supporting_services):
            self.logger.error(f"Failed to start {activity.name} - required supporting services could not be started")
            return
            
        # Stop current activity if one is running and this isn't a direct transition
        if self.current_activity and not direct_transition:
            await self._stop_activity(self.current_activity)
            
        self.logger.info(f"Starting activity: {activity.name}")
        
        # Start activity-specific service if needed
        if activity_service_name:
            if not await self._ensure_services([activity_service_name]):
                self.logger.error(f"Failed to start {activity.name} - activity service could not be started")
                return
                
        self.current_activity = activity
        
        # Publish activity started event
        await self.publish({
            "type": "activity_started",
            "activity": activity.name
        })
        
    async def _stop_activity(self, activity: ActivityType):
        """Stop an activity
        
        Args:
            activity: The activity to stop
        """
        if activity != self.current_activity:
            return
            
        self.logger.info(f"Stopping activity: {activity.name}")
        
        # Get current activity's services
        supporting_services, activity_service_name = ACTIVITY_REQUIREMENTS[activity]
        current_services = supporting_services.copy()  # Make a copy to avoid modifying the original
        if activity_service_name:
            current_services.append(activity_service_name)
            
        # Get next activity's services (SLEEP if stopping non-SLEEP activity)
        next_activity = ActivityType.SLEEP if activity != ActivityType.SLEEP else None
        next_services = []
        if next_activity:
            next_supporting_services, next_activity_service = ACTIVITY_REQUIREMENTS[next_activity]
            next_services = next_supporting_services.copy()  # Make a copy to avoid modifying the original
            if next_activity_service:
                next_services.append(next_activity_service)
        
        # Calculate services to stop (current services not needed by next activity)
        services_to_stop = [s for s in current_services if s not in next_services]
        await self._cleanup_services(services_to_stop)
            
        # Clear current activity before publishing event
        self.current_activity = None
        
        # Publish activity stopped event
        await self.publish({
            "type": "activity_stopped",
            "activity": activity.name
        })
        
        # Start SLEEP activity if needed, using direct transition to avoid recursion
        if activity != ActivityType.SLEEP:
            await self._start_activity(ActivityType.SLEEP, direct_transition=True)
        
    async def handle_event(self, event: Dict[str, Any]):
        """Handle events from other services"""
        async with self._activity_lock:  # Lock at the event handler level
            event_type = event.get("type")
            
            if event_type == "application_startup_completed":
                # Start initial sleep activity once all core services are ready
                await self._start_activity(ActivityType.SLEEP)
                
            elif event_type == "intent_detected":
                intent = event.get("intent")
                
                # Handle activity-related intents
                if intent == "wake_up":
                    # Start conversation activity
                    await self._start_activity(ActivityType.CONVERSATION)
                    
                elif intent == "hide_and_seek":
                    # Start hide and seek activity
                    await self._start_activity(ActivityType.HIDE_SEEK)
                    
                elif intent == "cuddle":
                    await self._start_activity(ActivityType.CUDDLE)
                    
                elif intent == "sleep":
                    # Return to sleep activity
                    await self._start_activity(ActivityType.SLEEP)
                    
            elif event_type == "conversation_ended":
                # When conversation ends, return to sleep if that was the current activity
                if self.current_activity == ActivityType.CONVERSATION:
                    await self._stop_activity(ActivityType.CONVERSATION)
                    
            elif event_type == "touch_stroke_intensity":
                intensity = event.get("intensity", 0.0)
                # Start cuddle activity when being petted, if not in conversation
                if intensity > 0 and self.current_activity not in [ActivityType.CONVERSATION, ActivityType.CUDDLE]:
                    await self._start_activity(ActivityType.CUDDLE)
                # Return to sleep when petting stops
                elif intensity == 0 and self.current_activity == ActivityType.CUDDLE:
                    await self._stop_activity(ActivityType.CUDDLE)
