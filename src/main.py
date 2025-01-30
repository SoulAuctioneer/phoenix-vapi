import asyncio
import logging
import signal
from services.event_manager import EventManager
from services.audio_service import AudioService
from services.wake_word import WakeWordService
from services.conversation import ConversationService
from services.led_service import LEDService

async def main():
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Create event manager
    event_manager = EventManager()
    
    # Create and register services in order
    services = [
        AudioService(event_manager),        # Initialize audio first
        WakeWordService(event_manager),     # Then wake word detection
        ConversationService(event_manager), # Then conversation handling
        LEDService(event_manager),          # Finally LED control
    ]
    
    # Start all services
    for service in services:
        await service.start()
        
    # Setup signal handlers for graceful shutdown
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown(services)))
        
    # Keep the main task running
    try:
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass

async def shutdown(services):
    """Gracefully shutdown all services"""
    logging.info("Shutting down...")
    
    # Stop services in reverse order
    for service in reversed(services):
        try:
            await service.stop()
        except Exception as e:
            logging.error(f"Error stopping service {service.__class__.__name__}: {e}")
            
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