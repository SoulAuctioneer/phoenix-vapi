import asyncio
import logging
from wake_word import WakeWordDetector
from config import PICOVOICE_ACCESS_KEY, WAKE_WORD_PATH
import time
import threading
import sys
import queue

# Configure detailed logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s.%(msecs)03d - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

def run_detector(detector, error_queue):
    """Run the detector in a thread"""
    try:
        logging.info("Starting detector thread")
        detector.start()
        logging.info("Detector thread completed normally")
    except Exception as e:
        logging.error(f"Error in detector thread: {e}")
        error_queue.put(sys.exc_info())

async def test_wake_word_restart():
    """Test starting, stopping, and restarting wake word detection"""
    detector = None
    detector_thread = None
    error_queue = queue.Queue()
    
    try:
        # First initialization
        logging.info("=== First Initialization ===")
        logging.info("Creating first detector instance...")
        detector = WakeWordDetector(
            callback_fn=lambda: logging.info("Wake word detected!"),
            access_key=PICOVOICE_ACCESS_KEY,
            keyword_path=WAKE_WORD_PATH
        )
        logging.info("First detector initialized successfully")
        
        # Start first instance in a thread
        logging.info("Starting first detector thread...")
        detector_thread = threading.Thread(target=run_detector, args=(detector, error_queue))
        detector_thread.daemon = True
        detector_thread.start()
        logging.info("First detector thread started")
        
        # Check for any immediate errors
        await asyncio.sleep(1)
        if not error_queue.empty():
            exc_info = error_queue.get()
            raise exc_info[1].with_traceback(exc_info[2])
        
        # Wait for a bit
        logging.info("Running first detector for 10 seconds...")
        await asyncio.sleep(10)
        
        # Stop first instance
        logging.info("Stopping first detector...")
        detector.stop()
        logging.info("Waiting for first detector thread to finish...")
        detector_thread.join(timeout=2)
        if detector_thread.is_alive():
            logging.error("First detector thread did not stop cleanly!")
        detector = None
        detector_thread = None
        
        # Wait between instances with progress logging
        total_wait = 5
        logging.info(f"Waiting {total_wait} seconds before restarting...")
        for i in range(total_wait):
            await asyncio.sleep(1)
            logging.debug(f"Wait progress: {i+1}/{total_wait} seconds")
        
        # Second initialization
        logging.info("\n=== Second Initialization ===")
        logging.info("Creating second detector instance...")
        detector = WakeWordDetector(
            callback_fn=lambda: logging.info("Wake word detected!"),
            access_key=PICOVOICE_ACCESS_KEY,
            keyword_path=WAKE_WORD_PATH
        )
        logging.info("Second detector initialized successfully")
        
        # Start second instance in a thread
        logging.info("Starting second detector thread...")
        detector_thread = threading.Thread(target=run_detector, args=(detector, error_queue))
        detector_thread.daemon = True
        detector_thread.start()
        logging.info("Second detector thread started")
        
        # Check for any immediate errors
        await asyncio.sleep(1)
        if not error_queue.empty():
            exc_info = error_queue.get()
            raise exc_info[1].with_traceback(exc_info[2])
        
        # Wait for a bit
        logging.info("Running second detector for 10 seconds...")
        await asyncio.sleep(10)
        
    except Exception as e:
        logging.error(f"Error during test: {e}", exc_info=True)
        if not error_queue.empty():
            exc_info = error_queue.get()
            logging.error("Thread error details:", exc_info=exc_info)
        raise
    finally:
        # Final cleanup with detailed logging
        logging.info("=== Final Cleanup ===")
        if detector:
            try:
                logging.info("Stopping detector...")
                detector.stop()
                if detector_thread and detector_thread.is_alive():
                    logging.info("Waiting for detector thread to finish...")
                    detector_thread.join(timeout=2)
                    if detector_thread.is_alive():
                        logging.error("Detector thread did not stop cleanly!")
                detector = None
                detector_thread = None
                logging.info("Cleanup completed successfully")
            except Exception as e:
                logging.error(f"Error during cleanup: {e}", exc_info=True)

if __name__ == "__main__":
    try:
        # Add signal handler for clean shutdown
        import signal
        def signal_handler(signum, frame):
            logging.info("Received interrupt signal")
            raise KeyboardInterrupt
        signal.signal(signal.SIGINT, signal_handler)
        
        logging.info("Starting wake word restart test...")
        asyncio.run(test_wake_word_restart())
    except KeyboardInterrupt:
        logging.info("Test interrupted by user")
    except Exception as e:
        logging.error(f"Test failed: {e}", exc_info=True)
    finally:
        logging.info("Test complete") 