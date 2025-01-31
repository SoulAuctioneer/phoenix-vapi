print("Starting test script...", flush=True)

import logging
import time
import os
import sys
from services.audio_manager import AudioManager, AudioConfig

# Configure logging with immediate output
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - [%(filename)s:%(lineno)d] - %(levelname)s - %(message)s',
    stream=sys.stdout,  # Explicitly log to stdout
    force=True  # Force configuration
)

# Test logging immediately
print("Logging test message...", flush=True)
logging.info("Test logging message")

def main():
    print("Entering main function...", flush=True)
    # Create audio manager
    logging.info("Creating AudioManager")
    config = AudioConfig()
    logging.info(f"Audio config: format={config.format}, channels={config.channels}, rate={config.rate}, chunk={config.chunk}")
    
    manager = AudioManager.get_instance(config)
    
    try:
        # Start the manager
        logging.info("Starting AudioManager")
        manager.start()
        
        # Verify WAV file exists
        wav_path = "assets/yawn.wav"
        if not os.path.exists(wav_path):
            logging.error(f"WAV file not found: {wav_path}")
            return
        logging.info(f"Found WAV file: {wav_path}")
        
        # Play the WAV file
        logging.info("Playing WAV file")
        success = manager.play_wav_file(wav_path, "test_direct")
        if not success:
            logging.error("Failed to start WAV playback")
            return
            
        # Wait for playback to complete (approximately)
        # WAV is 54709 samples at 16kHz = ~3.4 seconds
        wait_time = 5  # Wait a bit longer than the WAV duration
        logging.info(f"Waiting {wait_time} seconds for playback to complete...")
        
        for i in range(wait_time):
            time.sleep(1)
            logging.info(f"Still waiting... ({i+1}/{wait_time})")
            sys.stdout.flush()  # Force flush after each wait message
            
    except Exception as e:
        logging.error(f"Unexpected error: {e}", exc_info=True)
        
    finally:
        # Stop the manager
        logging.info("Stopping AudioManager")
        try:
            manager.stop()
            logging.info("AudioManager stopped")
        except Exception as e:
            logging.error(f"Error stopping AudioManager: {e}", exc_info=True)

if __name__ == "__main__":
    print("Starting main execution...", flush=True)
    try:
        main()
        logging.info("Test completed successfully")
    except KeyboardInterrupt:
        logging.info("Test interrupted by user")
    except Exception as e:
        logging.error(f"Test failed: {e}", exc_info=True)
    print("Script finished.", flush=True) 