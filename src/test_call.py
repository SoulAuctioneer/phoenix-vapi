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

SAMPLE_RATE = 16000
NUM_CHANNELS = 1

class AudioManager:
    _instance = None
    _virtual_mic = None
    _virtual_speaker = None
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = pyaudio.PyAudio()
            # Create virtual devices
            cls._virtual_mic = daily.Daily.create_microphone_device(
                "virtual-mic",
                sample_rate=SAMPLE_RATE,
                channels=NUM_CHANNELS,
                non_blocking=True  # Important for preventing blocking issues
            )
            cls._virtual_speaker = daily.Daily.create_speaker_device(
                "virtual-speaker",
                sample_rate=SAMPLE_RATE,
                channels=NUM_CHANNELS
            )
            daily.Daily.select_microphone_device("virtual-mic")
            daily.Daily.select_speaker_device("virtual-speaker")
        return cls._instance
    
    @classmethod
    def cleanup(cls):
        if cls._instance:
            # First release virtual devices
            if cls._virtual_mic:
                daily.Daily.select_microphone_device(None)
                cls._virtual_mic = None
            if cls._virtual_speaker:
                daily.Daily.select_speaker_device(None)
                cls._virtual_speaker = None
            
            # Wait a bit for devices to be released
            time.sleep(0.5)
            
            # Then terminate PyAudio
            cls._instance.terminate()
            cls._instance = None
            time.sleep(0.5)  # Give extra time for cleanup

class MockWakeWordDetector:
    def __init__(self):
        self.running = False
        self.stream = None
        self._audio = None
        
    def start(self):
        """Start listening for wake word"""
        if self.running:
            return
            
        try:
            # Get shared PyAudio instance
            self._audio = AudioManager.get_instance()
            
            # Configure stream with non-blocking callback
            self.stream = self._audio.open(
                rate=SAMPLE_RATE,
                channels=NUM_CHANNELS,
                format=pyaudio.paInt16,
                input=True,
                output=False,  # We only need input for wake word
                frames_per_buffer=512,
                stream_callback=self._audio_callback,
                start=False  # Don't start immediately
            )
            
            # Start stream after configuration
            self.stream.start_stream()
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
        if self.running and AudioManager._virtual_mic:
            # Write to virtual microphone if we're running
            AudioManager._virtual_mic.write_frames(in_data)
        return (None, pyaudio.paContinue)
        
    def stop(self):
        """Stop listening and clean up"""
        logging.info("Stopping wake word detection")
        self.running = False
        
        if self.stream:
            try:
                self.stream.stop_stream()
                time.sleep(0.1)  # Small delay before closing
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
            
            # Add delay after stopping detector
            await asyncio.sleep(0.5)
            
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
                
                # Wait between calls with longer delay
                if i < 1:  # Don't wait after last call
                    logging.info("Waiting 3 seconds before next wake word detection...")
                    await asyncio.sleep(3)
                    
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
                    await asyncio.sleep(0.5)  # Give time for detector cleanup
                except Exception as e:
                    logging.error(f"Error stopping detector: {e}")
                detector = None
            
            # 3. Clean up audio resources
            try:
                AudioManager.cleanup()
                await asyncio.sleep(1.0)  # Give more time for audio resources to clean up
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