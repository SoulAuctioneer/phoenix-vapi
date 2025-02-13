from services.service import BaseService
from managers.led_manager import LEDManager, LEDEffect
from config import PLATFORM, LED_BRIGHTNESS
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
            if self.platform == "raspberry-pi":
                logging.info("LED service started")
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
            logging.info("Wake word detected - switched to rotating rainbow effect")
            self.led_controller.start_effect(LEDEffect.RANDOM_TWINKLING, speed=0.06)

        elif event_type == "conversation_started":
            logging.info("Conversation started - switched to random twinkling effect")
            self.led_controller.start_effect(LEDEffect.RANDOM_TWINKLING, speed=0.1)

        elif event_type == "conversation_ended":
            logging.info("Conversation ended - switched to rotating pink blue effect")
            self.led_controller.start_effect(LEDEffect.ROTATING_PINK_BLUE)

        elif event_type == "application_startup_completed":
            logging.info("Application startup completed - switched to rotating pink blue effect")
            self.led_controller.start_effect(LEDEffect.ROTATING_PINK_BLUE)

        elif event_type == "touch_stroke_intensity":
            # Only trigger purring effect if we're not in a conversation
            if not self.global_state.conversation_active:
                intensity = event.get('intensity', 0.0)
                if intensity > 0:
                    # Map intensity (0-1) to LED effect speed (0.05-0.005)
                    # Higher intensity = faster purring (lower wait time)
                    # Using a larger range for more noticeable speed changes
                    # base_speed = 0.05  # Slower base speed
                    # min_speed = 0.005  # Fastest possible speed
                    # speed_range = base_speed - min_speed
                    # speed = base_speed - (intensity * speed_range)
                    speed = 0.05 # Just hardcoded as real purring doesn't really actually get faster, just louder
                    
                    # Map intensity to brightness (0.05-1.0)
                    # CURVE_RATIO = 1.0 for linear, > 1.0 for slower initial increase, < 1.0 for faster initial increase
                    CURVE_RATIO = 1.0  # Linear by default
                    min_brightness = 0.01  # Start very dim
                    brightness_range = 1.0 - min_brightness
                    # Apply curve ratio to intensity for optional non-linear scaling
                    curved_intensity = pow(intensity, CURVE_RATIO)
                    brightness = min_brightness + (curved_intensity * brightness_range)
                    
                    # Log the speed as frequency (1/speed) to make the relationship more intuitive
                    # Higher frequency = faster purring
                    frequency = 1.0 / speed if speed > 0 else 0
                    logging.info(f"Starting or updating purring effect with frequency {frequency:.2f}Hz (speed={speed:.4f}) and brightness {brightness:.2f} based on intensity {intensity:.2f}")
                    self.led_controller.start_or_update_effect(LEDEffect.PURRING, speed=speed, brightness=brightness)
                else:
                    # When intensity drops to 0, return to default effect
                    logging.info("Touch intensity ended, returning to default effect")
                    self.led_controller.start_effect(LEDEffect.ROTATING_PINK_BLUE)

        elif event_type == "start_led_effect":
            # Handle manual LED commands
            effect_name = event.get('data', {}).get('effectName')
            speed = event.get('data', {}).get('speed', 0.02)
            brightness = event.get('data', {}).get('brightness', LED_BRIGHTNESS)
            
            # Map string effect names to enum values
            effect_map = {
                "blue_breathing": LEDEffect.BLUE_BREATHING,
                "green_breathing": LEDEffect.GREEN_BREATHING,
                "rainbow": LEDEffect.ROTATING_RAINBOW,
                "pink_blue_cycle": LEDEffect.ROTATING_PINK_BLUE,
                "magical_spell": LEDEffect.RANDOM_TWINKLING,
                "rain": LEDEffect.RAIN,
                "lightning": LEDEffect.LIGHTNING,
                "purring": LEDEffect.PURRING
            }
            
            if effect_name in effect_map:
                effect = effect_map[effect_name]
                self.led_controller.start_effect(effect, speed=speed, brightness=brightness)
                logging.info(f"Started {effect_name} effect with speed {speed} and brightness {brightness}")
            elif effect_name == "stop":
                self.led_controller.stop_effect()
                logging.info("Stopped LED effect")
            elif effect_name == "clear":
                self.led_controller.clear()
                logging.info("Cleared all LEDs") 
