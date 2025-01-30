import logging
import asyncio
from typing import Dict, Any
from .base import BaseService
from wake_word import WakeWordDetector
from config import PICOVOICE_ACCESS_KEY, WAKE_WORD_PATH
import threading
import queue
import sys

class WakeWordService(BaseService):
    """Handles wake word detection"""
    def __init__(self, manager):
        super().__init__(manager)
        self.detector = None
        self._retry_count = 0
        self._max_retries = 3
        self._detector_thread = None
        self._error_queue = queue.Queue()
        self._loop = None  # Store the event loop for thread-safe callbacks
        
    def _run_detector(self):
        """Run the detector in a thread"""
        try:
            logging.info("Starting wake word detector thread")
            self.detector.start()
            logging.info("Wake word detector thread completed normally")
        except Exception as e:
            if self._running:  # Only log error if we haven't stopped intentionally
                logging.error(f"Error in wake word detector thread: {e}")
                self._error_queue.put(sys.exc_info())
        
    async def start(self):
        await super().start()
        self._loop = asyncio.get_running_loop()  # Store the event loop
        await self.setup_detector()
        if self.detector:
            # Start detector in a thread
            self._detector_thread = threading.Thread(target=self._run_detector)
            self._detector_thread.daemon = True
            self._detector_thread.start()
            
            # Check for immediate startup errors
            await asyncio.sleep(1)
            if not self._error_queue.empty():
                exc_info = self._error_queue.get()
                await self.cleanup_detector()
                raise exc_info[1].with_traceback(exc_info[2])
            
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
                logging.info("Stopping wake word detector...")
                self.detector.stop()
                
                if self._detector_thread and self._detector_thread.is_alive():
                    logging.info("Waiting for detector thread to finish...")
                    self._detector_thread.join(timeout=2)
                    if self._detector_thread.is_alive():
                        logging.error("Detector thread did not stop cleanly!")
                
                await asyncio.sleep(0.5)  # Add small delay after stopping
                
                # Clear error queue
                while not self._error_queue.empty():
                    self._error_queue.get()
                
            except Exception as e:
                logging.error(f"Error stopping detector: {e}")
            finally:
                self.detector = None
                self._detector_thread = None
            
    def on_wake_word(self):
        """Handle wake word detection - called from detector thread"""
        if not self._running or not self._loop:
            return
            
        # Stop detection immediately from the thread
        logging.info("Wake word detected, pausing detection")
        if self.detector:
            self.detector.stop()
            
        # Schedule the async event publishing in the event loop
        async def publish_wake_word_event():
            await self.manager.publish_event({
                "type": "wake_word_detected"
            })
            
        self._loop.call_soon_threadsafe(
            lambda: asyncio.create_task(publish_wake_word_event())
        )
            
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
                        # Start detector in a thread
                        self._detector_thread = threading.Thread(target=self._run_detector)
                        self._detector_thread.daemon = True
                        self._detector_thread.start()
                        
                        # Check for immediate startup errors
                        await asyncio.sleep(1)
                        if not self._error_queue.empty():
                            exc_info = self._error_queue.get()
                            await self.cleanup_detector()
                            raise exc_info[1].with_traceback(exc_info[2])
                            
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
                            self._detector_thread = threading.Thread(target=self._run_detector)
                            self._detector_thread.daemon = True
                            self._detector_thread.start()
                            
                            # Check for immediate startup errors
                            await asyncio.sleep(1)
                            if not self._error_queue.empty():
                                exc_info = self._error_queue.get()
                                await self.cleanup_detector()
                                raise exc_info[1].with_traceback(exc_info[2])
                    else:
                        logging.error("Max retries reached for wake word initialization")
                        # Notify other services about the failure
                        await self.manager.publish_event({
                            "type": "wake_word_error",
                            "error": "Failed to initialize wake word detection after multiple retries"
                        }) 