import time
from companion import KidsCompanion

def main():
    print("Starting AI Companion...")
    companion = KidsCompanion()
    
    try:
        companion.start_interaction()
        while True:
            time.sleep(0.1)  # Small delay to prevent CPU overhead
            
    except KeyboardInterrupt:
        print("\nShutting down AI Companion...")
    finally:
        companion.cleanup()

if __name__ == "__main__":
    main() 