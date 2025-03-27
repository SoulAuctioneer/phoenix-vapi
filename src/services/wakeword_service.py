import logging
import asyncio
from typing import Dict, Any
from services.service import BaseService
from managers.wakeword_manager import WakeWordManager

class WakeWordService(BaseService):
    """Handles wake word detection"""
    def __init__(self, service_manager):
        super().__init__(service_manager)
        self.detector = None
        
    async def start(self):
        await super().start()
        await self.setup_detector()
        
    async def stop(self):
        await self.cleanup_detector()
        await super().stop()
        
    async def setup_detector(self):
        """Initialize the wake word detector"""
        await self.cleanup_detector()  # Clean up any existing detector
        try:
            # Add delay before initialization to allow audio device to fully release
            await asyncio.sleep(1.5)
            
            # Create and initialize the detector with callback
            self.detector = await WakeWordManager.create(
                on_wake_word=self._handle_wake_word_detected
            )
            
            logging.info("Wake word detector initialized successfully")
            await self.detector.start()
            
        except Exception as e:
            logging.error("Failed to initialize wake word detector: %s", str(e), exc_info=True)
            raise
            
    async def cleanup_detector(self):
        """Clean up the wake word detector"""
        if self.detector:
            try:
                logging.info("Stopping wake word detector...")
                await self.detector.stop()
                await asyncio.sleep(0.5)  # Add small delay after stopping
                
            except Exception as e:
                logging.error(f"Error stopping detector: {e}")
            finally:
                self.detector = None
            
    async def handle_event(self, event: Dict[str, Any]):
        """Handle events from other services"""
        pass  # Wake word detection runs continuously
        
    async def _handle_wake_word_detected(self):
        """Callback handler for when a wake word is detected by the manager"""
        logging.info("Wake word detected, publishing event")
        await self.publish({"type": "wake_word_detected"}) 