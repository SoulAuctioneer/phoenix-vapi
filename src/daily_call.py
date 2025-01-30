import daily
import threading
import pyaudio
import json
import logging
from audio_control import AudioControl
import asyncio

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
        self.__audio_interface = pyaudio.PyAudio()
        self.__audio_control = AudioControl()
        self.__audio_control.volume = 0.4  # Set initial volume to 40%

        self.__input_audio_stream = self.__audio_interface.open(
            format=pyaudio.paInt16,
            channels=NUM_CHANNELS,
            rate=SAMPLE_RATE,
            input=True,
            frames_per_buffer=CHUNK_SIZE,
        )

        self.__output_audio_stream = self.__audio_interface.open(
            format=pyaudio.paInt16,
            channels=NUM_CHANNELS,
            rate=SAMPLE_RATE,
            output=True,
            frames_per_buffer=CHUNK_SIZE
        )

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
        del self.__participants["local"]

        self.__app_quit = False
        self.__app_error = None
        self.__app_joined = False
        self.__app_inputs_updated = False

        self.__start_event = threading.Event()
        self.__receive_bot_audio_thread = threading.Thread(
            target=self.receive_bot_audio)
        self.__send_user_audio_thread = threading.Thread(
            target=self.send_user_audio)

        self.__receive_bot_audio_thread.start()
        self.__send_user_audio_thread.start()

    async def handle_call_state_updated(self, state):
        """Handle call state changes and publish events"""
        logging.info(f"Call state updated: {state}")
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
        del self.__participants[participant["id"]]
        
        # If the leaving participant was the assistant, publish event
        if "userName" in participant["info"] and participant["info"]["userName"] == "Vapi Speaker":
            if self.manager:
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
        self.maybe_start()

    def join(self, meeting_url):
        logging.info(f"Joining call with URL: {meeting_url}")
        self.__call_client.join(meeting_url, completion=self.__event_handler.on_joined)

    def leave(self):
        """Leave the call and clean up resources"""
        self.__app_quit = True
        self.__receive_bot_audio_thread.join()
        self.__send_user_audio_thread.join()
        self.__call_client.leave()

    def maybe_start(self):
        if self.__app_error:
            self.__start_event.set()

        if self.__app_inputs_updated and self.__app_joined:
            self.__start_event.set()

    def send_user_audio(self):
        self.__start_event.wait()

        if self.__app_error:
            print(f"Unable to receive mic audio!")
            return

        while not self.__app_quit:
            buffer = self.__input_audio_stream.read(
                CHUNK_SIZE, exception_on_overflow=False)
            if len(buffer) > 0:
                try:
                    self.__mic_device.write_frames(buffer)
                except Exception as e:
                    print(e)

    def receive_bot_audio(self):
        self.__start_event.wait()

        if self.__app_error:
            print(f"Unable to receive bot audio!")
            return

        while not self.__app_quit:
            buffer = self.__speaker_device.read_frames(CHUNK_SIZE)

            if len(buffer) > 0:
                # Adjust volume before playing
                adjusted_buffer = self.__audio_control.adjust_stream_volume(buffer)
                self.__output_audio_stream.write(adjusted_buffer, CHUNK_SIZE)

    def send_app_message(self, message):
        """Send an application message to the assistant."""
        try:
            serialized_message = json.dumps(message)
            self.__call_client.send_app_message(serialized_message)
        except Exception as e:
            print(f"Failed to send app message: {e}")

    def set_volume(self, volume):
        """Set the output volume (0.0 to 1.0)"""
        self.__audio_control.volume = volume

    def get_volume(self):
        """Get the current output volume (0.0 to 1.0)"""
        return self.__audio_control.volume

    def cleanup(self):
        """Clean up resources"""
        if hasattr(self, '__audio_control'):
            self.__audio_control.cleanup()
        self.leave()
