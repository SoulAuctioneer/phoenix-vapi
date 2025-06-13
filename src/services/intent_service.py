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
        # Only do full cleanup if we don't have a detector yet, otherwise preserve Rhino
        if self.detector is None:
            await self.cleanup_detector(full_cleanup=True)  # Clean up any existing detector
        else:
            await self.cleanup_detector(full_cleanup=False)  # Just stop, preserve Rhino
            
        try:
            # Only create new detector if we don't have one, otherwise reuse
            if self.detector is None:
                # Add delay before initialization to allow audio device to fully release
                await asyncio.sleep(1.5)
                
                # Create the detector but don't start it yet
                self.detector = await SpeechIntentManager.create(
                    on_intent=self._handle_intent_detected
                )
                
                self.logger.info("Speech intent detector initialized successfully")
            else:
                self.logger.info("Reusing existing speech intent detector")
            
        except Exception as e:
            logging.error("Failed to initialize speech intent detector: %s", str(e), exc_info=True)
            raise
            
    async def cleanup_detector(self, full_cleanup=True):
        """
        Clean up the speech intent detector
        
        Args:
            full_cleanup: If True, fully destroys the detector including Rhino instance.
                         If False, just stops detection but preserves Rhino for reuse.
        """
        if self.detector:
            try:
                self.logger.info("Stopping speech intent detector...")
                if full_cleanup:
                    # Full cleanup - destroy the Rhino instance
                    await self.detector.cleanup(full_cleanup=True)
                else:
                    # Just stop detection, keep Rhino alive
                    await self.detector.stop()
                await asyncio.sleep(0.5)  # Add small delay after stopping
                
            except Exception as e:
                logging.error(f"Error stopping detector: {e}")
            finally:
                if full_cleanup:
                    self.detector = None

    async def start_detection_timeout(self):
        """Start intent detection with timeout"""
        try:
            # Start the detector
            await self.detector.start()
            self.logger.info("Started intent detection with %s second timeout", IntentConfig.DETECTION_TIMEOUT)
            
            # Publish event that intent detection has started
            await self.publish({
                "type": "intent_detection_started",
                "timeout": IntentConfig.DETECTION_TIMEOUT
            })

            # Start the LED effect
            await self.publish({
                "type": "start_led_effect",
                "data": {
                    "effect_name": "rotating_pink_blue",
                    "speed": 0.02,
                }
            })
            
            # Wait for timeout
            try:
                await asyncio.sleep(IntentConfig.DETECTION_TIMEOUT)
                # If we reach here, timeout occurred
                self.logger.info("Intent detection timed out")
                await self.publish({
                    "type": "intent_detection_timeout"
                })

                # Stop LED effect
                await self.publish({
                    "type": "stop_led_effect",
                    "data": {
                        "effect_name": "rotating_pink_blue"
                    }
                })
            except asyncio.CancelledError:
                # Task was cancelled (either by timeout or intent detection)
                self.logger.info("Intent detection cancelled")
                raise  # Re-raise to trigger cleanup
                
        except asyncio.CancelledError:
            # Handle cancellation cleanup
            self.logger.info("Cleaning up cancelled detection")
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
            self.logger.info("Wake word detected, starting intent detection")
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
        self.logger.info("Intent detected, stopping detection")

        # Stop LED effect
        await self.publish({
            "type": "stop_led_effect",
            "data": {
                "effect_name": "rotating_pink_blue"
            }
        })

        # Re-map old intent names to new ones
        intent = intent_data["intent"]
        if intent == "wake_up":
            intent = "conversation"

        # Re-map volume intents
        if intent == "custom_command":
            slots = intent_data.get("slots", {})
            if slots and "index" in slots:
                index_val = int(slots["index"])
                if index_val == 0:
                    intent = "shut_down"
                elif index_val == 1:
                    intent = "volume_down"
                elif index_val == 2:
                    intent = "volume_up"
                elif index_val == 3:
                    intent = "squealing"
                elif index_val == 4:
                    intent = "first_contact"
        elif intent == "volume":
            slots = intent_data.get("slots", {})
            if slots:
                if "level" in slots:
                    intent = "volume_level"
                    # Keep the level slot value for volume_level intent
                elif "command" in slots:
                    command = slots["command"].lower()
                    if command == "down":
                        intent = "volume_down"
                    elif command == "up":
                        intent = "volume_up"
                    elif command == "off":
                        intent = "volume_off"
                    elif command == "on":
                        intent = "volume_on"
        elif intent == "hide_and_seek":
            intent = "scavenger_hunt"

        # Publish the intent event first
        await self.publish({
            "type": "intent_detected",
            "intent": intent,
            # Unpack any other data from intent_data except "intent"
            **{k: v for k, v in intent_data.items() if k != "intent"}
        })
        
        # Then cancel the detection task if it exists
        if self.detection_task and not self.detection_task.done():
            self.detection_task.cancel()
            # Don't await the task here to avoid potential deadlocks
            self.detection_task = None