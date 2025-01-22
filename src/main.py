import time
from app import App

def main():
    print("Starting Phoenix AI Companion...")
    app = App()
    
    try:
        app.start_interaction()
        while True:
            time.sleep(0.1)  # Small delay to prevent CPU overhead
            
    except KeyboardInterrupt:
        print("\nShutting down Phoenix AI Companion...")
    finally:
        app.cleanup()

if __name__ == "__main__":
    main() 