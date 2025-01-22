import logging
from vapi_python import Vapi
from config import VAPI_API_KEY, ASSISTANT_CONFIG, ASSISTANT_ID

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class App:
    def __init__(self):
        self.vapi = Vapi(api_key=VAPI_API_KEY)
        self.is_active = False
        logging.info("KidsCompanion initialized")

    def start_interaction(self):
        """Start an interaction session with the AI companion"""
        if not self.is_active:
            logging.info("Starting new interaction session")
            self.is_active = True
            try:
                logging.info("Attempting to start Vapi connection with assistant_id: %s", ASSISTANT_ID)
                self.vapi.start(assistant_id=ASSISTANT_ID)
                logging.info("Vapi connection started successfully")
            except Exception as e:
                logging.error("Failed to start companion: %s", str(e), exc_info=True)
                self.stop_interaction()
        else:
            logging.warning("Attempted to start interaction while already active")

    def stop_interaction(self):
        """Stop the current interaction session"""
        if self.is_active:
            logging.info("Stopping interaction session")
            self.is_active = False
            try:
                self.vapi.stop()
                logging.info("Vapi connection stopped successfully")
            except Exception as e:
                logging.error("Error stopping companion: %s", str(e), exc_info=True)
        else:
            logging.debug("Stop interaction called while already inactive")

    def cleanup(self):
        """Clean up resources"""
        logging.info("Cleaning up resources")
        self.stop_interaction() 