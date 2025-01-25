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
            keywords = [keyword_path]
            self.wake_word = os.path.basename(keyword_path)
        else:
            # Use built-in keyword
            keyword = keyword or "porcupine"  # Default to "porcupine" if no keyword specified
            if keyword not in pvporcupine.KEYWORDS:
                available_keywords = ", ".join(sorted(pvporcupine.KEYWORDS))
                raise ValueError(
                    f"Keyword '{keyword}' not found. Available keywords:\n{available_keywords}"
                )
            keywords = [keyword]
            self.wake_word = keyword
            
        # Initialize Porcupine
        try:
            self.porcupine = pvporcupine.create(
                access_key=self.access_key,
                keywords=keywords
            )
            
            # Initialize PyAudio
            self.audio = pyaudio.PyAudio()
            
        except Exception as e:
            self.stop()  # Clean up any partially initialized resources
            print(f"Failed to initialize Porcupine: {e}")
            if "AccessKeyError" in str(e):
                print("Invalid access key. Please check your key at console.picovoice.ai")
            raise
        
    def start(self):
        """Start listening for wake word"""
        if self.running:
            return
            
        self.running = True
        
        try:
            self.stream = self.audio.open(
                rate=self.porcupine.sample_rate,
                channels=1,
                format=pyaudio.paInt16,
                input=True,
                frames_per_buffer=self.porcupine.frame_length,
                stream_callback=self._audio_callback
            )
            self.stream.start_stream()
            
        except Exception as e:
            print(f"Failed to start audio stream: {e}")
            self.running = False
            self.stop()
            raise
            
    def _audio_callback(self, in_data, frame_count, time_info, status):
        """Handle audio input from PyAudio"""
        if status:
            print(f"Audio callback status: {status}")
            
        try:
            # Convert audio data to integers
            pcm = struct.unpack_from("h" * self.porcupine.frame_length, in_data)
            
            # Process with Porcupine
            keyword_index = self.porcupine.process(pcm)
            
            # If wake word detected (keyword_index >= 0)
            if keyword_index >= 0:
                print(f"Wake word '{self.wake_word}' detected!")
                self.callback_fn()
                
        except Exception as e:
            print(f"Error processing audio: {e}")
            
        return (in_data, pyaudio.paContinue)
        
    def stop(self):
        """Stop listening and clean up"""
        self.running = False
        
        if hasattr(self, 'stream') and self.stream:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except Exception as e:
                print(f"Error closing audio stream: {e}")
            self.stream = None
            
        if hasattr(self, 'audio') and self.audio:
            try:
                self.audio.terminate()
            except Exception as e:
                print(f"Error terminating PyAudio: {e}")
            self.audio = None
            
        if hasattr(self, 'porcupine') and self.porcupine:
            try:
                self.porcupine.delete()
            except Exception as e:
                print(f"Error deleting Porcupine instance: {e}")
            self.porcupine = None
            
    def __del__(self):
        self.stop() 