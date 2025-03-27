import logging
import asyncio
from typing import Dict, Any, Optional
from services.service import BaseService
from config import IntentConfig

# Import the appropriate intent manager. Use Rhino if model path is set, otherwise use LLM.
if IntentConfig.MODEL_PATH:
    from managers.speech_intent_manager import SpeechIntentManager as SpeechIntentManager
else:
    from managers.llm_intent_manager import LLMIntentManager as SpeechIntentManager


class IntentService(BaseService):
    """
    Service that manages intent detection.
    Currently only supports speech-to-intent but eventually want to support various other ways to detect intent, e.g. with motion sensing etc.
    Uses either Rhino-based SpeechIntentManager or Whisper+GPT-based LLMIntentManager
    depending on platform configuration.
    TODO: This is temporary until I can get a MacOS model for PicoVoice Rhino.
    Coordinates with the manager to process spoken commands, and emits intent events.
    Intent detection is activated by wake word events and times out after several seconds.
    """
    def __init__(self, service_manager):
        super().__init__(service_manager)
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
            # Add delay before initialization to allow audio device to fully release
            await asyncio.sleep(1.5)
            
            # Create the detector but don't start it yet
            self.detector = await SpeechIntentManager.create(
                on_intent=self._handle_intent_detected
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
            try:
                await asyncio.sleep(IntentConfig.DETECTION_TIMEOUT)
                # If we reach here, timeout occurred
                logging.info("Intent detection timed out")
                await self.publish({
                    "type": "intent_detection_timeout"
                })
            except asyncio.CancelledError:
                # Task was cancelled (either by timeout or intent detection)
                logging.info("Intent detection cancelled")
                raise  # Re-raise to trigger cleanup
                
        except asyncio.CancelledError:
            # Handle cancellation cleanup
            logging.info("Cleaning up cancelled detection")
            raise  # Re-raise to ensure proper task cleanup
            
        finally:
            # Always stop the detector
            try:
                await self.detector.stop()
            except Exception as e:
                logging.error(f"Error stopping detector: {e}")
            
    async def handle_event(self, event: Dict[str, Any]):
        """
        Handle events from other services.
        Starts intent detection on wake word events.
        """
        event_type = event.get("type")
        
        if event_type == "wake_word_detected":
            logging.info("Wake word detected, starting intent detection")
            # Cancel any existing task
            if self.detection_task and not self.detection_task.done():
                self.detection_task.cancel()
                try:
                    await self.detection_task
                except asyncio.CancelledError:
                    pass
                self.detection_task = None
                
            # Start new detection task
            self.detection_task = asyncio.create_task(self.start_detection_timeout())
                
    async def _handle_intent_detected(self, intent_data: Dict[str, Any]):
        """Callback handler for when an intent is detected by the manager"""
        logging.info("Intent detected, stopping detection")
        
        # Re-map old intent names to new ones
        intent = intent_data["intent"]
        if intent == "wake_up":
            intent = "conversation"

        # Publish the intent event first
        await self.publish({
            "type": "intent_detected",
            "intent": intent,
            "slots": intent_data["slots"]
        })
        
        # Then cancel the detection task if it exists
        if self.detection_task and not self.detection_task.done():
            self.detection_task.cancel()
            # Don't await the task here to avoid potential deadlocks
            self.detection_task = None