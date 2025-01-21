from vapi_python import Vapi
from config import VAPI_API_KEY, ASSISTANT_CONFIG, ASSISTANT_ID

class KidsCompanion:
    def __init__(self):
        self.vapi = Vapi(api_key=VAPI_API_KEY)
        self.is_active = False

    def start_interaction(self):
        """Start an interaction session with the AI companion"""
        if not self.is_active:
            self.is_active = True
            try:
                # self.vapi.start(assistant=ASSISTANT_CONFIG)
                self.vapi.start(assistant_id=ASSISTANT_ID)
            except Exception as e:
                print(f"Error starting companion: {e}")
                self.stop_interaction()

    def stop_interaction(self):
        """Stop the current interaction session"""
        if self.is_active:
            self.is_active = False
            try:
                self.vapi.stop()
            except Exception as e:
                print(f"Error stopping companion: {e}")

    def cleanup(self):
        """Clean up resources"""
        self.stop_interaction() 