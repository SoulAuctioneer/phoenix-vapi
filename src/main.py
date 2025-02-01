import asyncio
import logging
import signal
from services.service import ServiceManager
from services.audio_service import AudioService
from services.wakeword_service import WakeWordService
from services.conversation_service import ConversationService
from services.led_service import LEDService

# Configure logging with more detail
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(filename)s.%(funcName)s:%(lineno)d] - %(levelname)s - %(message)s',
    force=True  # Override any existing logging configuration
)

# Enable debug logging for our modules
for logger_name in [
    'services.audio_manager',
    'services.wake_word',
    'services.conversation',
    'services.service',
]:
    logging.getLogger(logger_name).setLevel(logging.DEBUG)

class PhoenixApp:
    def __init__(self):
        self.manager = ServiceManager()
        self.services = []
        self._should_run = True

    async def initialize_services(self):
        """Initialize and start all services in the correct order"""
        # Create services in order
        services = [
            AudioService(self.manager),        # Initialize audio first
            WakeWordService(self.manager),     # Then wake word detection
            ConversationService(self.manager), # Then conversation handling
            LEDService(self.manager),          # Finally LED control
        ]
        
        # Start audio service first
        await self.manager.start_service(services[0].__class__.__name__.lower(), services[0])
        
        # Start remaining services in parallel
        await asyncio.gather(
            *[self.manager.start_service(service.__class__.__name__.lower(), service)
              for service in services[1:]]
        )
        
        self.services = services
        logging.info("All services initialized and started")

        # Request sound effect playback
        await self.manager.publish({
            "type": "play_sound",
            "effect_name": "RISING_TONE",
            "producer_name": "sfx",
            "volume": 0.1  # Set volume to 10%
        })

    async def run(self):
        """Main application loop"""
        try:
            await self.initialize_services()
            
            # Keep the main task running
            while self._should_run:
                await asyncio.sleep(1)
                
        except asyncio.CancelledError:
            logging.info("Application task cancelled")
            await self.cleanup()
        except Exception as e:
            logging.error(f"Fatal error: {e}", exc_info=True)
            raise
        finally:
            await self.cleanup()

    async def cleanup(self):
        """Cleanup all resources"""
        logging.info("Cleaning up resources...")
        await self.manager.stop_all()

    def handle_shutdown(self, sig=None):
        """Handle shutdown signals"""
        if sig:
            logging.info(f"Received signal {sig.name}")
        self._should_run = False
        # Schedule the cleanup
        asyncio.create_task(self.cleanup())
        # Cancel all tasks except the current one
        for task in asyncio.all_tasks():
            if task is not asyncio.current_task():
                task.cancel()

async def main():
    app = PhoenixApp()
    
    # Setup signal handlers for graceful shutdown
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(
            sig,
            lambda s=sig: app.handle_shutdown(s)
        )
    
    await app.run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except asyncio.CancelledError:
        logging.info("Application cancelled")
    except KeyboardInterrupt:
        logging.info("Application interrupted")
    except Exception as e:
        logging.error(f"Fatal error: {e}", exc_info=True)
    finally:
        logging.info("Application stopped") 