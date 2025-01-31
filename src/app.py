import logging
import daily
from services import ServiceManager, AudioService, WakeWordService, ConversationService, LEDService
import asyncio

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(filename)s.%(funcName)s:%(lineno)d] - %(levelname)s - %(message)s'
)

class App:
    def __init__(self):
        self.manager = ServiceManager()
        self.audio_service = None
        self.wake_word_service = None
        self.conversation_service = None
        self.led_service = None
        self._should_run = True
        
    async def start(self):
        """Start the application and all its services"""
        try:
            # Initialize Daily runtime once at startup
            daily.Daily.init()
            logging.info("Daily runtime initialized")
            
            # Initialize services
            self.audio_service = AudioService(self.manager)
            self.wake_word_service = WakeWordService(self.manager)
            self.conversation_service = ConversationService(self.manager)
            self.led_service = LEDService(self.manager)
            
            # Start all services and wait for them to complete initialization
            # Order matters: audio must start before services that use it
            await self.manager.start_service("audio", self.audio_service)  # Start audio first
            await asyncio.gather(
                self.manager.start_service("led", self.led_service),
                self.manager.start_service("wake_word", self.wake_word_service),
                self.manager.start_service("conversation", self.conversation_service)
            )
            
            # Keep running until stopped
            while self._should_run:
                await asyncio.sleep(1)
                
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