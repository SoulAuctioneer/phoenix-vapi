import logging

# Configure logging first, before any other imports
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

import signal
import sys
import asyncio
from app import App

async def main():
    app = App()
    shutdown_event = asyncio.Event()
    
    def signal_handler(sig, frame):
        logging.info("Stopping Phoenix Assistant...")
        # Use call_soon_threadsafe since we're in a signal handler
        asyncio.get_event_loop().call_soon_threadsafe(shutdown_event.set)
    
    signal.signal(signal.SIGINT, signal_handler)
    
    try:
        logging.info("Starting Phoenix Assistant...")
        # Start app in a separate task
        app_task = asyncio.create_task(app.start())
        
        # Wait for either the app to finish or shutdown signal
        await shutdown_event.wait()
        
        # First attempt graceful shutdown
        logging.info("Initiating graceful shutdown...")
        await asyncio.wait_for(app.cleanup(), timeout=5.0)
        
        # If app task is still running, force cancel it
        if not app_task.done():
            logging.warning("Forcing application shutdown...")
            app_task.cancel()
            try:
                await asyncio.wait_for(app_task, timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            
    except asyncio.TimeoutError:
        logging.error("Shutdown timed out, forcing exit...")
    except Exception as e:
        logging.error(f"Error: {e}", exc_info=True)
    finally:
        # Force exit if we're still here
        sys.exit(0)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Received keyboard interrupt, shutting down...") 