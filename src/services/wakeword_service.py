import logging
import asyncio
from typing import Dict, Any
from .service import BaseService
from managers.wakeword_manager import WakeWordManager
from config import PICOVOICE_ACCESS_KEY, WAKE_WORD_PATH

class WakeWordService(BaseService):
    """Handles wake word detection"""
    def __init__(self, manager):
        super().__init__(manager)
        self.detector = None
        self._loop = None  # Store the event loop for thread-safe callbacks
        
    async def start(self):
        await super().start()
        self._loop = asyncio.get_running_loop()  # Store the event loop
        await self.setup_detector()
        
    async def stop(self):
        await self.cleanup_detector()
        await super().stop()
        
    async def setup_detector(self):
        """Initialize the wake word detector"""
        await self.cleanup_detector()  # Clean up any existing detector
        try:
            logging.info("Using wake word from: %s", WAKE_WORD_PATH)
            # Add delay before initialization to allow audio device to fully release
            await asyncio.sleep(1.5)
            self.detector = WakeWordManager(
                callback_fn=self.on_wake_word,
                access_key=PICOVOICE_ACCESS_KEY,
                keyword_path=WAKE_WORD_PATH,
            )
            logging.info("Wake word detector initialized successfully")
            self.detector.start()
            
        except Exception as e:
            logging.error("Failed to initialize wake word detector: %s", str(e), exc_info=True)
            raise
            
    async def cleanup_detector(self):
        """Clean up the wake word detector"""
        if self.detector:
            try:
                logging.info("Stopping wake word detector...")
                self.detector.stop()
                await asyncio.sleep(0.5)  # Add small delay after stopping
                
            except Exception as e:
                logging.error(f"Error stopping detector: {e}")
            finally:
                self.detector = None
            
    def on_wake_word(self):
        """Handle wake word detection - called from audio thread"""
        if not self._running or not self._loop:
            return
            
        # Create the event to publish
        event = {
            "type": "wake_word_detected"
        }
        
        # Schedule the event publishing in the event loop
        def schedule_publish():
            self.logger.info("Publishing wake word event")
            # Create and return the task
            return asyncio.create_task(self.publish(event))
            
        try:
            # Schedule the task in the event loop
            self._loop.call_soon_threadsafe(schedule_publish)
        except Exception as e:
            self.logger.error(f"Failed to schedule wake word event: {e}", exc_info=True)
            
    async def handle_event(self, event: Dict[str, Any]):
        """Handle events from other services"""
        # We no longer need to handle conversation_ended since we keep running
        pass 