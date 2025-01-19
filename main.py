import time
import RPi.GPIO as GPIO
from companion import KidsCompanion

def main():
    print("Starting AI Companion...")
    companion = KidsCompanion()
    
    try:
        while True:
            # Check if button is pressed (GPIO 18)
            if not GPIO.input(18):  # Button press detected
                if not companion.is_active:
                    print("Starting new interaction...")
                    companion.start_interaction()
                else:
                    print("Stopping current interaction...")
                    companion.stop_interaction()
                # Debounce delay
                time.sleep(0.5)
            
            time.sleep(0.1)  # Small delay to prevent CPU overhead
            
    except KeyboardInterrupt:
        print("\nShutting down AI Companion...")
    finally:
        companion.cleanup()

if __name__ == "__main__":
    main() 