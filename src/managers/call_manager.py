import daily
import threading
import numpy as np
import json
import logging
import asyncio
import time
import requests
from enum import Enum
from managers.audio_manager import AudioManager
from config import CallConfig

class CallState(Enum):
    """Possible states for a call, matching Daily's API states"""
    INITIALIZED = "initialized"  # Initial state, ready to start a call
    JOINING = "joining"         # In process of joining
    JOINED = "joined"          # Successfully joined
    LEAVING = "leaving"        # In process of leaving
    LEFT = "left"              # Successfully left the call
    ERROR = "error"            # Error state (our addition)

    @property
    def is_active(self) -> bool:
        """Whether the call is in an active state"""
        return self in (CallState.JOINING, CallState.JOINED)
    
    @property
    def can_receive_audio(self) -> bool:
        """Whether the call can receive audio in this state"""
        return self == CallState.JOINED
        
    @property
    def can_start_new_call(self) -> bool:
        """Whether a new call can be started in this state"""
        return self in (CallState.INITIALIZED, CallState.LEFT)
        
    @property
    def needs_cleanup(self) -> bool:
        """Whether this state requires cleanup of call resources"""
        return self in (CallState.LEFT, CallState.ERROR)

    @property
    def is_terminal_state(self) -> bool:
        """Whether this is a terminal state that requires no further action"""
        return self in (CallState.INITIALIZED, CallState.LEFT, CallState.ERROR)

class CallStateManager:
    """Manages call state transitions and notifications"""
    def __init__(self, call_manager):
        self._state = CallState.INITIALIZED
        self._state_lock = asyncio.Lock()
        self._call_manager = call_manager
        self._state_handlers = {}
        self._participants = {}
        self._volume = CallConfig.Audio.DEFAULT_VOLUME
        self._start_event = asyncio.Event()
        
    @property
    def state(self) -> CallState:
        """Current call state"""
        return self._state
        
    @property
    def start_event(self) -> asyncio.Event:
        """Event used for synchronizing call start"""
        return self._start_event
        
    def register_handler(self, state: CallState, handler):
        """Register a handler for a specific state"""
        self._state_handlers[state] = handler
        
    async def transition_to(self, new_state: CallState):
        """Transition to a new state and notify listeners"""
        if not self._can_transition_to(new_state):
            logging.warning(f"Invalid state transition from {self._state} to {new_state}")
            return
            
        async with self._state_lock:
            old_state = self._state
            self._state = new_state
            
            # Log the transition
            logging.info(f"Call state transition: {old_state.value} -> {new_state.value}")
            
            # Publish event if we have a manager
            if self._call_manager.manager:
                await self._call_manager.manager.publish({
                    "type": "call_state",
                    "old_state": old_state.value,
                    "new_state": new_state.value,
                    "state": self._get_event_state(new_state)
                })
            
            # Execute state handler if one exists
            if new_state in self._state_handlers:
                try:
                    await self._state_handlers[new_state]()
                except Exception as e:
                    logging.error(f"Error in state handler for {new_state.value}: {e}")
                    if new_state != CallState.ERROR:  # Prevent infinite loop
                        await self.transition_to(CallState.ERROR)
    
    def _get_event_state(self, state: CallState) -> str:
        """Get the event state string for a given state"""
        if state == CallState.JOINED:
            return "started"
        elif state == CallState.LEFT:
            return "ended"
        return state.value
    
    def _can_transition_to(self, new_state: CallState) -> bool:
        """Check if transition to new state is valid"""
        valid_transitions = {
            CallState.INITIALIZED: [CallState.JOINING, CallState.ERROR],
            CallState.JOINING: [CallState.JOINED, CallState.ERROR, CallState.LEFT],
            CallState.JOINED: [CallState.LEAVING, CallState.ERROR],
            CallState.LEAVING: [CallState.LEFT, CallState.ERROR],
            CallState.LEFT: [CallState.INITIALIZED, CallState.ERROR, CallState.JOINING],  # Allow direct transition to JOINING
            CallState.ERROR: [CallState.INITIALIZED]  # Allow recovery from error state
        }
        
        valid_states = valid_transitions.get(self._state, [])
        if new_state not in valid_states:
            logging.warning(
                f"Invalid state transition attempted: {self._state.value} -> {new_state.value}. "
                f"Valid transitions are: {[s.value for s in valid_states]}"
            )
        return new_state in valid_states
    
    def reset(self):
        """Reset state to initial values"""
        old_state = self._state
        self._start_event.clear()
        self._participants.clear()
        self._volume = CallConfig.Audio.DEFAULT_VOLUME
        self._state = CallState.INITIALIZED  # Reset to initialized state
        logging.info(f"Reset state from {old_state} to {self._state}")
    
    def is_in_state(self, *states: CallState) -> bool:
        """Check if current state is one of the given states"""
        return self._state in states
    
    def set_volume(self, volume: float):
        """Set the volume level (0.0 to 1.0)"""
        self._volume = max(0.0, min(1.0, volume))
        
    def get_volume(self) -> float:
        """Get the current volume level"""
        return self._volume
        
    def update_participant(self, participant_id: str, participant_data: dict):
        """Update or add a participant"""
        self._participants[participant_id] = participant_data
        
    def remove_participant(self, participant_id: str):
        """Remove a participant"""
        self._participants.pop(participant_id, None)
            
    def get_participants(self) -> dict:
        """Get all participants"""
        return self._participants.copy()


