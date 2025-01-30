import daily
import threading
import numpy as np
import json
import logging
import asyncio
import time
from services.audio_manager import AudioManager

SAMPLE_RATE = 16000
NUM_CHANNELS = 1
CHUNK_SIZE = 640


def is_playable_speaker(participant):
    is_speaker = "userName" in participant["info"] and participant["info"]["userName"] == "Vapi Speaker"
    mic = participant["media"]["microphone"]
    is_subscribed = mic["subscribed"] == "subscribed"
    is_playable = mic["state"] == "playable"
    return is_speaker and is_subscribed and is_playable


class DailyCallEventHandler(daily.EventHandler):
    """Event handler for Daily calls"""
    def __init__(self, call):
        super().__init__()
        self.call = call
        self.loop = asyncio.get_event_loop()

    def on_call_state_updated(self, state):
        self.loop.call_soon_threadsafe(
            lambda: asyncio.create_task(self.call.handle_call_state_updated(state))
        )

    def on_participant_left(self, participant, reason):
        self.loop.call_soon_threadsafe(
            lambda: asyncio.create_task(self.call.handle_participant_left(participant, reason))
        )

    def on_participant_joined(self, participant):
        self.loop.call_soon_threadsafe(
            lambda: asyncio.create_task(self.call.handle_participant_joined(participant))
        )

    def on_participant_updated(self, participant):
        self.loop.call_soon_threadsafe(
            lambda: asyncio.create_task(self.call.handle_participant_updated(participant))
        )

    def on_inputs_updated(self, input_settings):
        self.loop.call_soon_threadsafe(
            lambda: asyncio.create_task(self.call.handle_inputs_updated(input_settings))
        )

    def on_joined(self, data, error):
        self.loop.call_soon_threadsafe(
            lambda: asyncio.create_task(self.call.handle_joined(data, error))
        )


