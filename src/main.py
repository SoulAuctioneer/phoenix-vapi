import signal
import sys
import asyncio
from app import App

async def main():
    app = App()
    
    # Handle Ctrl+C gracefully
    def signal_handler(sig, frame):
        print("\nStopping Phoenix Assistant...")
        asyncio.create_task(app.cleanup())
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    
    try:
        print("Starting Phoenix Assistant...")
        await app.start()
    except Exception as e:
        print(f"Error: {e}")
        await app.cleanup()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main()) 