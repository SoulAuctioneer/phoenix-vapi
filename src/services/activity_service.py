from typing import Dict, Any, Optional, Type, List, Tuple
from enum import Enum
from services.service import BaseService
from services.location_service import LocationService
from services.sensor_service import SensorService
from services.haptic_service import HapticService
from services.accelerometer_service import AccelerometerService
from activities.conversation_activity import ConversationActivity
from activities.sleep_activity import SleepActivity
from activities.hide_seek_activity import HideSeekActivity
from activities.scavenger_hunt_activity import ScavengerHuntActivity
from activities.squealing_activity import SquealingActivity
from activities.move_activity import MoveActivity
from activities.call_activity import CallActivity
from activities.play_music_activity import PlayMusicActivity
import asyncio
from config import ASSISTANT_CONFIG_FIRST_CONTACT

# TODO: Should this be StrEnum?
class ActivityType(Enum):
    """Types of activities the device can be in"""
    FIRST_CONTACT = "first_contact"
    CONVERSATION = "conversation"
    HIDE_SEEK = "hide_seek"
    SCAVENGER_HUNT = "scavenger_hunt"
    SQUEALING = "squealing"
    CUDDLE = "cuddle"
    SLEEP = "sleep"
    MOVE = "move"
    CALL = "call"
    PLAY_MUSIC = "play_music"
# Map activities to their required supporting services, activity-specific service, and optional start/stop sounds/TTS
# Format: (list of supporting services, activity service name if any, start_sound, stop_sound, start_tts_text, stop_tts_text)
ACTIVITY_REQUIREMENTS: Dict[ActivityType, Tuple[List[str], Optional[str], Optional[str], Optional[str], Optional[str], Optional[str]]] = {
    ActivityType.FIRST_CONTACT: ([], 'conversation', None, None, None, None),
    ActivityType.CONVERSATION: ([], 'conversation', "YAWN2", None, None, None),
    ActivityType.MOVE: (['accelerometer'], 'move', "YAY_PLAY", None, None, None),
    ActivityType.HIDE_SEEK: (['location'], 'hide_seek', None, None, None, None),
    ActivityType.SCAVENGER_HUNT: (['location'], 'scavenger_hunt', None, None, "Let's start the scavenger hunt", "We finished the scavenger hunt"),
    ActivityType.SQUEALING: (['accelerometer'], 'squealing', None, None, None, None),
    ActivityType.CUDDLE: (['haptic', 'sensor'], 'cuddle', None, None, None, None),
    ActivityType.SLEEP: ([], 'sleep', "YAWN", None, None, None),
    ActivityType.CALL: ([], 'call', None, None, None, None),
    ActivityType.PLAY_MUSIC: ([], 'play_music', None, None, None, None)
}

