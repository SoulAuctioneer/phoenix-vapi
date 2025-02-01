import logging
import asyncio
from typing import Dict, Any
from services.service import BaseService
from managers.wakeword_manager import WakeWordManager
from config import PICOVOICE_ACCESS_KEY, WAKE_WORD_PATH

class WakeWordService(BaseService):
    """Handles wake word detection"""
    def __init__(self, manager):
        super().__init__(manager)
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
            logging.info("Using wake word from: %s", WAKE_WORD_PATH)
            # Add delay before initialization to allow audio device to fully release
            await asyncio.sleep(1.5)
            
            # Create and initialize the detector
            self.detector = await WakeWordManager.create(
                manager=self.manager,  # Pass the manager for direct event publishing
                access_key=PICOVOICE_ACCESS_KEY,
                keyword_path=WAKE_WORD_PATH
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
        # We no longer need to handle conversation_ended since we keep running
        pass 