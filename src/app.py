import logging
import daily
from services import ServiceManager, WakeWordService, ConversationService, LEDService
import asyncio

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class App:
    def __init__(self):
        self.manager = ServiceManager()
        self.wake_word_service = None
        self.conversation_service = None
        self._should_run = True
        self.led_service = None
        # self.accelerometer_service = None
        
    async def start(self):
        """Start the application and all its services"""
        try:
            # Initialize Daily runtime once at startup
            daily.Daily.init()
            logging.info("Daily runtime initialized")
            
            # Initialize services
            self.wake_word_service = WakeWordService(self.manager)
            self.conversation_service = ConversationService(self.manager)
            self.led_service = LEDService(self.manager)
            # self.accelerometer_service = AccelerometerService(self.manager)
            
            # Start all services and wait for them to complete initialization
            await asyncio.gather(
                self.manager.start_service("led", self.led_service),  # Start LED first for visual feedback
                self.manager.start_service("wake_word", self.wake_word_service),
                self.manager.start_service("conversation", self.conversation_service)
                # await self.manager.start_service("accelerometer", self.accelerometer_service)
            )
            
            # Start event processing
            try:
                while self._should_run:
                    await self.manager.process_events()
            except asyncio.CancelledError:
                logging.info("App task cancelled")
                raise
            
        except Exception as e:
            logging.error("Error starting application: %s", str(e), exc_info=True)
            await self.cleanup()
            raise
            
    async def cleanup(self):
        """Clean up resources"""
        self._should_run = False
        logging.info("Cleaning up resources")
        await self.manager.stop_all()
        
        # Cleanup Daily runtime last
        try:
            daily.Daily.deinit()
            logging.info("Daily runtime deinitialized")
        except Exception as e:
            logging.error("Error deinitializing Daily runtime: %s", str(e), exc_info=True) 