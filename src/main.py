import asyncio
import logging
import signal
from services.service import ServiceManager
from services.audio_service import AudioService
from services.wake_word import WakeWordService
from services.conversation import ConversationService
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
    'services.service',  # Added service manager logging
]:
    logging.getLogger(logger_name).setLevel(logging.DEBUG)

async def main():
    # Create service manager
    manager = ServiceManager()
    
    # Create and register services in order
    services = [
        AudioService(manager),        # Initialize audio first
        WakeWordService(manager),     # Then wake word detection
        ConversationService(manager), # Then conversation handling
        LEDService(manager),          # Finally LED control
    ]
    
    # Start all services
    for service in services:
        await manager.start_service(service.__class__.__name__.lower(), service)
        
    # Setup signal handlers for graceful shutdown
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown(manager)))
        
    # Keep the main task running
    try:
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass

async def shutdown(manager: ServiceManager):
    """Gracefully shutdown all services"""
    logging.info("Shutting down...")
    await manager.stop_all()
    
    # Cancel the main task
    for task in asyncio.all_tasks():
        if task is not asyncio.current_task():
            task.cancel()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass  # Handle Ctrl+C gracefully
    except Exception as e:
        logging.error(f"Fatal error: {e}", exc_info=True)
    finally:
        logging.info("Application stopped") 