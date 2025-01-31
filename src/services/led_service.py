from services.service import BaseService
from managers.led_manager import LEDManager
from config import PLATFORM
import logging

class LEDService(BaseService):
    def __init__(self, manager):
        super().__init__(manager)
        self.led_controller = None
        self.platform = PLATFORM
        
    async def start(self):
        """Initialize and start the LED service"""
        try:
            self.led_controller = LEDManager()
            # Start with breathing effect
            self.led_controller.start_idle_pattern()
            if self.platform == "raspberry-pi":
                logging.info("LED service started with breathing effect on Raspberry Pi")
            else:
                logging.info("LED service started in simulation mode")
        except Exception as e:
            logging.error(f"Failed to start LED service: {e}")
            if self.platform == "raspberry-pi":
                # Only raise the error on Raspberry Pi - we expect the hardware to work there
                raise
            else:
                # On other platforms, log the error but continue without LED support
                logging.warning("LED service will run in mock mode")
                self.led_controller = None

    async def stop(self):
        """Stop the LED service and clean up"""
        if self.led_controller:
            self.led_controller.stop_effect()
            self.led_controller.clear()
            logging.info("LED service stopped")

    async def handle_event(self, event):
        """Handle LED-related events"""
        if not self.led_controller:
            # If we don't have a controller (e.g., on non-Raspberry Pi), just log the events
            logging.info(f"LED event '{event.get('type')}' received but no controller available")
            return

        event_type = event.get('type')

        if event_type == "wake_word_detected":
            # Wake word detected - switch to rainbow effect
            self.led_controller.start_listening_pattern(speed=0.01)  # Faster rainbow for wake word
            logging.info("Wake word detected - switched to rainbow effect")

        elif event_type == "conversation_started":
            # Conversation started - switch to conversation effect
            self.led_controller.start_conversation_pattern()
            logging.info("Conversation started - switched to conversation effect")

        elif event_type == "conversation_ended":
            # Conversation ended - return to breathing effect
            self.led_controller.start_idle_pattern()
            logging.info("Conversation ended - returned to breathing effect")

        elif event_type == "led_command":
            # Handle manual LED commands
            command = event.get('data', {}).get('command')
            if command == "start_listening_pattern":
                speed = event.get('data', {}).get('speed', 0.02)
                self.led_controller.start_listening_pattern(speed=speed)
                logging.info(f"Started rainbow effect with speed {speed}")
            elif command == "start_idle_pattern":
                speed = event.get('data', {}).get('speed', 0.05)
                self.led_controller.start_idle_pattern(speed=speed)
                logging.info(f"Started breathing effect with speed {speed}")
            elif command == "start_conversation_pattern":
                speed = event.get('data', {}).get('speed', 0.03)
                self.led_controller.start_conversation_pattern(speed=speed)
                logging.info(f"Started conversation effect with speed {speed}")
            elif command == "stop":
                self.led_controller.stop_effect()
                logging.info("Stopped LED effect")
            elif command == "clear":
                self.led_controller.clear()
                logging.info("Cleared all LEDs") 