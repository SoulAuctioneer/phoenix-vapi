print ("Importing modules...")
import asyncio
import logging
import signal
import argparse
import config
from config import PLATFORM, get_filter_logger
from services.service import ServiceManager
from services.audio_service import AudioService
from services.special_effect_service import SpecialEffectService
from services.wakeword_service import WakeWordService
from services.activity_service import ActivityService
from services.intent_service import IntentService
from services.speech_service import SpeechService
from utils.system import set_shutdown_callback

if PLATFORM == "raspberry-pi":
    from services.led_service import LEDService
    from services.battery_service import BatteryService

print ("Finished imported modules.")

# Configure logging with more detail
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(filename)s.%(funcName)s:%(lineno)d] - %(levelname)s - %(message)s',
    force=True  # Override any existing logging configuration
)

# Enable debug logging for our services
for logger_name in [
    'services.service',
    'services.audio',
    'services.wake_word',
    'services.led',
    'services.special_effect',
    'services.sensor',
    'services.haptic',
    'services.intent',
    'services.activity',
    'activities.scavenger_hunt_activity'
    'activities.sleep_activity',
    'activities.conversation',
    # 'activities.call', # Too noisy
    'services.location',
    'managers.location_manager',
    'managers.accelerometer_manager',
    'managers.led_manager',
    'services.accelerometer_service'
]:
    get_filter_logger(logger_name).setLevel(logging.DEBUG)

for logger_name in [
    'services.hide_seek_activity'
]:
    get_filter_logger(logger_name).setLevel(logging.WARNING)


# Disable the LEDs on the Respeaker 4-mic array
if PLATFORM == "raspberry-pi":
    logging.info("Disabling LEDs on Respeaker 4-mic array")
    try:
        from hardware.respeaker import disable_leds
        disable_leds()
    except Exception as e:
        logging.warning(f"Failed to disable Respeaker LEDs: {e}")


class PhoenixApp:
    def __init__(self):
        self.service_manager = ServiceManager()
        self._should_run = True
        self.initialized_services = {}
        self._is_cleaning_up = False

    async def initialize_services(self):
        """Initialize and start core services in the correct order"""
        # Initialize all services
        self.initialized_services = {
            'audio': AudioService(self.service_manager),
            'speech': SpeechService(self.service_manager),
            'wakeword': WakeWordService(self.service_manager),
            'special_effect': SpecialEffectService(self.service_manager),
            'intent': IntentService(self.service_manager),
            'activity': ActivityService(self.service_manager)
        }
        
        # Add platform-specific services on Raspberry Pi
        if PLATFORM == "raspberry-pi":
            self.initialized_services['led'] = LEDService(self.service_manager)
            self.initialized_services['battery'] = BatteryService(self.service_manager)

        # Start audio service first, then all other services in parallel
        await self.service_manager.start_service('audio', self.initialized_services['audio'])
        await asyncio.gather(
            *[self.service_manager.start_service(name, self.initialized_services[name])
              for name in self.initialized_services.keys() if name != 'audio']
        )
        
        logging.info("All services initialized and started")

    async def run(self):
        """Main application loop"""
        try:
            await self.initialize_services()
            
            # Notify that application startup is complete
            await self.service_manager.publish({
                "type": "application_startup_completed",
                "producer_name": "main"
            })

            # Keep the main task running
            while self._should_run:
                await asyncio.sleep(1)
                
        except asyncio.CancelledError:
            logging.info("Application task cancelled")
        except Exception as e:
            logging.error(f"Fatal error in PhoenixApp.run: {e}", exc_info=True)
            self._should_run = False # Ensure we don't continue
            # The 'finally' block will handle cleanup. Re-raising would be handled by the main entry point.
            raise
        finally:
            await self.cleanup()

    async def cleanup(self):
        """Cleanup all resources"""
        if self._is_cleaning_up:
            return
        self._is_cleaning_up = True
        logging.info("Cleaning up resources...")
        await self.service_manager.stop_all()

    def handle_shutdown(self, sig=None):
        """Handle shutdown signals"""
        if sig:
            logging.info(f"Received signal {sig.name}")
        self._should_run = False
        # Cancel all running tasks. This will interrupt the main `run` loop,
        # leading to a call to `cleanup` in its `finally` block.
        for task in asyncio.all_tasks():
            if task is not asyncio.current_task():
                task.cancel()

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--log_filters", nargs='*', help="Filter patterns for logging")
    args = parser.parse_args()

    if args.log_filters:
        logging.info(f"Log filters: {args.log_filters}")
        config.LOG_FILTERS = args.log_filters
    
    app = PhoenixApp()
    set_shutdown_callback(app.handle_shutdown)
    
    # Setup signal handlers for graceful shutdown
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(
            sig,
            lambda s=sig: app.handle_shutdown(s)
        )
    
    try:
        await app.run()
    except Exception as e:
        # This will catch the re-raised exception from app.run() and allow for a clean exit
        logging.info(f"Phoenix App run failed with exception: {e}. Application will now exit.")
        # The finally block in __main__ will still execute for final logging.


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except asyncio.CancelledError:
        logging.info("Application cancelled")
    except KeyboardInterrupt:
        logging.info("Application interrupted")
    except Exception as e:
        logging.error(f"Unhandled fatal error in main: {e}", exc_info=True)
    finally:
        logging.info("Application stopped") 