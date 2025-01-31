import logging
import pvporcupine
import numpy as np
import os
from dotenv import load_dotenv
import time
import threading
from services.audio_manager import AudioManager

class WakeWordDetector:
    def __init__(self, callback_fn=None, access_key=None, keyword=None, keyword_path=None):
        """
        Initialize the wake word detector using Porcupine.
        
        :param callback_fn: Function to call when wake word is detected
        :param access_key: Picovoice access key (from console.picovoice.ai)
        :param keyword: Built-in wake word to use (must be one of pvporcupine.KEYWORDS)
        :param keyword_path: Path to custom keyword file (ppn file)
        """
        # Initialize instance variables first to prevent cleanup errors
        self.porcupine = None
        self.running = False
        self._cleanup_lock = threading.Lock()  # Add lock for cleanup synchronization
        self._audio_consumer = None
        
        load_dotenv()
        self.callback_fn = callback_fn or (lambda: None)
        
        # Get access key from environment or parameter
        self.access_key = access_key or os.getenv('PICOVOICE_ACCESS_KEY')
        if not self.access_key:
            raise ValueError(
                "Picovoice access key is required. Get one from console.picovoice.ai\n"
                "Then either:\n"
                "1. Set it in your .env file as PICOVOICE_ACCESS_KEY=your_key_here\n"
                "2. Pass it directly to WakeWordDetector(access_key='your_key_here')"
            )
        
        try:
            # Initialize Porcupine first
            if keyword_path is not None:
                if not os.path.exists(keyword_path):
                    raise ValueError(f"Custom keyword file not found: {keyword_path}")
                self.wake_word = os.path.basename(keyword_path)
                self.porcupine = pvporcupine.create(
                    access_key=self.access_key,
                    keyword_paths=[keyword_path]
                )
            else:
                keyword = keyword or "porcupine"
                if keyword not in pvporcupine.KEYWORDS:
                    available_keywords = ", ".join(sorted(pvporcupine.KEYWORDS))
                    raise ValueError(
                        f"Keyword '{keyword}' not found. Available keywords:\n{available_keywords}"
                    )
                self.wake_word = keyword
                self.porcupine = pvporcupine.create(
                    access_key=self.access_key,
                    keywords=[keyword]
                )
                
            # Get audio manager instance
            self.audio_manager = AudioManager.get_instance()
                
        except Exception as e:
            self.cleanup()
            raise e

    def process_audio(self, audio_data: np.ndarray):
        """Process audio data from the audio manager"""
        if not self.running:
            return
            
        try:
            # Audio is already in int16 format, just pass it through
            keyword_index = self.porcupine.process(audio_data)
            
            # If wake word detected (keyword_index >= 0)
            if keyword_index >= 0:
                logging.info(f"Wake word '{self.wake_word}' detected!")
                self.callback_fn()  # This will publish the wake_word_detected event
                
        except Exception as e:
            if self.running:  # Only log if we're not intentionally stopping
                logging.error(f"Error processing audio: {e}")
                if logging.getLogger().isEnabledFor(logging.DEBUG):
                    logging.debug(f"Audio data shape: {audio_data.shape}, dtype: {audio_data.dtype}, range: [{audio_data.min()}, {audio_data.max()}]")

    def start(self):
        """Start listening for wake word"""
        if self.running:
            return
            
        try:
            self.running = True
            # Register as an audio consumer with specific chunk size
            self._audio_consumer = self.audio_manager.add_consumer(
                self.process_audio,
                chunk_size=self.porcupine.frame_length
            )
            logging.info("Wake word detection started")
            
        except Exception as e:
            logging.error(f"Error starting wake word detection: {e}")
            self.cleanup()
            raise

    def cleanup(self):
        """Clean up resources thoroughly"""
        with self._cleanup_lock:  # Ensure only one cleanup process runs at a time
            logging.info("Cleaning up wake word detection resources")
            self.running = False
            
            # Remove audio consumer
            if self._audio_consumer is not None:
                self.audio_manager.remove_consumer(self._audio_consumer)
                self._audio_consumer = None
                    
            # Clean up Porcupine
            if hasattr(self, 'porcupine') and self.porcupine:
                try:
                    self.porcupine.delete()
                except Exception as e:
                    logging.error(f"Error cleaning up Porcupine: {e}")
                finally:
                    self.porcupine = None
                    
            logging.info("Wake word detection cleanup completed")
            
    def stop(self):
        """Stop listening and clean up"""
        logging.info("Stopping wake word detection")
        self.running = False  # Set this first to ensure the processing loop exits cleanly
        time.sleep(0.1)  # Give the processing loop time to exit
        self.cleanup()
        
    def __del__(self):
        self.cleanup() 