def thread_safe_event(func):
    def wrapper(self, *args, **kwargs):
        self.loop.call_soon_threadsafe(
            lambda: asyncio.create_task(func(self, *args, **kwargs))
        )
    return wrapper

class CallEventHandler(daily.EventHandler):
    """Event handler for Daily calls"""
    def __init__(self, call):
        super().__init__()
        self.call = call
        self.loop = asyncio.get_event_loop()

    @thread_safe_event
    async def on_call_state_updated(self, state):
        await self.call.handle_call_state_updated(state)

    @thread_safe_event
    async def on_participant_left(self, participant, reason):
        await self.call.handle_participant_left(participant, reason)

    @thread_safe_event
    async def on_participant_joined(self, participant):
        await self.call.handle_participant_joined(participant)

    @thread_safe_event
    async def on_participant_updated(self, participant):
        await self.call.handle_participant_updated(participant)

    @thread_safe_event
    async def on_inputs_updated(self, input_settings):
        await self.call.handle_inputs_updated(input_settings)

    @thread_safe_event
    async def on_joined(self, data, error):
        await self.call.handle_joined(data, error)

    @thread_safe_event
    async def on_app_message(self, message, sender):
        await self.call.handle_app_message(message, sender)


class CallManager:
    """Handles Daily call functionality and Vapi API integration"""
    
    def __init__(self, *, api_key, api_url=CallConfig.Vapi.DEFAULT_API_URL, manager=None):
        # Public attributes
        self.api_key = api_key
        self.api_url = api_url
        self.manager = manager
        self.state_manager = CallStateManager(self)
        self.audio_manager = None

        # Private attributes - using single underscore
        self._mic_device = None
        self._speaker_device = None
        self._audio_consumer = None
        self._audio_producer = None
        self._event_handler = None
        self._call_client = None
        self._start_event = asyncio.Event()
        self._initialized = False

    @classmethod
    async def create(cls, *, api_key, api_url=CallConfig.Vapi.DEFAULT_API_URL, manager=None):
        """Factory method to create and initialize a CallManager instance"""
        instance = cls(api_key=api_key, api_url=api_url, manager=manager)
        await instance.initialize()
        return instance

    async def initialize(self):
        """Initialize the CallManager asynchronously"""
        if self._initialized:
            return
            
        try:
            # Initialize audio manager first
            self.audio_manager = AudioManager.get_instance()
            
            # Then initialize Daily runtime
            await self._initialize_daily_runtime()
            
            # Then create devices
            await self._initialize_devices()
            
            # Finally initialize call client
            await self._initialize_call_client()
            
            self._initialized = True
        except Exception as e:
            logging.error(f"Failed to initialize CallManager: {e}")
            await self.cleanup()
            raise

    async def _initialize_devices(self):
        """Initialize Daily devices"""
        try:
            # Create base Daily devices - these persist for the life of the class
            self._mic_device = daily.Daily.create_microphone_device(
                CallConfig.Daily.MIC_DEVICE_ID,
                sample_rate=CallConfig.Audio.SAMPLE_RATE,
                channels=CallConfig.Audio.NUM_CHANNELS
            )
            self._speaker_device = daily.Daily.create_speaker_device(
                CallConfig.Daily.SPEAKER_DEVICE_ID,
                sample_rate=CallConfig.Audio.SAMPLE_RATE,
                channels=CallConfig.Audio.NUM_CHANNELS
            )
            daily.Daily.select_speaker_device(CallConfig.Daily.SPEAKER_DEVICE_ID)
        except Exception as e:
            logging.error(f"Failed to initialize Daily devices: {e}")
            raise

    async def _initialize_call_audio(self):
        """Initialize audio components needed for a specific call"""
        try:
            # Create and start audio tasks
            self._receive_bot_audio_task = asyncio.create_task(self._receive_bot_audio())
            self._send_user_audio_task = asyncio.create_task(self._send_user_audio())
            
            # Register with audio manager for this call
            self._audio_consumer = self.audio_manager.add_consumer(
                self._handle_input_audio,
                chunk_size=CallConfig.Audio.CHUNK_SIZE
            )
            self._audio_producer = self.audio_manager.add_producer(
                "daily_call",
                chunk_size=CallConfig.Audio.CHUNK_SIZE
            )
            # Clear any existing data in the buffer
            self._audio_producer.buffer.clear()
            
            # Set initial volume for this call
            self.audio_manager.set_producer_volume("daily_call", self.state_manager.get_volume())
        except Exception as e:
            logging.error(f"Failed to initialize call audio: {e}")
            raise

    async def _initialize_daily_runtime(self):
        """Initialize the Daily runtime"""
        try:
            daily.Daily.init()
            logging.info("Daily runtime initialized")
        except Exception as e:
            logging.error(f"Failed to initialize Daily runtime: {e}")
            raise

    async def _initialize_call_client(self):
        """Initialize the Daily call client and its configuration"""
        # Release any existing client first
        if hasattr(self, '_call_client') and self._call_client:
            self._call_client.release()
            
        self._event_handler = CallEventHandler(self)
        self._call_client = daily.CallClient(event_handler=self._event_handler)
        
        self._call_client.update_inputs({
            "camera": False,
            "microphone": {
                "isEnabled": True,
                "settings": {
                    "deviceId": CallConfig.Daily.MIC_DEVICE_ID,
                    "customConstraints": CallConfig.Daily.MIC_CONSTRAINTS
                }
            }
        })
        
        self._call_client.update_subscription_profiles(CallConfig.Daily.SUBSCRIPTION_PROFILES)
        
        # Initialize participants
        participants = dict(self._call_client.participants())
        if "local" in participants:
            del participants["local"]
        for pid, pdata in participants.items():
            self.state_manager.update_participant(pid, pdata)
        
        # Register state handlers
        self.state_manager.register_handler(CallState.ERROR, self._handle_error_state)
        self.state_manager.register_handler(CallState.INITIALIZED, self._handle_initialized_state)
        self.state_manager.register_handler(CallState.JOINING, self._handle_joining_state)
        self.state_manager.register_handler(CallState.JOINED, self._handle_joined_state)
        self.state_manager.register_handler(CallState.LEFT, self._handle_left_state)

    async def _handle_error_state(self):
        """Handle error state"""
        self.state_manager.start_event.set()
        await self.leave()

    async def _handle_initialized_state(self):
        """Handle initialized state - ready for new call"""
        # Clean up any remaining resources
        await self._cleanup_call_audio()
        self.state_manager.start_event.clear()

    async def _handle_left_state(self):
        """Handle left state - cleanup and prepare for potential new call"""
        try:
            # Clean up call-specific resources
            await self._cleanup_call_audio()
            
            # Small delay to ensure all Daily events are processed
            await asyncio.sleep(0.1)
            
            # No need to transition to INITIALIZED - both states can start new calls
            logging.info("Call cleanup complete, ready for new call")
        except Exception as e:
            logging.error(f"Error in left state handler: {e}")
            await self.state_manager.transition_to(CallState.ERROR)

    async def _handle_joining_state(self):
        """Handle joining state - prepare for joining a call"""
        try:
            # Initialize timeout task attribute
            self._joining_timeout_task = None
            
            # Clear any existing audio setup
            await self._cleanup_call_audio()
            
            # Clear participants from any previous call
            self.state_manager.get_participants().clear()
            
            # Reset the start event
            self.state_manager.start_event.clear()
            
            if self.manager:
                await self.manager.publish({"type": "conversation_joining"})
                
            # Start a timeout task that will move us to error state if joining takes too long
            async def timeout_task():
                try:
                    await asyncio.sleep(10.0)  # 10 second timeout
                    if self.state_manager.state == CallState.JOINING:
                        logging.error("Timeout while waiting to join call")
                        await self.state_manager.transition_to(CallState.ERROR)
                except asyncio.CancelledError:
                    pass  # Task was cancelled because we joined successfully
                
            # Create and store the timeout task
            self._joining_timeout_task = asyncio.create_task(timeout_task())
                
        except Exception as e:
            logging.error(f"Error in joining state handler: {e}")
            await self.state_manager.transition_to(CallState.ERROR)

    async def _handle_joined_state(self):
        """Handle joined state"""
        try:
            # Cancel joining timeout if it exists
            if hasattr(self, '_joining_timeout_task') and self._joining_timeout_task:
                self._joining_timeout_task.cancel()
                
            # Initialize audio only after we're fully joined
            await self._initialize_call_audio()
            
            self.state_manager.start_event.set()
            if self.manager:
                await self.manager.publish({"type": "conversation_started"})
        except Exception as e:
            logging.error(f"Error in joined state handler: {e}")
            await self.state_manager.transition_to(CallState.ERROR)

    async def handle_call_state_updated(self, state):
        """Handle call state changes and publish events"""
        logging.info(f"Daily event: Call state updated: {state}")
        state_map = {
            "initialized": CallState.INITIALIZED,
            "joining": CallState.JOINING,
            "joined": CallState.JOINED,
            "leaving": CallState.LEAVING,
            "left": CallState.LEFT
        }
        
        if state in state_map:
            new_state = state_map[state]
            # Don't transition to INITIALIZED if we receive it from Daily
            # We manage this transition ourselves after cleanup
            if new_state == CallState.INITIALIZED:
                logging.debug("Ignoring INITIALIZED state from Daily - we manage this transition")
                return
                
            # Don't transition if we're already in that state
            if new_state == self.state_manager.state:
                logging.debug(f"Already in state {new_state.value}, ignoring transition")
                return
                
            await self.state_manager.transition_to(new_state)
        elif state == "error":
            await self.state_manager.transition_to(CallState.ERROR)

    async def handle_participant_left(self, participant, reason):
        """Handle participant leaving and publish event"""
        logging.info(f"Participant left: {participant}, reason: {reason}")
        if participant["id"] in self.state_manager.get_participants():
            self.state_manager.remove_participant(participant["id"])
            
            # If the leaving participant was the assistant, publish event and leave
            if ("userName" in participant["info"] and 
                participant["info"]["userName"] == "Vapi Speaker" and 
                not self.state_manager.state.is_terminal_state):
                await self.leave()

    async def handle_participant_joined(self, participant):
        """Handle participant joining"""
        logging.info(f"Participant joined: {participant}")
        self.state_manager.update_participant(participant["id"], participant)

    async def handle_participant_updated(self, participant):
        """Handle participant updates"""
        logging.debug(f"Participant updated: {participant}")
        self.state_manager.update_participant(participant["id"], participant)
        if self.is_playable_speaker(participant):
            self._call_client.send_app_message("playable")

    async def handle_inputs_updated(self, input_settings):
        """Handle input settings updates"""
        logging.debug(f"Inputs updated: {input_settings}")
        self.state_manager.start_event.set()
        self.maybe_start()

    async def handle_joined(self, data, error):
        """Handle call join result"""
        if error:
            logging.error(f"Unable to join call: {error}")
            await self.state_manager.transition_to(CallState.ERROR)
            return
            
        # Only transition if we're not already in JOINED state
        if not self.state_manager.is_in_state(CallState.JOINED):
            await self.state_manager.transition_to(CallState.JOINED)
        self.maybe_start()

    async def handle_app_message(self, message, sender):
        """Handle app messages"""
        logging.info(f"App message received: {message}, sender: {sender}")

    async def join(self, meeting_url):
        """Join a call with the given URL"""
        if not self.state_manager.state.can_start_new_call:
            logging.warning(f"Cannot join call - current state: {self.state_manager.state}")
            return
            
        logging.info(f"Joining call with URL: {meeting_url} (current state: {self.state_manager.state})")
        
        # Clear any previous state
        self.state_manager.start_event.clear()
        self.state_manager._participants.clear()
        
        # Now transition to JOINING
        logging.info("Transitioning to JOINING state...")
        await self.state_manager.transition_to(CallState.JOINING)
        
        # Only join if we successfully transitioned to JOINING
        if self.state_manager.state == CallState.JOINING:
            self._call_client.join(meeting_url, completion=self._event_handler.on_joined)
        else:
            logging.error(f"Failed to transition to JOINING state, current state: {self.state_manager.state}")
            await self.state_manager.transition_to(CallState.ERROR)

    async def leave(self):
        """Leave the call and clean up resources"""
        if self.state_manager.state.is_terminal_state:
            return
            
        # First transition to LEAVING state
        await self.state_manager.transition_to(CallState.LEAVING)
        
        # Immediately cleanup audio to prevent any more audio processing
        await self._cleanup_call_audio()
        
        # Then leave and release the call client
        # Store client locally so we can null the instance variable before calling leave
        client = self._call_client
        self._call_client = None
        
        # Leave the call first
        if client:
            try:
                client.leave()
                # Wait a tiny bit for the leave message to be sent
                await asyncio.sleep(0.05)
                # Then release the client
                client.release()
            except Exception as e:
                logging.warning(f"Error during client cleanup: {e}")
        
        # Wait for the left state update from Daily
        # If we don't receive it within a timeout, force the transition
        try:
            async with asyncio.timeout(2.0):  # 2 second timeout
                while not self.state_manager.state == CallState.LEFT:
                    await asyncio.sleep(0.1)
        except asyncio.TimeoutError:
            logging.warning("Timeout waiting for LEFT state from Daily, forcing transition")
            await self.state_manager.transition_to(CallState.LEFT)

    async def cleanup(self):
        """Clean up all resources"""
        try:
            # First leave any active call
            if not self.state_manager.state.is_terminal_state:
                await self.leave()
                
            # Then cleanup audio
            self._cleanup_audio_system()
            
            # Finally deinit Daily
            if hasattr(self, '_call_client') and self._call_client:
                self._call_client.release()
                self._call_client = None
                
            daily.Daily.deinit()
            logging.info("Daily runtime deinitialized")
            
            # Reset to initialized state
            await self.state_manager.transition_to(CallState.INITIALIZED)
        except Exception as e:
            logging.error(f"Error during CallManager cleanup: {e}")
            await self.state_manager.transition_to(CallState.ERROR)

    def send_app_message(self, message):
        """Send an application message to the assistant."""
        try:
            serialized_message = json.dumps(message)
            self._call_client.send_app_message(serialized_message)
        except Exception as e:
            print(f"Failed to send app message: {e}")

    def set_volume(self, volume):
        """Set the output volume (0.0 to 1.0)"""
        self.state_manager.set_volume(volume)
        self.audio_manager.set_producer_volume("daily_call", self.state_manager.get_volume())

    def get_volume(self):
        """Get the current output volume (0.0 to 1.0)"""
        return self.state_manager.get_volume()

    def maybe_start(self):
        """Check if we should set the start event"""
        if self.state_manager.state == CallState.ERROR:
            self.state_manager.start_event.set()

    def is_playable_speaker(self, participant):
        """Check if a participant is a playable speaker."""
        is_speaker = "userName" in participant["info"] and participant["info"]["userName"] == CallConfig.Vapi.SPEAKER_USERNAME
        mic = participant["media"]["microphone"]
        is_subscribed = mic["subscribed"] == "subscribed"
        is_playable = mic["state"] == "playable"
        return is_speaker and is_subscribed and is_playable

    async def _cleanup_call_audio(self):
        """Cleanup audio components specific to a call"""
        # Cancel audio tasks if they exist and are not None
        if hasattr(self, '_receive_bot_audio_task') and self._receive_bot_audio_task is not None:
            self._receive_bot_audio_task.cancel()
            try:
                await self._receive_bot_audio_task
            except asyncio.CancelledError:
                pass
            self._receive_bot_audio_task = None
            
        if hasattr(self, '_send_user_audio_task') and self._send_user_audio_task is not None:
            self._send_user_audio_task.cancel()
            try:
                await self._send_user_audio_task
            except asyncio.CancelledError:
                pass
            self._send_user_audio_task = None
            
        # Remove audio consumer and producer for this call
        if hasattr(self, '_audio_consumer') and self._audio_consumer is not None:
            self.audio_manager.remove_consumer(self._audio_consumer)
            self._audio_consumer = None
        
        if hasattr(self, '_audio_producer') and self._audio_producer is not None:
            self.audio_manager.remove_producer("daily_call")
            self._audio_producer = None

    def _cleanup_audio_system(self):
        """Cleanup the entire audio system"""
        # Clean up Daily devices
        if hasattr(self, '_mic_device'):
            self._mic_device = None
        if hasattr(self, '_speaker_device'):
            self._speaker_device = None

    def _create_vapi_call(self, payload):
        """Create a web call using the Vapi API"""
        url = f"{self.api_url}/call/web"
        headers = {
            'Authorization': 'Bearer ' + self.api_key,
            'Content-Type': 'application/json'
        }
        response = requests.post(url, headers=headers, json=payload)
        data = response.json()
        if response.status_code == 201:
            call_id = data.get('id')
            web_call_url = data.get('webCallUrl')
            return call_id, web_call_url
        else:
            raise Exception(f"Error: {data['message']}")

    async def start_call(
        self,
        *,
        assistant_id=None,
        assistant=None,
        assistant_overrides=None,
        squad_id=None,
        squad=None,
    ):
        """Start a new call with specified assistant or squad"""
        logging.info("Starting call...")

        # Start a new call
        if assistant_id:
            payload = {'assistantId': assistant_id, 'assistantOverrides': assistant_overrides}
        elif assistant:
            payload = {'assistant': assistant, 'assistantOverrides': assistant_overrides}
        elif squad_id:
            payload = {'squadId': squad_id}
        elif squad:
            payload = {'squad': squad}
        else:
            raise Exception("Error: No assistant specified.")

        logging.info("Creating web call...")
        call_id, web_call_url = self._create_vapi_call(payload)

        if not web_call_url:
            raise Exception("Error: Unable to create call.")

        logging.info('Joining call... ' + call_id)
        await self.join(web_call_url)

    def send_message(self, message):
        """Send a generic message to the assistant"""
        if not self.state_manager.state.is_active:
            raise Exception("Call not started. Please start the call first.")

        # Check message format
        if not isinstance(message, dict) or 'type' not in message:
            raise ValueError("Invalid message format.")

        try:
            self._call_client.send_app_message(message)
        except Exception as e:
            logging.error(f"Failed to send message: {e}")

    def add_message(self, role, content):
        """Send text messages with specific parameters"""
        message = {
            'type': 'add-message',
            'message': {
                'role': role,
                'content': content
            }
        }
        self.send_message(message)

    async def _receive_bot_audio(self):
        """Task for receiving bot audio from Daily"""
        try:
            await self.state_manager.start_event.wait()
            if self.state_manager.state == CallState.ERROR:
                logging.error("Unable to receive bot audio due to error state")
                return
                
            logging.info("Started receiving bot audio")
            while self.state_manager.state.can_receive_audio:
                try:
                    buffer = self._speaker_device.read_frames(CallConfig.Audio.CHUNK_SIZE)
                    if len(buffer) > 0 and self._audio_producer and self._audio_producer.active:
                        # Convert bytes to numpy array and send to audio manager
                        audio_np = np.frombuffer(buffer, dtype=np.int16)
                        self._audio_producer.buffer.put(audio_np)
                    await asyncio.sleep(0.01)  # Small sleep to prevent busy waiting
                except Exception as e:
                    if self.state_manager.state != CallState.ERROR:
                        logging.error(f"Error in receive audio task: {e}")
                    await asyncio.sleep(0.01)  # Ensure we don't busy-wait if state changes
        except asyncio.CancelledError:
            logging.info("Receive bot audio task cancelled")
            raise

    async def _send_user_audio(self):
        """Task for sending user audio to Daily"""
        try:
            await self.state_manager.start_event.wait()
            if self.state_manager.state == CallState.ERROR:
                logging.error("Unable to send user audio due to error state")
                return
                
            logging.info("Started sending user audio")
            while self.state_manager.state.can_receive_audio:
                try:
                    # Audio is handled by the audio manager consumer callback
                    await asyncio.sleep(0.1)  # Small sleep to prevent busy waiting
                except Exception as e:
                    if self.state_manager.state != CallState.ERROR:
                        logging.error(f"Error in send audio task: {e}")
                    await asyncio.sleep(0.01)  # Ensure we don't busy-wait if state changes
        except asyncio.CancelledError:
            logging.info("Send user audio task cancelled")
            raise

    def _handle_input_audio(self, audio_data: np.ndarray):
        """Handle input audio from audio manager"""
        # First check if we even have a mic device
        if not self._mic_device:
            return
            
        if not self.state_manager.state.can_receive_audio:
            # Don't log error during transitional states
            if self.state_manager.state not in (CallState.JOINING, CallState.LEAVING):
                logging.error("Unable to receive audio - call not in JOINED state")
            return
            
        try:
            self._mic_device.write_frames(audio_data.tobytes())
        except Exception as e:
            logging.error(f"Error writing to mic device: {e}")

