import logging
import pvporcupine
import numpy as np
import os
import asyncio
from managers.audio_manager import AudioManager
import threading
from config import PICOVOICE_ACCESS_KEY, WakeWordConfig
from typing import Callable, Awaitable, Optional

class WakeWordManager:
    """
    Handles wake word detection using Porcupine.
    Uses callback to notify service of wake word detection rather than publishing events directly.
    """
    def __init__(self, audio_manager, *, on_wake_word: Optional[Callable[[], Awaitable[None]]] = None):
        self.audio_manager = audio_manager
        self.on_wake_word = on_wake_word
        self.running = False
        self._audio_consumer = None
        self._lock = threading.Lock()
        self._remainder = np.array([], dtype=np.int16)  # Store remainder samples
        self._loop = None  # Store event loop reference
        
        # Initialize Porcupine
        try:
            access_key = PICOVOICE_ACCESS_KEY
            if not access_key:
                raise ValueError("Picovoice access key not found in environment")
                
            if WakeWordConfig.WAKE_WORD_BUILTIN:
                self.porcupine = pvporcupine.create(
                    access_key=access_key,
                    keywords=[WakeWordConfig.WAKE_WORD_BUILTIN]
                )
            else:
                self.porcupine = pvporcupine.create(
                    access_key=access_key,
                    keyword_paths=[WakeWordConfig.MODEL_PATH]
                )
            logging.info("Porcupine initialized successfully")
        except Exception as e:
            logging.error(f"Failed to initialize Porcupine: {e}")
            raise

    @classmethod
    async def create(cls, *, audio_manager=None, on_wake_word: Optional[Callable[[], Awaitable[None]]] = None):
        """Factory method to create and initialize a WakeWordManager instance"""
        if audio_manager is None:
            audio_manager = AudioManager.get_instance()
        instance = cls(audio_manager, on_wake_word=on_wake_word)
        return instance

    async def start(self):
        """Start wake word detection"""
        if self.running:
            return

        try:
            self.running = True
            # Store the event loop reference from the main thread
            self._loop = asyncio.get_running_loop()
            # Register as an audio consumer without specifying chunk size
            self._audio_consumer = self.audio_manager.add_consumer(
                self._process_audio
            )
            logging.info("Wake word detection started")

        except Exception as e:
            logging.error(f"Error starting wake word detection: {e}")
            await self.cleanup()
            raise

    def _process_audio(self, audio_data: np.ndarray):
        """Process audio data from the audio manager"""
        if not self.running:
            return
            
        try:
            # Combine with any remainder from last time
            if len(self._remainder) > 0:
                audio_data = np.concatenate([self._remainder, audio_data])
                
            # Process complete frames
            frame_length = self.porcupine.frame_length
            num_complete_frames = len(audio_data) // frame_length
            
            for i in range(num_complete_frames):
                start = i * frame_length
                end = start + frame_length
                frame = audio_data[start:end]
                
                # Process the frame
                result = self.porcupine.process(frame)
                if result >= 0:
                    self._handle_wake_word_detected()
                    
            # Store remainder samples for next time
            remainder_start = num_complete_frames * frame_length
            self._remainder = audio_data[remainder_start:]
            
        except Exception as e:
            logging.error(f"Error processing audio in wake word detection: {e}")

    async def stop(self):
        """Stop wake word detection"""
        if not self.running:
            return

        logging.info("Stopping wake word detection")
        self.running = False  # Set this first to ensure the processing loop exits cleanly
        await asyncio.sleep(0.1)  # Give the processing loop time to exit
        await self.cleanup()

    async def cleanup(self):
        """Clean up resources"""
        logging.info("Cleaning up wake word detection resources")
        self.running = False

        # Remove audio consumer
        if self._audio_consumer is not None:
            self.audio_manager.remove_consumer(self._audio_consumer)
            self._audio_consumer = None

        # Clean up Porcupine
        if self.porcupine:
            try:
                self.porcupine.delete()
            except Exception as e:
                logging.error(f"Error cleaning up Porcupine: {e}")
            finally:
                self.porcupine = None

        logging.info("Wake word detection cleanup completed")

    async def __aenter__(self):
        """Async context manager entry"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.cleanup()

    def _handle_wake_word_detected(self):
        """Handle wake word detection by calling the callback if provided"""
        logging.info("Wake word detected!")
        if self.on_wake_word and self._loop is not None:
            self._loop.call_soon_threadsafe(
                lambda: asyncio.create_task(self.on_wake_word())
            ) 