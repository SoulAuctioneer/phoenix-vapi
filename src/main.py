import signal
import sys
from app import App

def main():
    app = App()
    
    # Handle Ctrl+C gracefully
    def signal_handler(sig, frame):
        print("\nStopping Phoenix Assistant...")
        app.cleanup()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    
    try:
        print("Starting Phoenix Assistant...")
        app.start()
        
        # Keep the program running
        signal.pause()
        
    except Exception as e:
        print(f"Error: {e}")
        app.cleanup()
        sys.exit(1)

if __name__ == "__main__":
    main() 