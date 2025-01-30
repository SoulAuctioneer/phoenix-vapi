import logging
import pvporcupine
import pyaudio
import struct
import os
from dotenv import load_dotenv
import time

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
            
        # Initialize PyAudio with error handling
        try:
            self.audio = pyaudio.PyAudio()
            # Test if we can get the default input device
            device_info = self.audio.get_default_input_device_info()
            logging.info(f"Using input device: {device_info['name']}")
        except Exception as e:
            logging.error(f"Error initializing audio: {e}")
            self.cleanup()
            raise ValueError("Failed to initialize audio device")

    def start(self):
        """Start listening for wake word"""
        if self.running:
            return
            
        try:
            # Validate audio format requirements
            if self.porcupine.sample_rate != 16000:  # Standard Porcupine sample rate
                raise ValueError(f"Porcupine requires 16kHz sample rate")
                
            # Try to open the stream with specific error handling
            try:
                self.stream = self.audio.open(
                    rate=self.porcupine.sample_rate,
                    channels=1,  # Porcupine requires single-channel audio
                    format=pyaudio.paInt16,  # Porcupine requires 16-bit encoding
                    input=True,
                    frames_per_buffer=self.porcupine.frame_length,
                    input_device_index=None,  # Use default device
                    stream_callback=None  # Use blocking mode for reliability
                )
            except OSError as e:
                logging.error(f"OSError opening audio stream: {e}")
                self.cleanup()
                raise ValueError("Failed to open audio stream - device may be busy")
            except Exception as e:
                logging.error(f"Error opening audio stream: {e}")
                self.cleanup()
                raise
                
            self.running = True
            
            # Main processing loop
            while self.running:
                try:
                    pcm = self.stream.read(self.porcupine.frame_length, exception_on_overflow=False)
                    pcm = struct.unpack_from("h" * self.porcupine.frame_length, pcm)
                    
                    # Process with Porcupine
                    keyword_index = self.porcupine.process(pcm)
                    
                    # If wake word detected (keyword_index >= 0)
                    if keyword_index >= 0:
                        logging.info(f"Wake word '{self.wake_word}' detected!")
                        self.callback_fn()
                except OSError as e:
                    logging.error(f"OSError reading audio stream: {e}")
                    break
                except Exception as e:
                    logging.error(f"Error processing audio: {e}")
                    break
                    
        except Exception as e:
            logging.error(f"Error in audio processing: {e}")
        finally:
            self.cleanup()
            
    def cleanup(self):
        """Clean up resources thoroughly"""
        logging.info("Cleaning up wake word detection resources")
        self.running = False
        
        # Clean up in specific order
        if hasattr(self, 'stream') and self.stream:
            try:
                self.stream.stop_stream()
                time.sleep(0.1)  # Small delay between stop and close
                self.stream.close()
            except Exception as e:
                logging.error(f"Error cleaning up audio stream: {e}")
            finally:
                self.stream = None
                
        if hasattr(self, 'porcupine') and self.porcupine:
            try:
                self.porcupine.delete()
            except Exception as e:
                logging.error(f"Error cleaning up Porcupine: {e}")
            finally:
                self.porcupine = None
                
        if hasattr(self, 'audio') and self.audio:
            try:
                self.audio.terminate()
                time.sleep(0.1)  # Small delay after termination
            except Exception as e:
                logging.error(f"Error terminating PyAudio: {e}")
            finally:
                self.audio = None
                
        logging.info("Wake word detection cleanup completed")
        
    def stop(self):
        """Stop listening and clean up"""
        logging.info("Stopping wake word detection")
        self.cleanup()
        
    def __del__(self):
        self.cleanup() 