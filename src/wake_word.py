import logging
import pvporcupine
import pyaudio
import struct
import os
from dotenv import load_dotenv

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
        self.audio = None
        self.stream = None
        self.running = False
        
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
        
        # Handle keyword selection
        if keyword_path is not None:
            # Use custom keyword file
            if not os.path.exists(keyword_path):
                raise ValueError(f"Custom keyword file not found: {keyword_path}")
            self.wake_word = os.path.basename(keyword_path)
            # Initialize Porcupine with keyword_paths for custom wake word
            self.porcupine = pvporcupine.create(
                access_key=self.access_key,
                keyword_paths=[keyword_path]
            )
        else:
            # Use built-in keyword
            keyword = keyword or "porcupine"  # Default to "porcupine" if no keyword specified
            if keyword not in pvporcupine.KEYWORDS:
                available_keywords = ", ".join(sorted(pvporcupine.KEYWORDS))
                raise ValueError(
                    f"Keyword '{keyword}' not found. Available keywords:\n{available_keywords}"
                )
            self.wake_word = keyword
            # Initialize Porcupine with keywords for built-in wake word
            self.porcupine = pvporcupine.create(
                access_key=self.access_key,
                keywords=[keyword]
            )
            
        # Initialize PyAudio
        self.audio = pyaudio.PyAudio()
        
    def start(self):
        """Start listening for wake word"""
        if self.running:
            return
            
        try:
            # Validate audio format requirements
            if self.porcupine.sample_rate != 16000:  # Standard Porcupine sample rate
                raise ValueError(f"Porcupine requires 16kHz sample rate")
                
            self.stream = self.audio.open(
                rate=self.porcupine.sample_rate,
                channels=1,  # Porcupine requires single-channel audio
                format=pyaudio.paInt16,  # Porcupine requires 16-bit encoding
                input=True,
                frames_per_buffer=self.porcupine.frame_length
            )
            
            self.running = True
            
            # Main processing loop
            while self.running:
                pcm = self.stream.read(self.porcupine.frame_length, exception_on_overflow=False)
                pcm = struct.unpack_from("h" * self.porcupine.frame_length, pcm)
                
                # Process with Porcupine
                keyword_index = self.porcupine.process(pcm)
                
                # If wake word detected (keyword_index >= 0)
                if keyword_index >= 0:
                    logging.info(f"Wake word '{self.wake_word}' detected!")
                    self.callback_fn()
                    
        except Exception as e:
            logging.error(f"Error in audio processing: {e}")
        finally:
            self.stop()
            
    def stop(self):
        """Stop listening and clean up"""
        logging.info("Stopping wake word detection")
        self.running = False
        
        if hasattr(self, 'porcupine') and self.porcupine:
            self.porcupine.delete()
            self.porcupine = None
            
        if hasattr(self, 'stream') and self.stream:
            self.stream.stop_stream()
            self.stream.close()
            self.stream = None
            
        if hasattr(self, 'audio') and self.audio:
            self.audio.terminate()
            self.audio = None
            
        logging.info("Wake word detection stopped")
            
    def __del__(self):
        self.stop() 