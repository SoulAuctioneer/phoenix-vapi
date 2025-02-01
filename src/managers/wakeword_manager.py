import logging
import pvporcupine
import numpy as np
import os
from dotenv import load_dotenv
import asyncio
from managers.audio_manager import AudioManager

class WakeWordManager:
    """Handles wake word detection using Porcupine"""
    def __init__(self, *, manager=None, access_key=None, keyword=None, keyword_path=None):
        # Core attributes
        self.manager = manager
        self.access_key = access_key
        self.keyword = keyword
        self.keyword_path = keyword_path
        
        # Runtime state
        self.porcupine = None
        self.running = False
        self.audio_manager = None
        self._audio_consumer = None
        self.wake_word = None
        self._loop = None  # Store event loop reference

    @classmethod
    async def create(cls, *, manager=None, access_key=None, keyword=None, keyword_path=None):
        """Factory method to create and initialize a WakeWordManager instance"""
        instance = cls(
            manager=manager,
            access_key=access_key,
            keyword=keyword,
            keyword_path=keyword_path
        )
        await instance.initialize()
        return instance

    async def initialize(self):
        """Initialize the wake word detector"""
        try:
            # Store the event loop reference
            self._loop = asyncio.get_running_loop()
            
            # Load environment variables
            load_dotenv()
            
            # Get access key from environment or parameter
            self.access_key = self.access_key or os.getenv('PICOVOICE_ACCESS_KEY')
            if not self.access_key:
                raise ValueError(
                    "Picovoice access key is required. Get one from console.picovoice.ai\n"
                    "Then either:\n"
                    "1. Set it in your .env file as PICOVOICE_ACCESS_KEY=your_key_here\n"
                    "2. Pass it directly to WakeWordManager(access_key='your_key_here')"
                )

            # Initialize Porcupine
            if self.keyword_path is not None:
                if not os.path.exists(self.keyword_path):
                    raise ValueError(f"Custom keyword file not found: {self.keyword_path}")
                self.wake_word = os.path.basename(self.keyword_path)
                self.porcupine = pvporcupine.create(
                    access_key=self.access_key,
                    keyword_paths=[self.keyword_path]
                )
            else:
                self.keyword = self.keyword or "porcupine"
                if self.keyword not in pvporcupine.KEYWORDS:
                    available_keywords = ", ".join(sorted(pvporcupine.KEYWORDS))
                    raise ValueError(
                        f"Keyword '{self.keyword}' not found. Available keywords:\n{available_keywords}"
                    )
                self.wake_word = self.keyword
                self.porcupine = pvporcupine.create(
                    access_key=self.access_key,
                    keywords=[self.keyword]
                )

            # Get audio manager instance
            self.audio_manager = AudioManager.get_instance()
            logging.info("WakeWordManager initialized successfully")

        except Exception as e:
            logging.error(f"Failed to initialize WakeWordManager: {e}")
            await self.cleanup()
            raise

    async def start(self):
        """Start wake word detection"""
        if self.running:
            return

        try:
            self.running = True
            # Register as an audio consumer with specific chunk size
            self._audio_consumer = self.audio_manager.add_consumer(
                self._process_audio,
                chunk_size=self.porcupine.frame_length
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
            # Process audio through Porcupine
            keyword_index = self.porcupine.process(audio_data)
            
            # If wake word detected (keyword_index >= 0)
            if keyword_index >= 0:
                logging.info(f"Wake word '{self.wake_word}' detected!")
                # Schedule the event publishing using stored event loop
                if self.manager and self._loop:
                    self._loop.call_soon_threadsafe(
                        lambda: asyncio.create_task(
                            self.manager.publish({"type": "wake_word_detected"})
                        )
                    )

        except Exception as e:
            if self.running:  # Only log if we're not intentionally stopping
                logging.error(f"Error processing audio: {e}")

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