class ActivityService(BaseService):
    """
    Service that manages the current activity state and transitions.
    Coordinates starting and stopping activities based on events from other services.
    Also manages the lifecycle of activity-specific services.
    """
    def __init__(self, service_manager):
        super().__init__(service_manager)
        self.current_activity: Optional[ActivityType] = None
        # Define available activity services
        # TODO: Should we switch to the ActivityType enum for the keys here?
        self.activity_services = {
            'location': LocationService,
            'sensor': SensorService,
            'haptic': HapticService,
            'accelerometer': AccelerometerService,
            'conversation': ConversationActivity,
            'move': MoveActivity,
            'hide_seek': HideSeekActivity,
            'scavenger_hunt': ScavengerHuntActivity,
            'squealing': SquealingActivity,
            'call': CallActivity,
            'sleep': SleepActivity,
            'play_music': PlayMusicActivity,
        }
        self.initialized_services: Dict[str, BaseService] = {}
        self.active_services: Dict[str, BaseService] = {}
        self._transition_queue = asyncio.Queue()
        self._transition_task = None
        self.is_transitioning = False # Flag to track ongoing transitions
        
    async def start(self):
        """Start the activity service. Initial activity will be started after receiving startup completed event."""
        await super().start()
        # Start the transition processing task
        self._transition_task = asyncio.create_task(self._process_transitions())
        
    async def stop(self):
        """Stop the activity service and current activity"""
        # Cancel the transition processing task
        if self._transition_task:
            self._transition_task.cancel()
            try:
                await self._transition_task
            except asyncio.CancelledError:
                pass
            
        if self.current_activity:
            await self._stop_activity(self.current_activity)
        await super().stop()
        
    async def _process_transitions(self):
        """Process activity transitions from the queue"""
        while True:
            try:
                # Wait for the next transition
                activity, kwargs = await self._transition_queue.get()
                self.is_transitioning = True # Set flag before starting
                
                try:
                    await self._start_activity(activity, **kwargs)
                except Exception as e:
                    self.logger.error(f"Error processing activity transition: {e}")
                finally:
                    # Mark the transition as done and clear the flag
                    self.is_transitioning = False
                    self._transition_queue.task_done()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in transition processing loop: {e}")
                await asyncio.sleep(0.1)  # Avoid tight loop on persistent errors
                
    async def _queue_transition(self, activity: ActivityType, **kwargs):
        """Queue an activity transition
        
        Args:
            activity: The activity to transition to
        """
        await self._transition_queue.put((activity, kwargs))
        
    async def _ensure_services(self, required_services: list[str], **kwargs) -> bool:
        """Ensure all required services are initialized and running
        
        Args:
            required_services: List of service names that need to be running
            **kwargs: Additional arguments to pass to the activity's start method
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
                    service = service_class(self._service_manager)
                    self.initialized_services[service_name] = service
                else:
                    self.logger.debug(f"Service {service_name} already initialized")
                    
                # Start the service
                service = self.initialized_services[service_name]
                self.logger.info(f"Starting service: {service_name}")
                try:
                    await self._service_manager.start_service(service_name, service, **kwargs)
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
                try:
                    await self._service_manager.stop_service(service_name)
                    self.logger.info(f"Successfully stopped service: {service_name}")
                except Exception as e:
                     self.logger.error(f"Failed to stop service {service_name}: {e}", exc_info=True)
                # Always remove from active services, even if stop failed, but check if it still exists
                if service_name in self.active_services:
                    del self.active_services[service_name]
        
    async def _start_activity(self, activity: ActivityType, **kwargs):
        """Start a new activity, stopping the current activity if one is running
        
        Args:
            activity: The activity to start
            **kwargs: Additional arguments to pass to the activity's start method
        """
        if activity == self.current_activity:
            self.logger.debug(f"Activity {activity.name} already active")
            return

        # Get required supporting services and activity service
        requirements = ACTIVITY_REQUIREMENTS[activity]
        supporting_services, activity_service_name, start_sound, _, start_tts, _ = requirements
        
        # Play start sound if defined
        if start_sound:
            self.logger.info(f"Activity {activity.name} starting, playing start sound: {start_sound}")
            await self.publish({
                "type": "play_sound",
                "effect_name": start_sound,
                # TODO: Change back when not in public!
                # "volume": 1.0 
            })
            
        # Speak start text if defined
        if start_tts:
            self.logger.info(f"Activity {activity.name} starting, speaking: {start_tts}")
            await self.publish({
                "type": "speak_audio",
                "text": start_tts
            })
            
        # If we have a current activity, stop it first
        if self.current_activity:
            await self._stop_activity(self.current_activity)
            
        # Ensure supporting services are running
        if not await self._ensure_services(supporting_services):
            self.logger.error(f"Failed to start {activity.name} - required supporting services could not be started")
            return
            
        self.logger.info(f"Starting activity: {activity.name}")
        
        # Start activity-specific service if needed
        if activity_service_name:
            if not await self._ensure_services([activity_service_name]):
                self.logger.error(f"Failed to start {activity.name} - activity service could not be started")
                return
            
        # Any additional setup for the activity
        if activity in [ActivityType.CONVERSATION, ActivityType.FIRST_CONTACT]:
            conversation_activity = self.active_services.get('conversation')
            await conversation_activity.start_conversation(**kwargs)
                
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
        
        # Play stop sound if defined (before stopping services)
        requirements = ACTIVITY_REQUIREMENTS[activity]
        supporting_services, activity_service_name, _, stop_sound, _, stop_tts = requirements
        
        if stop_sound:
            self.logger.info(f"Activity {activity.name} stopping, playing stop sound: {stop_sound}")
            await self.publish({
                "type": "play_sound",
                "effect_name": stop_sound
            })
            
        # Speak stop text if defined
        if stop_tts:
            self.logger.info(f"Activity {activity.name} stopping, speaking: {stop_tts}")
            await self.publish({
                "type": "speak_audio",
                "text": stop_tts
            })
            
        # Get current activity's services
        services_to_stop_list = supporting_services.copy()  # Make a copy to avoid modifying the original
        if activity_service_name:
            services_to_stop_list.append(activity_service_name)
            
        # Stop all services for this activity
        self.logger.info(f"Cleaning up supporting services for activity {activity.name}. Services to stop: {services_to_stop_list}")
        await self._cleanup_services(services_to_stop_list)
            
        # Clear current activity before publishing event
        self.current_activity = None
        
        # Publish activity stopped event without waiting to prevent deadlocks.
        # An event handler should not block waiting for another event to be fully
        # processed, as this can cause the entire event loop to hang if other
        # services are also waiting.
        asyncio.create_task(self.publish({
            "type": "activity_stopped",
            "activity": activity.name
        }))
        
        # Default behavior: If no other transition is queued or running, go to SLEEP
        if not self.is_transitioning and self._transition_queue.empty():
            self.logger.info(f"Activity {activity.name} ended, transitioning to default SLEEP activity.")
            await self._queue_transition(ActivityType.SLEEP)
        else:
            self.logger.info(f"Activity {activity.name} ended, but transition is running or queue is not empty. Not transitioning to SLEEP. Is transition running: {self.is_transitioning}, is queue empty: {self._transition_queue.empty()}")
        
    async def handle_event(self, event: Dict[str, Any]):
        """Handle events from other services"""
        event_type = event.get("type")
        
        if event_type == "application_startup_completed":
            # Start initial sleep activity once all core services are ready
            await self._queue_transition(ActivityType.SLEEP)
            
        elif event_type == "intent_detected":
            intent = event.get("intent")
            
            # TODO: Should we check that this intent is an ActivityType?
            # Then we can simplify to:
            # await self._queue_transition(intent)
            # ...special handling for 'call'
            
            # Handle activity-related intents
            if intent == "conversation":
                # Start conversation activity
                await self._queue_transition(ActivityType.CONVERSATION)
                
            elif intent == "hide_and_seek":
                # TODO: We're temporarily repurposing "hide_and_seek" -> scavenger hunt.
                # Start scavenger hunt activity
                await self._queue_transition(ActivityType.SCAVENGER_HUNT)
                # Start hide and seek activity
                # await self._queue_transition(ActivityType.HIDE_SEEK)

            # TODO: This needs to be added to the Pico model.
            elif intent == "scavenger_hunt":
                # Start scavenger hunt activity
                await self._queue_transition(ActivityType.SCAVENGER_HUNT)
            
            elif intent == "first_contact":
                # Start first contact activity
                await self._queue_transition(ActivityType.FIRST_CONTACT, assistant_config=ASSISTANT_CONFIG_FIRST_CONTACT, include_memories=False)

            elif intent == "squealing":
                # Start squealing activity
                await self._queue_transition(ActivityType.SQUEALING)

            elif intent == "cuddle":
                # Start cuddle activity
                await self._queue_transition(ActivityType.CUDDLE)

            elif intent == "move":
                # Start move activity
                await self._queue_transition(ActivityType.MOVE)
                
            elif intent == "sleep":
                # Return to sleep activity
                await self._queue_transition(ActivityType.SLEEP)
                
            elif intent == "call":
                # Start call activity, passing the contact name
                slots = event.get("slots")
                if slots and "contact" in slots:
                    contact = slots["contact"]
                    await self.publish({
                        "type": "speak_audio",
                        "text": f"Okay let's phone {contact}"
                    })
                    await self._queue_transition(ActivityType.CALL, contact=contact)
                else:
                    self.logger.error("No contact name provided for call activity")

            elif intent == "play_music":
                await self._queue_transition(ActivityType.PLAY_MUSIC)
            
            # TODO: Handle "shut_down" intent
            else:
                self.logger.error(f"Can't handle 'intent_detected' intent with value: {intent}.")

        elif event_type == "activity_ended":
            activity_name = event.get("activity")
            if not activity_name:
                self.logger.error("Received 'activity_ended' event without 'activity' name.")
                return

            try:
                activity_to_stop = ActivityType(activity_name.lower())
                # Check if the activity that ended is the current active one and no transition is running
                if self.current_activity == activity_to_stop and not self.is_transitioning:
                    self.logger.info(f"'{activity_name}' activity ended. Stopping it now.")
                    await self._stop_activity(activity_to_stop)
                elif self.current_activity != activity_to_stop:
                    self.logger.warning(f"Received 'activity_ended' for '{activity_name}', but current activity is '{self.current_activity.name}'. Ignoring.")
                else: # is_transitioning
                    self.logger.info(f"Received 'activity_ended' for '{activity_name}' during a transition. Ignoring.")
            except ValueError:
                self.logger.error(f"Received 'activity_ended' for an unknown activity type: '{activity_name}'.")

        elif event_type == "conversation_ended":
            # A conversation has finished. Stop the conversation activity.
            if self.current_activity == ActivityType.CONVERSATION and not self.is_transitioning:
                await self._stop_activity(ActivityType.CONVERSATION)
        
        elif event_type == "scavenger_hunt_won":
            if self.current_activity == ActivityType.SCAVENGER_HUNT and not self.is_transitioning:
                await self._stop_activity(ActivityType.SCAVENGER_HUNT)
        
        elif event_type == "squealing_ended":
            self.logger.info("Ending squealing activity")
            if self.current_activity == ActivityType.SQUEALING and not self.is_transitioning:
                await self._stop_activity(ActivityType.SQUEALING)

                
        elif event_type == "hide_seek_won":
            # TODO: When hide and seek is won, transition to special conversation
            # await self._queue_transition(ActivityType.CONVERSATION)
            pass

        elif event_type == "touch_stroke_intensity":
            intensity = event.get("intensity", 0.0)
            # Start cuddle activity when being petted, if not in conversation
            if intensity > 0 and self.current_activity not in [ActivityType.CONVERSATION, ActivityType.CUDDLE]:
                await self._queue_transition(ActivityType.CUDDLE)
            # Return to sleep when petting stops
            elif intensity == 0 and self.current_activity == ActivityType.CUDDLE:
                await self._queue_transition(ActivityType.SLEEP)

        elif event_type == "start_sensing_phoenix_distance":
            # Start the location service to sense the distance to the Phoenix
            await self._ensure_services(['location'])

        elif event_type == "stop_sensing_phoenix_distance":
            # Stop the location service only if it's not required by the current activity
            # This check prevents stopping location if HIDE_SEEK is active.
            current_reqs = ACTIVITY_REQUIREMENTS.get(self.current_activity, ([], None, None, None, None, None))
            if 'location' not in current_reqs[0]:
                await self._cleanup_services(['location'])
            else:
                self.logger.debug("Location service required by current activity, not stopping.")

        # Handle PSTN call events published by CallActivity
        elif event_type in ["pstn_call_initiated", "pstn_call_ended", "pstn_call_error", "pstn_call_already_ended", "pstn_call_not_found"]:
            self.logger.info(f"PSTN Call Event: {event_type} - SID: {event.get('sid')}, Details: {event.get('reason') or event.get('status')}")
            # Optionally add specific logic here based on call events
            if event_type == "pstn_call_error":
                # If a call fails immediately, maybe transition back to sleep?
                if self.current_activity == ActivityType.CALL:
                    self.logger.error("PSTN call error detected, stopping CALL activity.")
                    await self._stop_activity(ActivityType.CALL)
        
        elif event_type == "pstn_call_completed_remotely":
            self.logger.info(f"PSTN call completed remotely (SID: {event.get('sid')}, Status: {event.get('status')}). Stopping CALL activity.")
            if self.current_activity == ActivityType.CALL:
                # The polling task in CallActivity already cleared its SID
                # We just need to stop the activity here, which will trigger transition to SLEEP
                await self._stop_activity(ActivityType.CALL)
            else:
                self.logger.debug(f"Received pstn_call_completed_remotely but current activity is {self.current_activity}. Ignoring.")
        
        else:
            self.logger.debug(f"Unknown event type: {event_type}")
