from textwrap import dedent
import daily
import threading
import numpy as np
import json
import logging
import asyncio
import time
import requests
from enum import Enum
import concurrent.futures
from managers.audio_manager import AudioManager
from config import ConversationConfig, FULL_ACTIVITIES_PROMPT, ACTIVITIES_CONFIG, ASSISTANT_CONTEXT_MEMORY_PROMPT, get_filter_logger
import queue
from utils.audio_processing import StreamingPitchShifter, STFTPITCHSHIFT_AVAILABLE

logger = get_filter_logger('conversation_manager')
logger.setLevel(logging.DEBUG)

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
    def __init__(self, conversation_manager):
        self._state = CallState.INITIALIZED
        self._state_lock = asyncio.Lock()
        self._conversation_manager = conversation_manager
        self._state_handlers = {}
        self._participants = {}
        self._volume = ConversationConfig.Audio.DEFAULT_VOLUME
        self._start_event = asyncio.Event()
        self._is_muted = False  # Track microphone mute state
        self._user_speaking = False  # Track if user is currently speaking
        self._assistant_speaking = False  # Track if assistant is currently speaking
        self._is_tool_led_effect_active = False # Flag for tool-initiated persistent LED effects
        
    @property
    def state(self) -> CallState:
        """Current call state"""
        return self._state
        
    @property
    def start_event(self) -> asyncio.Event:
        """Event used for synchronizing call start"""
        return self._start_event
        
    @property
    def is_muted(self) -> bool:
        """Get the current mute state"""
        return self._is_muted
        
    @property 
    def user_speaking(self) -> bool:
        """Whether the user is currently speaking"""
        return self._user_speaking
        
    @property
    def assistant_speaking(self) -> bool:
        """Whether the assistant is currently speaking"""
        return self._assistant_speaking
        
    def register_handler(self, state: CallState, handler):
        """Register a handler for a specific state"""
        self._state_handlers[state] = handler
        
    async def transition_to(self, new_state: CallState):
        """Transition to a new state and notify listeners"""
        if not self._can_transition_to(new_state):
            logger.warning(f"Invalid state transition from {self._state} to {new_state}")
            return
            
        async with self._state_lock:
            old_state = self._state
            self._state = new_state
            
            # Log the transition
            logger.info(f"Call state transition: {old_state.value} -> {new_state.value}")
            
            # Publish event
            await self._conversation_manager.publish_event_callback({
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
                    logger.error(f"Error in state handler for {new_state.value}: {e}")
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
            logger.warning(
                f"Invalid state transition attempted: {self._state.value} -> {new_state.value}. "
                f"Valid transitions are: {[s.value for s in valid_states]}"
            )
        return new_state in valid_states
    
    def reset(self):
        """Reset state to initial values"""
        old_state = self._state
        self._start_event.clear()
        self._participants.clear()
        self._volume = ConversationConfig.Audio.DEFAULT_VOLUME
        self._is_muted = False  # Reset mute state
        self._state = CallState.INITIALIZED  # Reset to initialized state
        logger.info(f"Reset state from {old_state} to {self._state}")
    
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

    def set_muted(self, muted: bool):
        """Set the mute state"""
        self._is_muted = muted

    async def set_speaking_state(self, role: str, is_speaking: bool):
        """Update the speaking state for the assistant and trigger LED effects"""
        role = role.lower()

        if role == "assistant":
            self._assistant_speaking = is_speaking
                
            # Toggle the mute state if the assistant is speaking (existing logic)
            if ConversationConfig.MUTE_WHEN_ASSISTANT_SPEAKING:
                self._is_muted = self._assistant_speaking

            if is_speaking: # Assistant starts speaking
                if not self._is_tool_led_effect_active:
                    # No tool-initiated LED effect was active, or it has finished its display period.
                    # Proceed with normal speaking LED.
                    asyncio.create_task(self._conversation_manager.publish_event_callback({
                        "type": "stop_led_effect"
                    }))
                    await asyncio.sleep(0.05) # Ensure stop command is processed
                    asyncio.create_task(self._conversation_manager.publish_event_callback({
                        "type": "start_led_effect",
                        "data": {"effect_name": "ROTATING_GREEN_YELLOW"}
                    }))
            else: # Assistant stops speaking
                if self._is_tool_led_effect_active:
                    # A tool-initiated LED effect was active. Let it play for this duration of speech.
                    # Set the flag to False so that next time the assistant stops/starts speaking,
                    # the normal speaking/idle LED logic resumes.
                    # NOTE: Moved to the user role's is_speaking state.
                    pass
                    # self._is_tool_led_effect_active = False
                    # DO NOT change the LED effect, let the tool's effect continue.
                else:
                    # If _is_tool_led_effect_active is False (meaning a tool effect just played during speech, 
                    # or no tool effect was active), show the idle effect.
                    asyncio.create_task(self._conversation_manager.publish_event_callback({
                        "type": "stop_led_effect"
                    }))
                    await asyncio.sleep(0.05) # Ensure stop command is processed
                    asyncio.create_task(self._conversation_manager.publish_event_callback({
                        "type": "start_led_effect",
                        "data": {"effect_name": "TWINKLING", "speed": 0.1}
                    }))
        
        # Note: User speaking state is still tracked (`self._user_speaking`)
        # but no longer triggers LED effects in this method.
        elif role == "user":
             self._user_speaking = is_speaking
             if is_speaking:
                # Hopefully this should give more time for the effect to play.
                self._is_tool_led_effect_active = False


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


class ConversationManager:
    """Handles Daily call functionality and Vapi API integration"""
    
    DEFAULT_PITCH_SEMITONES = 4.0

    def __init__(self, *, publish_event_callback=None, memory_manager=None):
        # Public attributes
        self.api_key = ConversationConfig.Vapi.API_KEY
        self.api_url = ConversationConfig.Vapi.DEFAULT_API_URL
        self.publish_event_callback = publish_event_callback
        self.state_manager = CallStateManager(self)
        self.audio_manager = None
        self.memory_manager = memory_manager
        self.loop = None

        # Private attributes - using single underscore
        self._mic_device = None
        self._speaker_device = None
        self._audio_consumer = None
        self._audio_producer = None
        self._event_handler = None
        self._call_client = None
        self._start_event = asyncio.Event()
        self._initialized = False
        self._pitch_shifter = None
        
        self._raw_audio_queue = queue.Queue(maxsize=10) # Intermediate queue
        self._audio_reader_thread = None
        self._pitch_shift_worker_task = None

        # Message queue for non-interrupting messages
        self._message_queue = asyncio.Queue()
        self._message_processor_task = None
        
        # Conversation history
        self.conversation = []

    @classmethod
    async def create(cls, *, publish_event_callback, memory_manager=None):
        """Factory method to create and initialize a ConversationManager instance"""
        instance = cls(publish_event_callback=publish_event_callback, memory_manager=memory_manager)
        await instance.initialize()
        return instance

    async def initialize(self):
        """Initialize the ConversationManager asynchronously"""
        if self._initialized:
            return
            
        try:
            self.loop = asyncio.get_running_loop()
            # Initialize audio manager first
            self.audio_manager = AudioManager.get_instance()
            
            # Register state handlers
            self.state_manager.register_handler(CallState.ERROR, self._handle_error_state)
            self.state_manager.register_handler(CallState.INITIALIZED, self._handle_initialized_state)
            self.state_manager.register_handler(CallState.JOINING, self._handle_joining_state)
            self.state_manager.register_handler(CallState.JOINED, self._handle_joined_state)
            self.state_manager.register_handler(CallState.LEFT, self._handle_left_state)
            
            # Start message processor task
            self._message_processor_task = asyncio.create_task(self._process_queued_messages())
            
            # Create the input thread first
            self._input_thread = threading.Thread(
                target=self._input_audio_thread,
                name="DailyInputAudioThread"
            )
            self._input_thread.daemon = True
            
            # Create the audio reader thread and pitch shifting worker
            self._audio_reader_thread = threading.Thread(
                target=self._audio_reader_loop,
                name="DailyAudioReaderThread"
            )
            self._audio_reader_thread.daemon = True
            self._pitch_shift_worker_task = asyncio.create_task(self._pitch_shift_worker())

            # Create minimal input buffer
            self._input_buffer = queue.Queue(maxsize=4)  # Minimal buffer size
            
            # Register with audio manager for this call
            self._audio_consumer = self.audio_manager.add_consumer(
                self._handle_input_audio,
                chunk_size=ConversationConfig.Audio.CHUNK_SIZE
            )
            self._audio_producer = self.audio_manager.add_producer(
                "daily_call",
                chunk_size=ConversationConfig.Audio.CHUNK_SIZE,
                buffer_size=ConversationConfig.Audio.BUFFER_SIZE,
                is_stream=True
            )
            # Clear any existing data in the buffer
            self._audio_producer.buffer.clear()
            
            # Set initial volume for this call
            self.audio_manager.set_producer_volume("daily_call", self.state_manager.get_volume())
            
            # Start the threads/tasks
            self._input_thread.start()
            self._audio_reader_thread.start()
            
            self._initialized = True
        except Exception as e:
            logger.error(f"Failed to initialize ConversationManager: {e}")
            await self.cleanup()
            raise

    async def _initialize_devices(self):
        """Initialize Daily devices"""
        try:
            # Small delay before creating devices
            await asyncio.sleep(0.1)
            
            # Create base Daily devices - these persist for the life of the class
            self._mic_device = daily.Daily.create_microphone_device(
                ConversationConfig.Daily.MIC_DEVICE_ID,
                sample_rate=ConversationConfig.Audio.SAMPLE_RATE,
                channels=ConversationConfig.Audio.NUM_CHANNELS
            )
            self._speaker_device = daily.Daily.create_speaker_device(
                ConversationConfig.Daily.SPEAKER_DEVICE_ID,
                sample_rate=ConversationConfig.Audio.SAMPLE_RATE,
                channels=ConversationConfig.Audio.NUM_CHANNELS
            )
            daily.Daily.select_speaker_device(ConversationConfig.Daily.SPEAKER_DEVICE_ID)
            
            # Small delay after device creation
            await asyncio.sleep(0.1)
        except Exception as e:
            logger.error(f"Failed to initialize Daily devices: {e}")
            raise

    async def _initialize_call_audio(self):
        """Initialize audio components needed for a specific call"""
        try:
            # Create the input thread first
            self._input_thread = threading.Thread(
                target=self._input_audio_thread,
                name="DailyInputAudioThread"
            )
            self._input_thread.daemon = True
            
            # Create the audio reader thread and pitch shifting worker
            self._audio_reader_thread = threading.Thread(
                target=self._audio_reader_loop,
                name="DailyAudioReaderThread"
            )
            self._audio_reader_thread.daemon = True
            self._pitch_shift_worker_task = asyncio.create_task(self._pitch_shift_worker())

            # Create minimal input buffer
            self._input_buffer = queue.Queue(maxsize=4)  # Minimal buffer size
            
            # Register with audio manager for this call
            self._audio_consumer = self.audio_manager.add_consumer(
                self._handle_input_audio,
                chunk_size=ConversationConfig.Audio.CHUNK_SIZE
            )
            self._audio_producer = self.audio_manager.add_producer(
                "daily_call",
                chunk_size=ConversationConfig.Audio.CHUNK_SIZE,
                buffer_size=ConversationConfig.Audio.BUFFER_SIZE,
                is_stream=True
            )
            # Clear any existing data in the buffer
            self._audio_producer.buffer.clear()
            
            # Set initial volume for this call
            self.audio_manager.set_producer_volume("daily_call", self.state_manager.get_volume())
            
            # Start the threads/tasks
            self._input_thread.start()
            self._audio_reader_thread.start()
            
        except Exception as e:
            logger.error(f"Failed to initialize call audio: {e}")
            raise

    async def _initialize_daily_runtime(self):
        """Initialize the Daily runtime"""
        try:
            # First ensure Daily is deinitialized
            try:
                daily.Daily.deinit()
                await asyncio.sleep(0.2)  # Small delay after deinit
            except Exception:
                pass  # Ignore errors from deinit attempt
                
            # Then initialize
            daily.Daily.init()
            await asyncio.sleep(0.1)  # Small delay after init
            logger.info("Daily runtime initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Daily runtime: {e}")
            raise

    async def _initialize_call_client(self):
        """Initialize the Daily call client and its configuration"""
        # Release any existing client first
        if hasattr(self, '_call_client') and self._call_client:
            self._call_client.release()
            
        self._event_handler = CallEventHandler(self)
        self._call_client = daily.CallClient(event_handler=self._event_handler)
        
        # Initialize with microphone enabled (unmuted)
        self._call_client.update_inputs({
            "camera": False,
            "microphone": {
                "isEnabled": True,  # Start unmuted
                "settings": {
                    "deviceId": ConversationConfig.Daily.MIC_DEVICE_ID,
                    "customConstraints": ConversationConfig.Daily.MIC_CONSTRAINTS
                }
            }
        })
        self.state_manager.set_muted(False)  # Initialize mute state
        
        self._call_client.update_subscription_profiles(ConversationConfig.Daily.SUBSCRIPTION_PROFILES)
        
        # Initialize participants
        participants = dict(self._call_client.participants())
        if "local" in participants:
            del participants["local"]
        for pid, pdata in participants.items():
            self.state_manager.update_participant(pid, pdata)

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
            
            # Extract and store memories from the conversation if available
            if self.memory_manager and self.conversation:
                logger.info("Extracting and storing memories from conversation")
                success = await self.memory_manager.extract_and_store_conversation_memories(self.conversation)
                if success:
                    logger.info("Successfully stored conversation memories")
                else:
                    logger.warning("No memories were stored")
            
            logger.info("Call cleanup complete, ready for new call")
        except Exception as e:
            logger.error(f"Error in left state handler: {e}")
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
            
            # Reset conversation history for new call
            self.conversation = []
            
            await self.publish_event_callback({"type": "conversation_joining"})
                
            # Start a timeout task that will move us to error state if joining takes too long
            async def timeout_task():
                try:
                    await asyncio.sleep(10.0)  # 10 second timeout
                    if self.state_manager.state == CallState.JOINING:
                        logger.error("Timeout while waiting to join call")
                        await self.state_manager.transition_to(CallState.ERROR)
                except asyncio.CancelledError:
                    pass  # Task was cancelled because we joined successfully
                
            # Create and store the timeout task
            self._joining_timeout_task = asyncio.create_task(timeout_task())
                
        except Exception as e:
            logger.error(f"Error in joining state handler: {e}")
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
            await self.publish_event_callback({"type": "conversation_started"})
        except Exception as e:
            logger.error(f"Error in joined state handler: {e}")
            await self.state_manager.transition_to(CallState.ERROR)

    async def handle_call_state_updated(self, state):
        """Handle call state changes and publish events"""
        logger.info(f"Daily event: Call state updated: {state}")
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
        logger.info(f"Participant left: {participant}, reason: {reason}")
        if participant["id"] in self.state_manager.get_participants():
            self.state_manager.remove_participant(participant["id"])
            
            # If the leaving participant was the assistant, publish event and leave
            if ("userName" in participant["info"] and 
                participant["info"]["userName"] == "Vapi Speaker" and 
                not self.state_manager.state.is_terminal_state):
                await self.leave()

    async def handle_participant_joined(self, participant):
        """Handle participant joining"""
        logger.info(f"Participant joined: {participant}")
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
            logger.error(f"Unable to join call: {error}")
            await self.state_manager.transition_to(CallState.ERROR)
            return
            
        # Only transition if we're not already in JOINED state
        if not self.state_manager.is_in_state(CallState.JOINED):
            await self.state_manager.transition_to(CallState.JOINED)
        self.maybe_start()

    async def _handle_tool_calls(self, tool_calls):
        """Handle tool calls from the assistant"""
        for tool_call in tool_calls:
            if tool_call.get('type') != 'function':
                logger.warning(f"Unknown tool call type: {tool_call.get('type')}")
                continue
                
            function = tool_call.get('function', {})
            name = function.get('name')
            arguments = function.get('arguments', {})
            tool_call_id = tool_call.get('toolCallId', None)
            
            logger.info(f"Handling tool call: {name} with arguments {arguments}")
            
            if name == 'play_special_effect':
                effect_name = arguments.get('effect_name', None)
                if effect_name:
                    self.state_manager._is_tool_led_effect_active = True
                    await self.publish_event_callback({
                        "type": "play_special_effect",
                        "effect_name": effect_name
                    })

            elif name == 'show_color':
                color = arguments.get('color', None)
                if color:
                    self.state_manager._is_tool_led_effect_active = True
                    await self.publish_event_callback({
                        "type": "start_led_effect",
                        "data": {
                            "effect_name": "rotating_color",
                            "color": color
                        }
                    })

            elif name == 'start_sensing_phoenix_distance':
                await self.publish_event_callback({
                    "type": "start_sensing_phoenix_distance"
                })

            elif name == 'stop_sensing_phoenix_distance':
                await self.publish_event_callback({
                    "type": "stop_sensing_phoenix_distance"
                })

            elif name == 'list_activities':
                # message = {
                #     "results": [
                #         {
                #             "toolCallId": tool_call_id,
                #             "result": FULL_ACTIVITIES_PROMPT
                #         }
                #     ]
                # }
                # TODO: Need to figure out how to send response back to assistant properly.
                #self._call_client.send_app_message(message)
                #self.send_message(FULL_ACTIVITIES_PROMPT)
                self.add_message("system", FULL_ACTIVITIES_PROMPT)

            elif name == 'start_activity':
                # await self.publish_event_callback({
                #     "type": "start_story"
                # })
                activity_key = arguments.get('activity_key', None)
                # message = {
                #     "results": [
                #         {
                #             "toolCallId": tool_call_id,
                #             "result": ACTIVITIES_CONFIG.get(activity_key)
                #         }
                #     ]
                # }
                #self._call_client.send_app_message(message)
                #self.send_message(message)
                activity_config = ACTIVITIES_CONFIG.get(activity_key)
                def parse_activity_config(config, indent=0):
                    """Convert activity config dictionary to plain text/markdown string"""
                    result = ""
                    indent_str = " " * indent
                    for key, value in config.items():
                        if isinstance(value, dict):
                            result += f"{indent_str}*{key}*:\n"
                            result += parse_activity_config(value, indent + 4)
                        else:
                            result += f"{indent_str}*{key}*: {value}\n"
                    return result

                activity_config_str = parse_activity_config(activity_config)
                if activity_config:
                    logger.info(f"Sending activity {activity_key} config: {activity_config_str}")
                    self.add_message("system", activity_config_str)
                else:
                    logger.warning(f"Unknown activity: {activity_key}")
            else:
                logger.warning(f"Unknown tool call: {name}")

    async def handle_app_message(self, message, sender):
        """Handle app messages"""

        # Log the raw message
        # logger.info(f"Received app message: {message}")

        # Convert string messages to dict if needed
        if isinstance(message, str):
            try:
                message = json.loads(message)
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse message as JSON: {message}")
                return
                
        # Extract message type
        msg_type = message.get("type", "")
        
        # Handle different message types
        if msg_type == "status-update":
            status = message.get("status", "")
            logger.info(f"Status update: {status}")
        elif msg_type == "speech-update":
            status = message.get("status", "")
            role = message.get("role", "")
            # Update speaking state based on status
            is_speaking = status == "started"

            await self.state_manager.set_speaking_state(role, is_speaking)
            logger.info(f"Speech update - Status: {status}, Role: {role}")
        elif msg_type == "transcript":
            pass
            # role = message.get("role", "")
            # transcript_type = message.get("transcriptType", "")
            # transcript = message.get("transcript", "")
            # # Only log final transcripts
            # if transcript_type == "final":
            #     logger.info(f"Transcript | {role.title()}: {transcript}")
        elif msg_type == "conversation-update":
            self.conversation = message.get("conversation", [])
            last_message = self.conversation[-1]
            role = last_message.get('role')
            content = last_message.get('content', '')
            logger.info(f"Message: {role}: {content}")
        elif msg_type == "user-interrupted":
            logger.info("User interrupted the assistant")
        elif msg_type == "model-output":
            # Too noisy
            # logger.info("Model output: " + message.get("output", ""))
            pass
        elif msg_type == "voice-input":
            # Too noisy
            # logger.info("Voice input: " + message.get("input", ""))
            pass
        elif msg_type == "call_state":
            old_state = message.get("old_state", "")
            new_state = message.get("new_state", "")
            logger.info(f"Call state changed: {old_state} -> {new_state}")
        elif msg_type == "participant-left":
            info = message.get("info", {})
            username = info.get("userName", "Unknown")
            reason = message.get("reason", "")
            logger.info(f"Participant left: {username} ({reason})")
        elif msg_type == "tool-calls":
            await self._handle_tool_calls(message.get('toolCalls', []))
        elif msg_type == "ERROR":
            error_message = message.get("message", "")
            target = message.get("target", "")
            logger.error(f"WebSocket/Signaling Error - Message: {error_message}, Target: {target}")
        else:
            logger.warning(f"Unknown message type received: {msg_type}, full message: {message}")

    async def join(self, meeting_url):
        """Join a call with the given URL"""
        if not self.state_manager.state.can_start_new_call:
            logger.warning(f"Cannot join call - current state: {self.state_manager.state}")
            return
            
        logger.info(f"Joining call with URL: {meeting_url} (current state: {self.state_manager.state})")
        
        # Initialize Daily runtime before joining
        try:
            await self._initialize_daily_runtime()
            await self._initialize_devices()
        except Exception as e:
            logger.error(f"Failed to initialize Daily for call: {e}")
            await self.state_manager.transition_to(CallState.ERROR)
            return
        
        # Clear any previous state
        self.state_manager.start_event.clear()
        self.state_manager._participants.clear()
        
        # Initialize call client before joining
        await self._initialize_call_client()
        
        # Now transition to JOINING
        logger.info("Transitioning to JOINING state...")
        await self.state_manager.transition_to(CallState.JOINING)
        
        # Only join if we successfully transitioned to JOINING
        if self.state_manager.state == CallState.JOINING:
            self._call_client.join(meeting_url, completion=self._event_handler.on_joined)
        else:
            logger.error(f"Failed to transition to JOINING state, current state: {self.state_manager.state}")
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
                # Wait a bit for the leave message to be sent
                await asyncio.sleep(0.2)
                # Then release the client
                try:
                    client.release()
                    logger.info("Call client released")
                except Exception as e:
                    logger.warning(f"Error releasing call client: {e}")
                # Wait a bit after release
                await asyncio.sleep(0.2)
            except Exception as e:
                logger.warning(f"Error during client cleanup: {e}")
        
        # Wait for the left state update from Daily
        # If we don't receive it within a timeout, force the transition
        try:
            async def wait_for_left_state():
                while not self.state_manager.state == CallState.LEFT:
                    await asyncio.sleep(0.1)
                    
            await asyncio.wait_for(wait_for_left_state(), timeout=2.0)  # 2 second timeout
        except asyncio.TimeoutError:
            logger.warning("Timeout waiting for LEFT state from Daily, forcing transition")
            await self.state_manager.transition_to(CallState.LEFT)
        
        # Small delay to ensure cleanup is complete
        await asyncio.sleep(0.2)

    async def cleanup(self):
        """Clean up all resources"""
        try:
            # Cancel message processor task if it exists
            if self._message_processor_task:
                self._message_processor_task.cancel()
                try:
                    await self._message_processor_task
                except asyncio.CancelledError:
                    pass
                self._message_processor_task = None
            
            # First leave any active call
            if not self.state_manager.state.is_terminal_state:
                await self.leave()
                
            # Then cleanup audio
            self._cleanup_audio_system()
            
            # Release call client if it exists
            if hasattr(self, '_call_client') and self._call_client:
                try:
                    self._call_client.release()
                except Exception as e:
                    logger.warning(f"Error releasing call client: {e}")
                self._call_client = None
            
            # Small delay to ensure client is fully released
            await asyncio.sleep(0.2)
            
            # Reset to initialized state
            await self.state_manager.transition_to(CallState.INITIALIZED)
            
            # Clear event handler
            self._event_handler = None
            
        except Exception as e:
            logger.error(f"Error during ConversationManager cleanup: {e}")
            await self.state_manager.transition_to(CallState.ERROR)
            
        # Final delay to ensure all resources are cleaned up
        await asyncio.sleep(0.2)

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
        is_speaker = "userName" in participant["info"] and participant["info"]["userName"] == ConversationConfig.Vapi.SPEAKER_USERNAME
        mic = participant["media"]["microphone"]
        is_subscribed = mic["subscribed"] == "subscribed"
        is_playable = mic["state"] == "playable"
        return is_speaker and is_subscribed and is_playable

    async def _cleanup_call_audio(self):
        """Cleanup audio components specific to a call"""
        # Cancel audio tasks if they exist and are not None
        if hasattr(self, '_pitch_shift_worker_task') and self._pitch_shift_worker_task is not None:
            self._pitch_shift_worker_task.cancel()
            try:
                await self._pitch_shift_worker_task
            except asyncio.CancelledError:
                pass
            self._pitch_shift_worker_task = None
            
        # Wait for threads to finish
        if hasattr(self, '_audio_reader_thread') and self._audio_reader_thread is not None:
            self._audio_reader_thread.join(timeout=1.0)
            self._audio_reader_thread = None
        if hasattr(self, '_input_thread') and self._input_thread is not None:
            self._input_thread.join(timeout=1.0)
            self._input_thread = None
            
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
        response = requests.post(url, headers=headers, json=payload, timeout=30)
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
        assistant_config=None,
        squad_id=None,
        squad=None,
        include_memories: bool = True
    ):
        """Start a new call with specified assistant or squad"""
        logger.info("Starting call...")

        assistant_config_to_use = assistant_config.copy()
        # Fetch memories and add to assistant context
        if include_memories:
            memories = self.memory_manager.get_memories_formatted()
            assistant_config_to_use["context"] += ASSISTANT_CONTEXT_MEMORY_PROMPT.format(memories=memories)

        # Start a new call
        if assistant_id:
            payload = {'assistantId': assistant_id, 'assistantOverrides': assistant_config_to_use}
        elif assistant:
            payload = {'assistant': assistant, 'assistantOverrides': assistant_config_to_use}
        elif squad_id:
            payload = {'squadId': squad_id}
        elif squad:
            payload = {'squad': squad}
        else:
            raise Exception("Error: No assistant specified.")

        logger.info("Creating web call with payload: " + str(payload))
        call_id, web_call_url = self._create_vapi_call(payload)

        if not web_call_url:
            raise Exception("Error: Unable to create call.")

        logger.info('Joining call... ' + call_id)
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
            logger.error(f"Failed to send message: {e}")

    # TODO: Just found this ability in the docs. Use the trigger_response parameter. 
    def add_message(self, role, content, trigger_response=True):
        """ Adds the message to the conversation history.
            role: system (Theoretically ensures the addition is unobtrusive but not actually the case) | user | assistant | tool | function
            content: Actual message content.
            trigger_response: Whether to trigger a response from the assistant or silently add the message to the conversation history.
        """
        message = {
            'type': 'add-message',
            'message': {
                'role': role,
                'content': content
            },
            'triggerResponseEnabled': trigger_response            
        }
        self.send_message(message)

    # TODO: Just found this ability in the docs. Use it instead of sending the "wait, I want to say something" message.
    def tell_assistant_mute(self, mute: bool):
        """Send a mute message to the assistant"""
        message = {
            'type': 'control',
            'control': 'mute-assistant' if mute else 'unmute-assistant'
        }
        self.send_message(message)

    def tell_assistant_say_something(self, content: str, end_call_after_spoken: bool = False):
        """Tell the assistant to say something"""
        message = {
            'type': 'say',
            'say': content,
            'endCallAfterSpoken': end_call_after_spoken
        }
        self.send_message(message)

    def tell_assistant_end_call(self):
        """Tell the assistant to end the call"""
        message = {
            'type': 'end-call'
        }
        self.send_message(message)

    # TODO: This isn't being used anywhere. Should we use it for tool call results, or will the non-blocking config of the tools suffice?
    def add_message_no_interrupt(self, role, content):
        """Adds the message to the conversation history without interrupting the assistant.
        The message will be queued and sent when neither party is speaking.
        
        Args:
            role (str): Message role (system/user/assistant/tool/function)
            content (str): Message content
        """
        message = {
            'type': 'add-message',
            'message': {
                'role': role,
                'content': content
            }
        }
        
        # Add to queue - use create_task to avoid blocking
        asyncio.create_task(self._message_queue.put(message))

    def interrupt_assistant(self):
        """Stop the assistant from speaking if it's speaking"""
        if self.state_manager.assistant_speaking and ConversationConfig.MUTE_WHEN_ASSISTANT_SPEAKING:
            self.add_message("user", "Wait, I want to say something.")
    
    async def _send_user_audio(self):
        """Task for sending user audio to Daily"""
        try:
            await self.state_manager.start_event.wait()
            if self.state_manager.state == CallState.ERROR:
                logger.error("Unable to send user audio due to error state")
                return
                
            logger.info("Started sending user audio")
            while self.state_manager.state.can_receive_audio:
                await asyncio.sleep(0.1)  # Match original implementation's timing
        except asyncio.CancelledError:
            logger.info("Send user audio task cancelled")
            raise

    def _input_audio_thread(self):
        """Dedicated thread for handling input audio"""
        try:
            while self.state_manager.state.can_receive_audio:
                try:
                    # Get audio data from the buffer with short timeout
                    audio_data = self._input_buffer.get(timeout=0.01)  # Reduced timeout for lower latency
                    # TODO: We're muting just by throwing away the audio data.
                    #       We should (also?) be muting the mic device and/or pausing the audio producer.
                    if audio_data is not None and self._mic_device and not self.state_manager.is_muted:
                        self._mic_device.write_frames(audio_data.tobytes())
                except queue.Empty:
                    time.sleep(0.001)  # Minimal sleep when no data
                    continue
                except Exception as e:
                    if self.state_manager.state.can_receive_audio:
                        logger.error(f"Error in input audio thread: {e}")
                    time.sleep(0.001)
        except Exception as e:
            logger.error(f"Input audio thread error: {e}")

    def _handle_input_audio(self, audio_data: np.ndarray):
        """Queue audio data from audio manager"""
        try:
            if self.state_manager.state.can_receive_audio:
                try:
                    self._input_buffer.put_nowait(audio_data)
                except queue.Full:
                    # Try to remove old data and add new
                    try:
                        self._input_buffer.get_nowait()
                        self._input_buffer.put_nowait(audio_data)
                    except (queue.Empty, queue.Full):
                        pass  # If still can't add, drop the frame
        except Exception as e:
            logger.error(f"Error queuing input audio: {e}")

    async def mute(self):
        """Mute the local participant's microphone"""
        if not self._call_client or not self.state_manager.state.can_receive_audio:
            logger.warning("Cannot mute - call not active")
            return False
            
        try:
            self._call_client.update_inputs({
                "microphone": {
                    "isEnabled": False,
                    "settings": {
                        "deviceId": ConversationConfig.Daily.MIC_DEVICE_ID,
                        "customConstraints": ConversationConfig.Daily.MIC_CONSTRAINTS
                    }
                }
            })
            self.state_manager.set_muted(True)
            logger.info("Microphone muted")
            return True
        except Exception as e:
            logger.error(f"Failed to mute microphone: {e}")
            return False

    async def unmute(self):
        """Unmute the local participant's microphone"""
        if not self._call_client or not self.state_manager.state.can_receive_audio:
            logger.warning("Cannot unmute - call not active")
            return False
            
        try:
            self._call_client.update_inputs({
                "microphone": {
                    "isEnabled": True,
                    "settings": {
                        "deviceId": ConversationConfig.Daily.MIC_DEVICE_ID,
                        "customConstraints": ConversationConfig.Daily.MIC_CONSTRAINTS
                    }
                }
            })
            self.state_manager.set_muted(False)
            logger.info("Microphone unmuted")
            return True
        except Exception as e:
            logger.error(f"Failed to unmute microphone: {e}")
            return False

    async def toggle_mute(self):
        """Toggle the mute state of the local participant's microphone"""
        if self.state_manager.is_muted:
            return await self.unmute()
        else:
            return await self.mute()

    def is_muted(self) -> bool:
        """Get the current mute state"""
        return self.state_manager.is_muted

    async def _process_queued_messages(self):
        """Background task to process queued messages when neither party is speaking"""
        while True:
            try:
                # Wait for a message to be available
                message = await self._message_queue.get()
                
                # Wait until neither party is speaking
                while (self.state_manager.assistant_speaking or 
                       self.state_manager.user_speaking):
                    await asyncio.sleep(0.1)
                
                # Send the message if we're still in an active call
                if self.state_manager.state.is_active:
                    self.send_message(message)
                    
                self._message_queue.task_done()
                
            except asyncio.CancelledError:
                # Clean exit on cancellation
                break
            except Exception as e:
                logger.error(f"Error processing queued message: {e}")
                await asyncio.sleep(0.1)

    async def _pitch_shift_worker(self):
        """
        Gets raw audio from a queue, pitch-shifts it, and puts it into the
        final producer buffer for playback.
        """
        loop = asyncio.get_running_loop()
        
        # Initialize pitch shifter if available
        if STFTPITCHSHIFT_AVAILABLE:
            pitch_factor = 2 ** (self.DEFAULT_PITCH_SEMITONES / 12.0)
            self._pitch_shifter = StreamingPitchShifter(pitch_factor=pitch_factor)
            # "Warm up" the pitch shifter to avoid a long delay on the first chunk
            try:
                logger.info("Warming up pitch shifter...")
                warmup_chunk = np.zeros(ConversationConfig.Audio.CHUNK_SIZE, dtype=np.int16)
                await loop.run_in_executor(
                    None, self._pitch_shifter.process_chunk, warmup_chunk
                )
                logger.info("Pitch shifter warmed up.")
            except Exception as e:
                logger.error(f"Error warming up pitch shifter: {e}")
        else:
            self._pitch_shifter = None

        logger.info("Pitch shift worker started.")

        try:
            while True:
                raw_chunk = await loop.run_in_executor(
                    None, self._raw_audio_queue.get
                )

                chunks_to_play = []
                if self.state_manager.assistant_speaking and self._pitch_shifter:
                    processed_chunks = await loop.run_in_executor(
                        None, self._pitch_shifter.process_chunk, raw_chunk
                    )
                    if processed_chunks:
                        chunks_to_play.extend(processed_chunks)
                else:
                    chunks_to_play.append(raw_chunk)

                for chunk in chunks_to_play:
                    if chunk is not None and chunk.size > 0:
                        # This put is blocking, but the buffer is sized to handle it
                        self._audio_producer.buffer.put(chunk)

                self._raw_audio_queue.task_done()

        except asyncio.CancelledError:
            logger.info("Pitch shift worker cancelled.")
            if self._pitch_shifter:
                self._pitch_shifter.clear()
        except Exception as e:
            logger.error(f"Error in pitch shift worker: {e}", exc_info=True)

    def _audio_reader_loop(self):
        """
        Dedicated thread to read audio from the blocking Daily device
        and put it into a queue for async processing.
        """
        logger.info("Audio reader thread started.")
        while self.state_manager.state.can_receive_audio:
            try:
                buffer = self._speaker_device.read_frames(ConversationConfig.Audio.CHUNK_SIZE)
                if buffer:
                    audio_np = np.frombuffer(buffer, dtype=np.int16)
                    try:
                        self._raw_audio_queue.put_nowait(audio_np)
                    except queue.Full:
                        logger.warning("Raw audio queue is full. An audio chunk was dropped.")
                else:
                    time.sleep(0.001) # Avoid tight loop if no buffer
            except Exception as e:
                if self.state_manager.state.can_receive_audio:
                    logger.error(f"Error in audio reader thread: {e}", exc_info=True)
                break
        logger.info("Audio reader thread stopped.")

