import logging
import daily
from services import ServiceManager, WakeWordService, ConversationService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class App:
    def __init__(self):
        # Initialize Daily runtime
        daily.Daily.init()
        logging.info("Daily runtime initialized")
        
        self.manager = ServiceManager()
        self.wake_word_service = None
        self.conversation_service = None
        # self.led_service = None
        # self.accelerometer_service = None
        
    async def start(self):
        """Start the application and all its services"""
        try:
            # Initialize and start services
            self.wake_word_service = WakeWordService(self.manager)
            self.conversation_service = ConversationService(self.manager)
            # self.led_service = LEDService(self.manager)
            # self.accelerometer_service = AccelerometerService(self.manager)
            
            await self.manager.start_service("wake_word", self.wake_word_service)
            await self.manager.start_service("conversation", self.conversation_service)
            # await self.manager.start_service("led", self.led_service)
            # await self.manager.start_service("accelerometer", self.accelerometer_service)
            
            # Start event processing
            await self.manager.process_events()
            
        except Exception as e:
            logging.error("Error starting application: %s", str(e), exc_info=True)
            await self.cleanup()
            raise
            
    async def cleanup(self):
        """Clean up resources"""
        logging.info("Cleaning up resources")
        await self.manager.stop_all() 