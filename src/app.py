import logging
from vapi import Vapi
from wake_word import WakeWordDetector
from config import VAPI_API_KEY, PICOVOICE_ACCESS_KEY, ASSISTANT_CONFIG, ASSISTANT_ID, WAKE_WORD_PATH

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class App:
    def __init__(self):
        self.vapi = Vapi(api_key=VAPI_API_KEY)
        self.wake_word_detector = None
        self.is_active = False
        logging.info("App initialized")

    def setup_wake_word(self):
        """Initialize the wake word detector"""
        try:
            logging.info("Using wake word from: %s", WAKE_WORD_PATH)
            self.wake_word_detector = WakeWordDetector(
                callback_fn=self.on_wake_word,
                access_key=PICOVOICE_ACCESS_KEY,
                keyword_path=WAKE_WORD_PATH,
            )
            logging.info("Wake word detector initialized successfully")
        except Exception as e:
            logging.error("Failed to initialize wake word detector: %s", str(e), exc_info=True)
            raise

    def on_wake_word(self):
        """Handle wake word detection by starting an interaction"""
        if not self.is_active:
            logging.info("Wake word detected, starting interaction")
            self.start_interaction()
        else:
            logging.debug("Wake word detected but interaction already active")

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

    def start(self):
        """Start the application and begin listening for wake word"""
        try:
            self.setup_wake_word()
            logging.info("Starting wake word detection...")
            print("Waiting for wake word...")
            self.wake_word_detector.start()
        except Exception as e:
            logging.error("Error starting application: %s", str(e), exc_info=True)
            self.cleanup()
            raise

    def cleanup(self):
        """Clean up resources"""
        logging.info("Cleaning up resources")
        self.stop_interaction()
        if self.wake_word_detector:
            try:
                self.wake_word_detector.stop()
                logging.info("Wake word detector stopped successfully")
            except Exception as e:
                logging.error("Error stopping wake word detector: %s", str(e), exc_info=True) 