class DailyCall:
    """Handles Daily call functionality"""
    def __init__(self, manager=None):
        self.manager = manager
        self.__call_state = "initialized"
        self.__app_quit = False
        self.__app_error = None
        self.__app_joined = False
        self.__app_inputs_updated = False
        self.__participants = {}
        self.__start_event = threading.Event()
        self.__volume = 0.3  # Initial volume at 30%
        
        # Get audio manager instance
        self.audio_manager = AudioManager.get_instance()
        
        # Setup Daily call client
        self.__event_handler = DailyCallEventHandler(self)
        self.__call_client = daily.CallClient(event_handler=self.__event_handler)
        
        self.__call_client.update_inputs({
            "camera": False,
            "microphone": {
                "isEnabled": True,
                "settings": {
                    "deviceId": "my-mic",
                    "customConstraints": {
                        "autoGainControl": {"exact": True},
                        "noiseSuppression": {"exact": True},
                        "echoCancellation": {"exact": True},
                    }
                }
            }
        })
        
        self.__call_client.update_subscription_profiles({
            "base": {
                "camera": "unsubscribed",
                "microphone": "subscribed"
            }
        })
        
        self.__participants = dict(self.__call_client.participants())
        if "local" in self.__participants:
            del self.__participants["local"]
            
        # Setup audio devices and consumers/producers
        self.setup_audio()

    def setup_audio(self):
        """Initialize audio components"""
        # Create Daily devices
        self.__mic_device = daily.Daily.create_microphone_device(
            "my-mic",
            sample_rate=SAMPLE_RATE,
            channels=NUM_CHANNELS
        )

        self.__speaker_device = daily.Daily.create_speaker_device(
            "my-speaker",
            sample_rate=SAMPLE_RATE,
            channels=NUM_CHANNELS
        )
        daily.Daily.select_speaker_device("my-speaker")
        
        # Register as audio consumer and producer
        self._audio_consumer = self.audio_manager.add_consumer(self.handle_input_audio)
        self._audio_producer = self.audio_manager.add_producer("daily_call")
        # Set initial volume
        self.audio_manager.set_producer_volume("daily_call", self.__volume)
        
    def handle_input_audio(self, audio_data: np.ndarray):
        """Handle input audio from audio manager"""
        if not self.__app_quit and self.__mic_device:
            try:
                # Convert float32 to int16 for Daily
                audio_int16 = (audio_data * 32767).astype(np.int16)
                self.__mic_device.write_frames(audio_int16.tobytes())
            except Exception as e:
                logging.error(f"Error writing to mic device: {e}")

    def handle_output_audio(self, audio_data: bytes):
        """Handle output audio from Daily"""
        if not self.__app_quit and self._audio_producer:
            try:
                # Convert int16 to float32
                audio_np = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32767.0
                # Volume control is handled by the AudioManager
                self._audio_producer.buffer.put(audio_np)
            except Exception as e:
                logging.error(f"Error processing output audio: {e}")

    async def handle_call_state_updated(self, state):
        """Handle call state changes and publish events"""
        # Prevent redundant state updates
        if state == self.__call_state:
            return
            
        logging.info(f"Call state updated: {state}")
        self.__call_state = state
        
        if self.manager:
            if state == "joined":
                await self.manager.publish_event({
                    "type": "call_state",
                    "state": "started"
                })
            elif state == "left":
                await self.manager.publish_event({
                    "type": "call_state",
                    "state": "ended"
                })

    async def handle_participant_left(self, participant, reason):
        """Handle participant leaving and publish event"""
        logging.info(f"Participant left: {participant}, reason: {reason}")
        if participant["id"] in self.__participants:
            del self.__participants[participant["id"]]
            
            # If the leaving participant was the assistant, publish event
            if "userName" in participant["info"] and participant["info"]["userName"] == "Vapi Speaker":
                if self.manager and self.__call_state != "left":  # Only if we haven't already left
                    await self.manager.publish_event({
                        "type": "call_state",
                        "state": "ended"
                    })
                    self.leave()

    async def handle_participant_joined(self, participant):
        logging.info(f"Participant joined: {participant}")
        self.__participants[participant["id"]] = participant

    async def handle_participant_updated(self, participant):
        logging.debug(f"Participant updated: {participant}")
        self.__participants[participant["id"]] = participant
        if is_playable_speaker(participant):
            self.__call_client.send_app_message("playable")

    async def handle_inputs_updated(self, input_settings):
        logging.debug(f"Inputs updated: {input_settings}")
        self.__app_inputs_updated = True
        self.maybe_start()

    async def handle_joined(self, data, error):
        if error:
            logging.error(f"Unable to join call: {error}")
            self.__app_error = error
        else:
            self.__app_joined = True
            logging.info("Joined call")
            if self.manager:
                await self.manager.publish_event({"type": "conversation_started"})
        self.maybe_start()

    def join(self, meeting_url):
        """Join a call with the given URL"""
        if self.__call_state == "left":
            # Reset state
            self.__app_quit = False
            self.__app_error = None
            self.__app_joined = False
            self.__app_inputs_updated = False
            self.__start_event.clear()
            
            # Setup audio again
            self.setup_audio()
            
        logging.info(f"Joining call with URL: {meeting_url}")
        self.__call_client.join(meeting_url, completion=self.__event_handler.on_joined)

    def leave(self):
        """Leave the call and clean up resources"""
        if self.__call_state == "left":  # Don't leave if already left
            return
            
        self.__app_quit = True
        
        # Remove audio consumer and producer
        if hasattr(self, '_audio_consumer'):
            self.audio_manager.remove_consumer(self._audio_consumer)
            self._audio_consumer = None
            
        if hasattr(self, '_audio_producer'):
            self.audio_manager.remove_producer("daily_call")
            self._audio_producer = None
            
        # Leave the call
        self.__call_client.leave()

    def send_app_message(self, message):
        """Send an application message to the assistant."""
        try:
            serialized_message = json.dumps(message)
            self.__call_client.send_app_message(serialized_message)
        except Exception as e:
            print(f"Failed to send app message: {e}")

    def set_volume(self, volume):
        """Set the output volume (0.0 to 1.0)"""
        self.__volume = max(0.0, min(1.0, volume))
        self.audio_manager.set_producer_volume("daily_call", self.__volume)

    def get_volume(self):
        """Get the current output volume (0.0 to 1.0)"""
        return self.__volume

    def maybe_start(self):
        if self.__app_error:
            self.__start_event.set()

        if self.__app_inputs_updated and self.__app_joined:
            self.__start_event.set()

    def cleanup(self):
        """Clean up resources"""
        self.leave()
