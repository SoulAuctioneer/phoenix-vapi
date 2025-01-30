import logging
import asyncio
from typing import Dict, Any
from .base import BaseService
from wake_word import WakeWordDetector
from config import PICOVOICE_ACCESS_KEY, WAKE_WORD_PATH

class WakeWordService(BaseService):
    """Handles wake word detection"""
    def __init__(self, manager):
        super().__init__(manager)
        self.detector = None
        
    async def start(self):
        await super().start()
        await self.setup_detector()
        if self.detector:
            self.detector.start()
            
    async def stop(self):
        await self.cleanup_detector()
        await super().stop()
        
    async def setup_detector(self):
        """Initialize the wake word detector"""
        await self.cleanup_detector()  # Clean up any existing detector
        try:
            logging.info("Using wake word from: %s", WAKE_WORD_PATH)
            self.detector = WakeWordDetector(
                callback_fn=self.on_wake_word,
                access_key=PICOVOICE_ACCESS_KEY,
                keyword_path=WAKE_WORD_PATH,
            )
            logging.info("Wake word detector initialized successfully")
        except Exception as e:
            logging.error("Failed to initialize wake word detector: %s", str(e), exc_info=True)
            raise
            
    async def cleanup_detector(self):
        """Clean up the wake word detector"""
        if self.detector:
            try:
                self.detector.stop()
            except Exception as e:
                logging.error(f"Error stopping detector: {e}")
            self.detector = None
            
    def on_wake_word(self):
        """Handle wake word detection"""
        if self._running:
            # Pause wake word detection
            logging.info("Wake word detected, pausing detection")
            if self.detector:
                self.detector.stop()
            # Notify other services
            asyncio.create_task(self.manager.publish_event({
                "type": "wake_word_detected"
            }))
            
    async def handle_event(self, event: Dict[str, Any]):
        """Handle events from other services"""
        if event.get("type") == "conversation_ended":
            if self._running:
                logging.info("Conversation ended, reinitializing wake word detection")
                await self.cleanup_detector()  # Ensure cleanup
                await asyncio.sleep(1)  # Add small delay to allow audio device to be released
                try:
                    await self.setup_detector()
                    if self.detector:
                        self.detector.start()
                except Exception as e:
                    logging.error(f"Failed to reinitialize wake word detection: {e}")
                    # Retry once after a longer delay
                    await asyncio.sleep(2)
                    await self.setup_detector()
                    if self.detector:
                        self.detector.start() 