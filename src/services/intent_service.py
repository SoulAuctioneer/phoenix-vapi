import logging
import asyncio
from typing import Dict, Any, Optional
from services.service import BaseService
from managers.speech_intent_manager import SpeechIntentManager
from config import PICOVOICE_ACCESS_KEY, IntentConfig

class IntentService(BaseService):
    """
    Service that manages intent detection.
    Currently only supports speech-to-intent detection using Rhino.
    Coordinates with SpeechIntentManager to process spoken commands, and emits intent events.
    Intent detection is activated by wake word events and times out after several seconds.
    """
    def __init__(self, manager):
        super().__init__(manager)
        self.detector = None
        self.detection_task: Optional[asyncio.Task] = None
        
    async def start(self):
        """Start the speech intent service"""
        await super().start()
        # Initialize detector but don't start it yet
        await self.setup_detector()
        
    async def stop(self):
        """Stop the speech intent service"""
        await self.cleanup_detector()
        if self.detection_task:
            self.detection_task.cancel()
            try:
                await self.detection_task
            except asyncio.CancelledError:
                pass
            self.detection_task = None
        await super().stop()
        
    async def setup_detector(self):
        """Initialize the speech intent detector"""
        await self.cleanup_detector()  # Clean up any existing detector
        try:
            logging.info("Using context from: %s", IntentConfig.CONTEXT_PATH)
            # Add delay before initialization to allow audio device to fully release
            await asyncio.sleep(1.5)
            
            # Create the detector but don't start it yet
            self.detector = await SpeechIntentManager.create(
                on_intent=self._handle_intent_detected  # Pass callback for intent detection
            )
            
            logging.info("Speech intent detector initialized successfully")
            
        except Exception as e:
            logging.error("Failed to initialize speech intent detector: %s", str(e), exc_info=True)
            raise
            
    async def cleanup_detector(self):
        """Clean up the speech intent detector"""
        if self.detector:
            try:
                logging.info("Stopping speech intent detector...")
                await self.detector.stop()
                await asyncio.sleep(0.5)  # Add small delay after stopping
                
            except Exception as e:
                logging.error(f"Error stopping detector: {e}")
            finally:
                self.detector = None

    async def start_detection_timeout(self):
        """Start intent detection with timeout"""
        if self.detection_task and not self.detection_task.done():
            # Cancel any existing detection task
            self.detection_task.cancel()
            try:
                await self.detection_task
            except asyncio.CancelledError:
                pass

        try:
            # Start the detector
            await self.detector.start()
            logging.info("Started intent detection with %s second timeout", IntentConfig.DETECTION_TIMEOUT)
            
            # Publish event that intent detection has started
            await self.publish({
                "type": "intent_detection_started",
                "timeout": IntentConfig.DETECTION_TIMEOUT
            })
            
            # Wait for timeout
            await asyncio.sleep(IntentConfig.DETECTION_TIMEOUT)
            
            # If we reach here, timeout occurred
            logging.info("Intent detection timed out")
            await self.detector.stop()
            
            # Publish timeout event
            await self.publish({
                "type": "intent_detection_timeout"
            })
            
        except asyncio.CancelledError:
            # Task was cancelled (either by timeout or intent detection)
            logging.info("Intent detection cancelled")
            await self.detector.stop()
            raise
        finally:
            self.detection_task = None
            
    async def handle_event(self, event: Dict[str, Any]):
        """
        Handle events from other services.
        Starts intent detection on wake word events.
        """
        event_type = event.get("type")
        
        if event_type == "wake_word_detected":
            logging.info("Wake word detected, starting intent detection")
            if not self.detection_task or self.detection_task.done():
                self.detection_task = asyncio.create_task(self.start_detection_timeout())
                
    async def _handle_intent_detected(self, intent_data: Dict[str, Any]):
        """Callback handler for when an intent is detected by the manager"""
        logging.info("Intent detected, stopping detection")
        
        # Publish the intent event
        await self.publish({
            "type": "intent_detected",
            "intent": intent_data["intent"],
            "slots": intent_data["slots"]
        })
        
        # Stop the detection task
        if self.detection_task and not self.detection_task.done():
            # Create a new task for cancellation to avoid blocking
            cancel_task = asyncio.create_task(self._cancel_detection_task())
            try:
                await cancel_task
            except Exception as e:
                logging.error(f"Error cancelling detection task: {e}")
                
    async def _cancel_detection_task(self):
        """Helper method to safely cancel the detection task"""
        try:
            self.detection_task.cancel()
            await self.detection_task
        except asyncio.CancelledError:
            # This is expected when cancelling
            pass
        except Exception as e:
            logging.error(f"Unexpected error while cancelling detection task: {e}")
        finally:
            self.detection_task = None