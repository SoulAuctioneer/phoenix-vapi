import asyncio
import logging
import daily
from vapi import Vapi
from config import VAPI_API_KEY, ASSISTANT_ID
import time
import pyaudio

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class AudioManager:
    _instance = None
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = pyaudio.PyAudio()
        return cls._instance
    
    @classmethod
    def cleanup(cls):
        if cls._instance:
            cls._instance.terminate()
            cls._instance = None

class MockWakeWordDetector:
    def __init__(self):
        self.running = False
        self.stream = None
        
    def start(self):
        """Start listening for wake word"""
        if self.running:
            return
            
        try:
            # Get shared PyAudio instance
            audio = AudioManager.get_instance()
            
            # Get default input device info
            device_info = audio.get_default_input_device_info()
            logging.info(f"Using input device: {device_info['name']}")
            
            # Configure stream with device-specific settings
            self.stream = audio.open(
                rate=16000,
                channels=1,
                format=pyaudio.paInt16,
                input=True,
                input_device_index=device_info['index'],
                frames_per_buffer=512,
                stream_callback=self._audio_callback
            )
            
            self.running = True
            logging.info("Audio stream started successfully")
            return True
            
        except Exception as e:
            logging.error(f"Error starting audio stream: {e}")
            self.running = False
            return False
    
    def _audio_callback(self, in_data, frame_count, time_info, status):
        """Handle audio data from the stream"""
        if status:
            logging.warning(f"Audio callback status: {status}")
        return (None, pyaudio.paContinue)
        
    def stop(self):
        """Stop listening and clean up"""
        logging.info("Stopping wake word detection")
        self.running = False
        
        if hasattr(self, 'stream') and self.stream:
            try:
                self.stream.stop_stream()
                self.stream.close()
                self.stream = None
            except Exception as e:
                logging.error(f"Error stopping audio stream: {e}")
            
        logging.info("Wake word detection stopped")

async def test_consecutive_calls():
    # Initialize Daily runtime once at the start
    try:
        daily.Daily.init()
        logging.info("Daily runtime initialized")
    except Exception as e:
        logging.error(f"Failed to initialize Daily runtime: {e}")
        return
    
    detector = None
    vapi = None
    
    try:
        # Initialize wake word detector
        detector = MockWakeWordDetector()
        
        for i in range(2):  # Test two calls
            logging.info(f"Starting wake word detection (Call {i+1})...")
            if not detector.start():
                logging.error("Failed to start wake word detection, aborting test")
                break
            
            # Simulate wake word detection after 2 seconds
            await asyncio.sleep(2)
            
            logging.info("Wake word detected!")
            detector.stop()
            
            try:
                # Start call
                logging.info(f"Starting call {i+1}...")
                vapi = Vapi(api_key=VAPI_API_KEY)
                vapi.start(assistant_id=ASSISTANT_ID)
                
                # Wait for 10 seconds
                logging.info("Waiting for 10 seconds...")
                await asyncio.sleep(10)
                
                # Stop call and cleanup
                logging.info(f"Stopping call {i+1}...")
                vapi.stop()
                del vapi
                vapi = None
                
                # Wait between calls
                if i < 1:  # Don't wait after last call
                    logging.info("Waiting 2 seconds before next wake word detection...")
                    await asyncio.sleep(2)
                    
            except Exception as e:
                logging.error(f"Error during call {i+1}: {e}")
                if vapi:
                    try:
                        vapi.stop()
                    except:
                        pass
                    vapi = None
                break
                
    except Exception as e:
        logging.error(f"Error during test: {str(e)}", exc_info=True)
    finally:
        logging.info("Test complete, cleaning up...")
        try:
            # Final cleanup in specific order
            # 1. Stop any active calls first
            if vapi:
                try:
                    vapi.stop()
                    await asyncio.sleep(0.5)  # Give some time for the call to clean up
                except Exception as e:
                    logging.error(f"Error stopping Vapi: {e}")
                vapi = None
            
            # 2. Stop wake word detection
            if detector:
                try:
                    detector.stop()
                except Exception as e:
                    logging.error(f"Error stopping detector: {e}")
                detector = None
            
            # 3. Clean up audio resources
            try:
                AudioManager.cleanup()
                await asyncio.sleep(0.5)  # Give some time for audio resources to clean up
            except Exception as e:
                logging.error(f"Error cleaning up audio: {e}")
            
            # 4. Finally deinitialize Daily runtime
            try:
                daily.Daily.deinit()
                logging.info("Daily runtime deinitialized")
            except Exception as e:
                logging.error(f"Error deinitializing Daily runtime: {e}")
                
        except Exception as e:
            logging.error(f"Error during final cleanup: {str(e)}", exc_info=True)

if __name__ == "__main__":
    asyncio.run(test_consecutive_calls()) 