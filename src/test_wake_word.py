import asyncio
import logging
from wake_word import WakeWordDetector
from config import PICOVOICE_ACCESS_KEY, WAKE_WORD_PATH
import time
import threading

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def run_detector(detector):
    """Run the detector in a thread"""
    try:
        detector.start()
    except Exception as e:
        logging.error(f"Error in detector thread: {e}")

async def test_wake_word_restart():
    """Test starting, stopping, and restarting wake word detection"""
    detector = None
    detector_thread = None
    
    try:
        # First initialization
        logging.info("=== First Initialization ===")
        detector = WakeWordDetector(
            callback_fn=lambda: logging.info("Wake word detected!"),
            access_key=PICOVOICE_ACCESS_KEY,
            keyword_path=WAKE_WORD_PATH
        )
        logging.info("First detector initialized")
        
        # Start first instance in a thread
        detector_thread = threading.Thread(target=run_detector, args=(detector,))
        detector_thread.daemon = True
        detector_thread.start()
        logging.info("First detector started")
        
        # Wait for a bit
        await asyncio.sleep(10)  # Increased from 5 to 10 seconds
        logging.info("Stopping first detector")
        
        # Stop and cleanup
        detector.stop()
        detector_thread.join(timeout=2)  # Wait for thread to finish
        detector = None
        detector_thread = None
        
        # Wait between instances
        logging.info("Waiting 5 seconds before restarting...")  # Increased from 2 to 5 seconds
        await asyncio.sleep(5)
        
        # Second initialization
        logging.info("\n=== Second Initialization ===")
        detector = WakeWordDetector(
            callback_fn=lambda: logging.info("Wake word detected!"),
            access_key=PICOVOICE_ACCESS_KEY,
            keyword_path=WAKE_WORD_PATH
        )
        logging.info("Second detector initialized")
        
        # Start second instance in a thread
        detector_thread = threading.Thread(target=run_detector, args=(detector,))
        detector_thread.daemon = True
        detector_thread.start()
        logging.info("Second detector started")
        
        # Wait for a bit
        await asyncio.sleep(10)  # Increased from 5 to 10 seconds
        
    except Exception as e:
        logging.error(f"Error during test: {e}", exc_info=True)
    finally:
        # Final cleanup
        if detector:
            logging.info("Final cleanup")
            detector.stop()
            if detector_thread and detector_thread.is_alive():
                detector_thread.join(timeout=2)
            detector = None

if __name__ == "__main__":
    try:
        asyncio.run(test_wake_word_restart())
    except KeyboardInterrupt:
        logging.info("Test interrupted by user")
    except Exception as e:
        logging.error(f"Test failed: {e}", exc_info=True)
    finally:
        logging.info("Test complete") 