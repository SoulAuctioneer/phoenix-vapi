from services.service import BaseService
from managers.led_manager import LEDManager, LEDEffect, LEDManagerRings
from config import PLATFORM, LEDConfig
import logging


class LEDService(BaseService):
    def __init__(self, service_manager):
        super().__init__(service_manager)
        self.led_controller = None
        self.platform = PLATFORM
        
    async def start(self):
        """Initialize and start the LED service"""
        try:
            if LEDConfig.IS_DUAL_RINGS:
                logging.info("Using dual-ring LED setup.")
                self.led_controller = LEDManagerRings(initial_brightness=LEDConfig.LED_BRIGHTNESS)
            else:
                logging.info("Using single LED strip setup.")
                self.led_controller = LEDManager(initial_brightness=LEDConfig.LED_BRIGHTNESS)
            
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

        if event_type == "intent_detection_started":
            logging.info("Intent detection started - switched to random twinkling effect")
            # TODO: This needs to be smarter in respect to what effect we revert to after finishing, need more state orchestration
            duration = event.get('timeout', 7)
            self.led_controller.start_effect(LEDEffect.ROTATING_PINK_BLUE, speed=0.03)

        elif event_type == "stop_led_effect":
            self.led_controller.stop_effect()
            logging.info("Stopped LED effect")

        elif event_type == "conversation_started":
            # Now handled by activity service
            # logging.info("Conversation started - switched to random twinkling effect")
            # self.led_controller.start_effect(LEDEffect.RANDOM_TWINKLING, speed=0.1)
            pass

        elif event_type == "conversation_ended":
            # Now handled by switching to sleep activity
            # logging.info("Conversation ended - switched to rotating pink blue effect")
            # self.led_controller.start_effect(LEDEffect.ROTATING_PINK_BLUE)
            pass

        elif event_type == "application_startup_completed":
            # Now handled by switching to sleep activity
            # logging.info("Application startup completed - switched to rotating pink blue effect")
            # self.led_controller.start_effect(LEDEffect.ROTATING_PINK_BLUE)
            pass

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
            brightness = event.get('data', {}).get('brightness', 1.0)
            # --- Extract color specifically for rotating_color ---
            color = None
            if effect_name == "rotating_color":
                color = event.get('data', {}).get('color')
                if not color:
                    logging.warning("'rotating_color' effect requested but no color specified in event data. Effect may fail or use default.")
            # --- End color extraction ---
            
            # Map string effect names to enum values
            effect_map = {
                "blue_breathing": LEDEffect.BLUE_BREATHING,
                "green_breathing": LEDEffect.GREEN_BREATHING,
                "rainbow": LEDEffect.ROTATING_RAINBOW,
                "rotating_pink_blue": LEDEffect.ROTATING_PINK_BLUE,
                "rotating_green_yellow": LEDEffect.ROTATING_GREEN_YELLOW,
                "magical_spell": LEDEffect.RANDOM_TWINKLING,
                "rain": LEDEffect.RAIN,
                "lightning": LEDEffect.LIGHTNING,
                "purring": LEDEffect.PURRING,
                "rotating_color": LEDEffect.ROTATING_COLOR
            }
            
            if effect_name in effect_map:
                effect = effect_map[effect_name]
                self.led_controller.start_effect(effect, speed=speed, brightness=brightness, color=color)
                logging.info(f"Started {effect_name} effect with speed {speed}, brightness {brightness}" + (f" and color {color}" if color else ""))
            elif effect_name == "stop":
                self.led_controller.stop_effect()
                logging.info("Stopped LED effect")
            elif effect_name == "clear":
                self.led_controller.clear()
                logging.info("Cleared all LEDs")

        elif event_type == "battery_alert":
            alerts = event.get('alerts', [])
            if "voltage_low" in alerts:
                current_base_brightness = self.led_controller.get_base_brightness()
                new_base_brightness = max(0.0, current_base_brightness - 0.05) # Decrease by 0.05, ensuring it doesn't go below 0
                if new_base_brightness < current_base_brightness: # Only update if there's a change
                    self.led_controller.set_base_brightness(new_base_brightness)
                    logging.warning(f"Low voltage detected! Reducing base LED brightness from {current_base_brightness:.2f} to {new_base_brightness:.2f}")
                else:
                    logging.info(f"Low voltage detected, but base brightness already at minimum (0.0)") 
