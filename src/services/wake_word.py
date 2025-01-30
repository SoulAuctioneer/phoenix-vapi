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
        self._retry_count = 0
        self._max_retries = 3
        
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
            # Add delay before initialization to allow audio device to fully release
            await asyncio.sleep(1.5)
            self.detector = WakeWordDetector(
                callback_fn=self.on_wake_word,
                access_key=PICOVOICE_ACCESS_KEY,
                keyword_path=WAKE_WORD_PATH,
            )
            logging.info("Wake word detector initialized successfully")
            self._retry_count = 0  # Reset retry count on successful initialization
        except Exception as e:
            logging.error("Failed to initialize wake word detector: %s", str(e), exc_info=True)
            raise
            
    async def cleanup_detector(self):
        """Clean up the wake word detector"""
        if self.detector:
            try:
                self.detector.stop()
                await asyncio.sleep(0.5)  # Add small delay after stopping
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
                
                # Implement exponential backoff for retries
                retry_delay = min(1.5 * (self._retry_count + 1), 5.0)
                await asyncio.sleep(retry_delay)  # Add increasing delay between retries
                
                try:
                    await self.setup_detector()
                    if self.detector:
                        self.detector.start()
                        self._retry_count = 0  # Reset retry count on success
                except Exception as e:
                    logging.error(f"Failed to reinitialize wake word detection: {e}")
                    self._retry_count += 1
                    
                    if self._retry_count < self._max_retries:
                        logging.info(f"Retrying initialization (attempt {self._retry_count + 1}/{self._max_retries})")
                        # Try again with exponential backoff
                        retry_delay = min(2.0 * (self._retry_count + 1), 8.0)
                        await asyncio.sleep(retry_delay)
                        await self.setup_detector()
                        if self.detector:
                            self.detector.start()
                    else:
                        logging.error("Max retries reached for wake word initialization")
                        # Notify other services about the failure
                        await self.manager.publish_event({
                            "type": "wake_word_error",
                            "error": "Failed to initialize wake word detection after multiple retries"
                        }) 