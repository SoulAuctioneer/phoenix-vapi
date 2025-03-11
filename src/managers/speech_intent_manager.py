import logging
import pvrhino
import numpy as np
import asyncio
import threading
from managers.audio_manager import AudioManager
from config import PICOVOICE_ACCESS_KEY, IntentConfig
from typing import Callable, Awaitable, Optional, Dict, Any

class SpeechIntentManager:
    """
    Handles speech-to-intent detection using Rhino.
    Processes audio input to detect and understand spoken commands within a defined context.
    Uses callbacks to notify service of detected intents rather than publishing events directly.
    """
    def __init__(self, audio_manager, *, on_intent: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None):
        self.audio_manager = audio_manager
        self.on_intent = on_intent
        self.running = False
        self._audio_consumer = None
        self._lock = threading.Lock()
        self._remainder = np.array([], dtype=np.int16)
        self._loop = None
        self.rhino = None
        self._initialize_rhino()
        
    def _initialize_rhino(self):
        """Initialize or reinitialize the Rhino instance"""
        # Clean up existing instance if any
        if self.rhino:
            try:
                self.rhino.delete()
            except Exception as e:
                logging.error(f"Error cleaning up existing Rhino instance: {e}")
            self.rhino = None
            
        try:
            access_key = PICOVOICE_ACCESS_KEY
            if not access_key:
                raise ValueError("Picovoice access key not found in environment")
                
            self.rhino = pvrhino.create(
                access_key=access_key,
                context_path=IntentConfig.RHINO_MODEL_PATH
            )
            logging.info("Rhino speech-to-intent engine initialized successfully")
        except Exception as e:
            logging.error(f"Failed to initialize Rhino: {e}")
            raise

    @classmethod
    async def create(cls, *, audio_manager=None, on_intent: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None):
        """Factory method to create and initialize a SpeechIntentManager instance"""
        if audio_manager is None:
            audio_manager = AudioManager.get_instance()
        instance = cls(audio_manager, on_intent=on_intent)
        return instance

    async def start(self):
        """Start speech intent detection"""
        if self.running:
            return

        try:
            # Ensure we have a valid Rhino instance
            if self.rhino is None:
                self._initialize_rhino()
                
            self.running = True
            self._loop = asyncio.get_running_loop()
            self._audio_consumer = self.audio_manager.add_consumer(
                self._process_audio
            )
            logging.info("Speech intent detection started")

        except Exception as e:
            logging.error(f"Error starting speech intent detection: {e}")
            await self.cleanup()
            raise

    def _process_audio(self, audio_data: np.ndarray):
        """
        Process audio data from the audio manager
        Detects and processes spoken commands using Rhino
        """
        if not self.running or self.rhino is None:
            return
            
        try:
            # Combine with any remainder from last time
            if len(self._remainder) > 0:
                audio_data = np.concatenate([self._remainder, audio_data])
                
            # Process complete frames
            frame_length = self.rhino.frame_length
            num_complete_frames = len(audio_data) // frame_length
            
            for i in range(num_complete_frames):
                start = i * frame_length
                end = start + frame_length
                frame = audio_data[start:end]
                
                # Process the frame
                is_finalized = self.rhino.process(frame)
                if is_finalized:
                    inference = self.rhino.get_inference()
                    self._handle_inference(inference)
                    
            # Store remainder samples for next time
            remainder_start = num_complete_frames * frame_length
            self._remainder = audio_data[remainder_start:]
            
        except Exception as e:
            logging.error(f"Error processing audio in speech intent detection: {e}")

    def _handle_inference(self, inference):
        """Handle speech intent inference results by calling the callback if provided"""
        if inference.is_understood:
            logging.info(f"Detected intent: {inference.intent}")
            logging.debug(f"With slots: {inference.slots}")
            
            # Create intent data
            intent_data = {
                "intent": inference.intent,
                "slots": inference.slots
            }
            
            # Call the callback in a thread-safe way
            if self.on_intent and self._loop is not None:
                self._loop.call_soon_threadsafe(
                    lambda: asyncio.create_task(
                        self.on_intent(intent_data)
                    )
                )
        else:
            logging.info("Speech command not understood")

    async def stop(self):
        """Stop speech intent detection"""
        if not self.running:
            return

        logging.info("Stopping speech intent detection")
        self.running = False
        await asyncio.sleep(0.1)
        await self.cleanup()

    async def cleanup(self):
        """Clean up resources"""
        logging.info("Cleaning up speech intent detection resources")
        self.running = False

        if self._audio_consumer is not None:
            self.audio_manager.remove_consumer(self._audio_consumer)
            self._audio_consumer = None

        if self.rhino:
            try:
                self.rhino.delete()
            except Exception as e:
                logging.error(f"Error cleaning up Rhino: {e}")
            finally:
                self.rhino = None

        logging.info("Speech intent detection cleanup completed")

    async def __aenter__(self):
        """Async context manager entry"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.cleanup()