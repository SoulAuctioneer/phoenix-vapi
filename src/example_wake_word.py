from wake_word import WakeWordDetector
import pvporcupine
import time
import signal
import os

def on_wake_word():
    print("Wake word detected! Ready to listen...")

def main():
    # Show available built-in keywords
    print("Available built-in wake words:")
    for keyword in sorted(pvporcupine.KEYWORDS):
        print(f"- {keyword}")
    print()
    
    # You can use either a built-in wake word:
    wake_word = "porcupine"  # or any other from the list above
    
    # Or a custom keyword file (if you have one):
    # keyword_path = "path/to/your/custom_wake_word.ppn"
    
    try:
        # Initialize with built-in wake word:
        detector = WakeWordDetector(
            callback_fn=on_wake_word,
            keyword=wake_word
        )
        
        # Or initialize with custom keyword file:
        # detector = WakeWordDetector(
        #     callback_fn=on_wake_word,
        #     keyword_path=keyword_path
        # )
        
        # Handle Ctrl+C gracefully
        def signal_handler(sig, frame):
            print("\nStopping wake word detection...")
            detector.stop()
            exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        
        print(f"\nStarting wake word detection...")
        print(f"Say '{wake_word}' to trigger the wake word...")
        print("(Press Ctrl+C to exit)")
        detector.start()
        
        # Keep the program running
        while True:
            time.sleep(0.1)
            
    except ValueError as e:
        print(f"Error: {e}")
        print("\nPlease set up your access key and try again.")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if 'detector' in locals():
            detector.stop()

if __name__ == "__main__":
    main() 