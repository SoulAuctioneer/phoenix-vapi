import daily
import threading
import pyaudio
import json
import logging
from audio_control import AudioControl

SAMPLE_RATE = 16000
NUM_CHANNELS = 1
CHUNK_SIZE = 640


def is_playable_speaker(participant):
    is_speaker = "userName" in participant["info"] and participant["info"]["userName"] == "Vapi Speaker"
    mic = participant["media"]["microphone"]
    is_subscribed = mic["subscribed"] == "subscribed"
    is_playable = mic["state"] == "playable"
    return is_speaker and is_subscribed and is_playable


class DailyCall(daily.EventHandler):
    def __init__(self):
        # Call parent class's __init__ first
        super().__init__()
        
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

        self.__call_client = daily.CallClient(event_handler=self)

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

    # Event handlers from daily.EventHandler
    def on_active_speaker_changed(self, participant):
        logging.debug(f"Active speaker changed: {participant}")

    def on_app_message(self, message, sender):
        logging.debug(f"App message from {sender}: {message}")

    def on_available_devices_updated(self, available_devices):
        logging.debug(f"Available devices updated: {available_devices}")

    def on_call_state_updated(self, state):
        logging.info(f"Call state updated: {state}")

    def on_dialin_ready(self, sip_endpoint):
        logging.debug(f"Dialin ready: {sip_endpoint}")

    def on_dialout_answered(self, data):
        logging.debug(f"Dialout answered: {data}")

    def on_dialout_connected(self, data):
        logging.debug(f"Dialout connected: {data}")

    def on_dialout_error(self, data):
        logging.error(f"Dialout error: {data}")

    def on_dialout_stopped(self, data):
        logging.debug(f"Dialout stopped: {data}")

    def on_dialout_warning(self, data):
        logging.warning(f"Dialout warning: {data}")

    def on_error(self, message):
        logging.error(f"Call error: {message}")
        self.__app_error = message

    def on_inputs_updated(self, input_settings):
        logging.debug(f"Inputs updated: {input_settings}")
        self.__app_inputs_updated = True
        self.maybe_start()

    def on_live_stream_error(self, stream_id, message):
        logging.error(f"Live stream error for {stream_id}: {message}")

    def on_live_stream_started(self, status):
        logging.info(f"Live stream started: {status}")

    def on_live_stream_stopped(self, stream_id):
        logging.info(f"Live stream stopped: {stream_id}")

    def on_live_stream_updated(self, state):
        logging.debug(f"Live stream updated: {state}")

    def on_live_stream_warning(self, stream_id, message):
        logging.warning(f"Live stream warning for {stream_id}: {message}")

    def on_network_stats_updated(self, stats):
        logging.debug(f"Network stats updated: {stats}")

    def on_participant_counts_updated(self, counts):
        logging.debug(f"Participant counts updated: {counts}")

    def on_participant_joined(self, participant):
        logging.info(f"Participant joined: {participant}")
        self.__participants[participant["id"]] = participant

    def on_participant_left(self, participant, reason):
        logging.info(f"Participant left: {participant}, reason: {reason}")
        del self.__participants[participant["id"]]
        # Call session end callback before leaving if it exists
        # if self.__on_session_end:
        #     self.__on_session_end()
        self.leave()

    def on_participant_updated(self, participant):
        logging.debug(f"Participant updated: {participant}")
        self.__participants[participant["id"]] = participant
        if is_playable_speaker(participant):
            self.__call_client.send_app_message("playable")

    def on_publishing_updated(self, publishing_settings):
        logging.debug(f"Publishing updated: {publishing_settings}")

    def on_recording_error(self, stream_id, message):
        logging.error(f"Recording error for {stream_id}: {message}")

    def on_recording_started(self, status):
        logging.info(f"Recording started: {status}")

    def on_recording_stopped(self, stream_id):
        logging.info(f"Recording stopped: {stream_id}")

    def on_subscription_profiles_updated(self, profile_settings):
        logging.debug(f"Subscription profiles updated: {profile_settings}")

    def on_subscriptions_updated(self, subscription_settings):
        logging.debug(f"Subscriptions updated: {subscription_settings}")

    def on_transcription_error(self, message):
        logging.error(f"Transcription error: {message}")

    def on_transcription_message(self, data):
        logging.debug(f"Transcription message: {data}")

    def on_transcription_started(self):
        logging.info("Transcription started")

    def on_transcription_stopped(self):
        logging.info("Transcription stopped")

    def on_waiting_participant_added(self, participant):
        logging.info(f"Waiting participant added: {participant}")

    def on_waiting_participant_removed(self, participant):
        logging.info(f"Waiting participant removed: {participant}")

    def on_waiting_participant_updated(self, participant):
        logging.debug(f"Waiting participant updated: {participant}")

    def on_joined(self, data, error):
        if error:
            logging.error(f"Unable to join call: {error}")
            self.__app_error = error
        else:
            self.__app_joined = True
            logging.info("Joined call")
        self.maybe_start()

    def join(self, meeting_url):
        logging.info(f"Joining call with URL: {meeting_url}")
        self.__call_client.join(meeting_url, completion=self.on_joined)

    def leave(self):
        """Leave the call and clean up resources"""
        self.__app_quit = True
        self.__receive_bot_audio_thread.join()
        self.__send_user_audio_thread.join()
        self.__call_client.leave()
        # Call session end callback if it exists
        # if self.__on_session_end:
        #     self.__on_session_end()

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
        """
        Send an application message to the assistant.

        :param message: The message to send (expects a dictionary).
        """
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
