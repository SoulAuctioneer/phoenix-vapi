# Configure logging
import logging
logging.basicConfig(
    level=logging.DEBUG,  # Set to DEBUG for more detailed logging
    format='%(asctime)s - [%(filename)s:%(lineno)d] - %(levelname)s - %(message)s'
)

import asyncio
import os
from services.audio_service import AudioService
from services.service import ServiceManager

async def main():
    # Create a service manager
    logging.info("Creating ServiceManager")
    manager = ServiceManager()
    
    # Create and start the audio service
    logging.info("Creating AudioService")
    audio_service = AudioService(manager)
    
    logging.info("Starting AudioService")
    await audio_service.start()
    
    try:
        # Verify the WAV file exists
        wav_path = "assets/yawn.wav"
        if not os.path.exists(wav_path):
            raise FileNotFoundError(f"WAV file not found: {wav_path}")
        logging.info(f"Found WAV file: {wav_path}")
        
        # Play the yawn sound
        logging.info("Sending play_sound event...")
        await audio_service.handle_event({
            "type": "play_sound",
            "wav_path": wav_path,
            "producer_name": "test_yawn"
        })
        
        # Wait longer to ensure we see the full lifecycle
        logging.info("Waiting for sound to complete...")
        for i in range(10):  # Wait up to 10 seconds
            logging.debug(f"Still waiting... ({i+1}/10)")
            await asyncio.sleep(1)
        
    finally:
        # Stop the audio service
        logging.info("Stopping audio service...")
        await audio_service.stop()
        logging.info("Audio service stopped")

if __name__ == "__main__":
    try:
        asyncio.run(main())
        logging.info("Test completed successfully")
    except KeyboardInterrupt:
        logging.info("Test interrupted by user")
    except Exception as e:
        logging.error(f"Test failed: {e}", exc_info=True) 