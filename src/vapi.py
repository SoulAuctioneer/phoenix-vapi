import logging
from daily import *
import requests
from daily_call import DailyCall


class Vapi:
    def __init__(self, *, api_key, api_url="https://api.vapi.ai", manager=None):
        self.api_key = api_key
        self.api_url = api_url
        self.manager = manager
        self.__client = None
        # self.__on_session_end = None
        # Initialize Daily runtime
        try:
            Daily.init()
            logging.info("Daily runtime initialized")
        except Exception as e:
            logging.error(f"Failed to initialize Daily runtime: {e}")
            raise

    def __del__(self):
        """Cleanup when the Vapi instance is destroyed"""
        self.cleanup()

    def cleanup(self):
        """Clean up resources"""
        if self.__client:
            self.stop()
        try:
            Daily.deinit()
            logging.info("Daily runtime deinitialized")
        except Exception as e:
            logging.error(f"Error deinitializing Daily runtime: {e}")

    def __create_web_call(self, payload):
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

    def start(
        self,
        *,
        assistant_id=None,
        assistant=None,
        assistant_overrides=None,
        squad_id=None,
        squad=None,
        # on_session_end=None,
    ):
        logging.info("Starting Vapi...")
        # Store the session end callback
        # self.__on_session_end = on_session_end

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
        call_id, web_call_url = self.__create_web_call(payload)

        if not web_call_url:
            raise Exception("Error: Unable to create call.")

        logging.info('Joining call... ' + call_id)

        self.__client = DailyCall(manager=self.manager)
        self.__client.join(web_call_url)

    def stop(self):
        if self.__client:
            self.__client.leave()
            self.__client = None

    def send(self, message):
        """
        Send a generic message to the assistant.

        :param message: A dictionary containing the message type and content.
        """
        if not self.__client:
            raise Exception("Call not started. Please start the call first.")

        # Check message format here instead of serialization
        if not isinstance(message, dict) or 'type' not in message:
            raise ValueError("Invalid message format.")

        try:
            self.__client.send_app_message(message)  # Send dictionary directly
        except Exception as e:
            print(f"Failed to send message: {e}")

    def add_message(self, role, content):
        """
        method to send text messages with specific parameters.
        """
        message = {
            'type': 'add-message',
            'message': {
                'role': role,
                'content': content
            }
        }
        self.send(message)
