import asyncio
import logging
import signal
from config import PLATFORM, LED_CONFIG
from services.service import ServiceManager
from services.audio_service import AudioService
from services.special_effect_service import SpecialEffectService
from services.wakeword_service import WakeWordService
from services.activity_service import ActivityService
from services.intent_service import IntentService

if PLATFORM == "raspberry-pi":
    from services.led_service import LEDService
    from services.battery_service import BatteryService

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
    'services.conversation',
    'services.led',
    'services.special_effect',
    'services.sensor',
    'services.haptic',
    'services.intent',
    'services.activity',
    'services.sleep_activity',
    # Too noisy, disable for now
    'services.location',
    'managers.location_manager'
]:
    logging.getLogger(logger_name).setLevel(logging.DEBUG)

for logger_name in [
    'services.hide_seek_service'
]:
    logging.getLogger(logger_name).setLevel(logging.WARNING)


# Disable the LEDs on the Respeaker 4-mic array
if PLATFORM == "raspberry-pi":
    logging.info("Disabling LEDs on Respeaker 4-mic array")
    from hardware.respeaker import disable_leds
    disable_leds()


class PhoenixApp:
    def __init__(self):
        self.service_manager = ServiceManager()
        self._should_run = True
        self.initialized_services = {}

    async def initialize_services(self):
        """Initialize and start core services in the correct order"""
        # Initialize all services
        self.initialized_services = {
            'audio': AudioService(self.service_manager),
            'wakeword': WakeWordService(self.service_manager),
            'special_effect': SpecialEffectService(self.service_manager),
            'intent': IntentService(self.service_manager),
            'activity': ActivityService(self.service_manager)
        }
        
        # Add platform-specific services on Raspberry Pi
        if PLATFORM == "raspberry-pi":
            self.initialized_services['battery'] = BatteryService(self.service_manager)
            if LED_CONFIG.LEDS_ENABLED:
                self.initialized_services['led'] = LEDService(self.service_manager)

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
            await self.cleanup()
        except Exception as e:
            logging.error(f"Fatal error: {e}", exc_info=True)
            raise
        finally:
            await self.cleanup()

    async def cleanup(self):
        """Cleanup all resources"""
        logging.info("Cleaning up resources...")
        await self.service_manager.stop_all()

    def handle_shutdown(self, sig=None):
        """Handle shutdown signals"""
        if sig:
            logging.info(f"Received signal {sig.name}")
        self._should_run = False
        # Schedule the cleanup
        asyncio.create_task(self.cleanup())
        # Cancel all tasks except the current one
        for task in asyncio.all_tasks():
            if task is not asyncio.current_task():
                task.cancel()

async def main():
    app = PhoenixApp()
    
    # Setup signal handlers for graceful shutdown
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(
            sig,
            lambda s=sig: app.handle_shutdown(s)
        )
    
    await app.run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except asyncio.CancelledError:
        logging.info("Application cancelled")
    except KeyboardInterrupt:
        logging.info("Application interrupted")
    except Exception as e:
        logging.error(f"Fatal error: {e}", exc_info=True)
    finally:
        logging.info("Application stopped") 