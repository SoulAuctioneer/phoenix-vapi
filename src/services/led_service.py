from services.service import BaseService
from managers.led_manager import LEDManager, LEDManagerRings
from config import PLATFORM, LEDConfig
import logging

# Import the bridge augmentation function
from hardware.respeaker_led_bridge import augment_led_manager, MappingMode

class LEDService(BaseService):
    def __init__(self, service_manager):
        super().__init__(service_manager)
        self.led_controller = None
        self.platform = PLATFORM
        
    async def start(self):
        """Initialize and start the LED service and ReSpeaker bridge."""
        try:
            if LEDConfig.IS_DUAL_RINGS:
                self.logger.info("Using dual-ring LED setup.")
                self.led_controller = LEDManagerRings(initial_brightness=LEDConfig.LED_BRIGHTNESS)
            else:
                self.logger.info("Using single LED strip setup.")
                self.led_controller = LEDManager(initial_brightness=LEDConfig.LED_BRIGHTNESS)

            # Augment with ReSpeaker LED bridge
            if LEDConfig.USE_RESPEAKER_LEDS:
                self.logger.info("Augmenting LED manager with ReSpeaker bridge.")
                # This function modifies the led_controller in place to add ReSpeaker support
                self.respeaker_bridge = augment_led_manager(self.led_controller)
                if self.respeaker_bridge:
                    self.logger.info("Successfully augmented LED manager with ReSpeaker support.")
                else:
                    self.logger.info("ReSpeaker hardware not found or bridge failed to initialize. Continuing with NeoPixels only.")
            
            self.logger.info("LED service started")

        except Exception as e:
            logging.error(f"Failed to start LED service: {e}", exc_info=True)
            if self.platform == "raspberry-pi":
                # On Pi, this is a critical failure.
                raise
            else:
                # On other platforms, log the error but continue without LED support
                logging.warning("LED service will run in a mocked/uninitialized state.")
                self.led_controller = None

    async def stop(self):
        """Stop the LED service and clean up"""
        if self.led_controller:
            await self.led_controller.stop_effect()
            self.led_controller.clear()
            self.logger.info("LED service stopped")

    async def handle_event(self, event):
        """Handle LED-related events"""
        if not self.led_controller:
            # If we don't have a controller (e.g., on non-Raspberry Pi), just log the events
            logging.debug(f"LED event '{event.get('type')}' received but no controller available")
            return

        event_type = event.get('type')

        # if event_type == "intent_detection_started":
        #     self.logger.info("Intent detection started - switched to random twinkling effect")
        #     # TODO: This needs to be smarter in respect to what effect we revert to after finishing, need more state orchestration
        #     duration = event.get('timeout', 7)
        #     self.led_controller.start_effect("ROTATING_PINK_BLUE", speed=0.03)

        if event_type == "start_led_effect":
            # Handle manual LED commands
            # TODO: Change to uppercase everywhere
            effect_name = event.get('data', {}).get('effect_name').upper()
            speed = event.get('data', {}).get('speed', 0.02)
            brightness = event.get('data', {}).get('brightness', 1.0)
            # --- Extract color specifically for rotating_color ---
            # TODO: Hacky, need to refactor to handle effect-specific parameters generically, e.g. via kwargs
            color = None
            if effect_name == "rotating_color":
                color = event.get('data', {}).get('color')
                if not color:
                    logging.warning("'rotating_color' effect requested but no color specified in event data. Effect may fail or use default.")
            # --- End color extraction ---
            
            if effect_name == "stop":
                await self.led_controller.stop_effect()
                self.logger.info("Stopped LED effect")
            elif effect_name == "clear":
                self.led_controller.clear()
                self.logger.info("Cleared all LEDs")
            # Check if the effect_name is a known key in the manager's map
            elif effect_name in self.led_controller._EFFECT_MAP: 
                # Pass the string name directly
                # Call start_or_update_effect, which handles both starting and updating
                await self.led_controller.start_or_update_effect(effect_name, speed=speed, brightness=brightness, color=color)
                # Logging for start/update is handled within the manager now
                # self.logger.info(f"Started/Updated {effect_name} effect with speed {speed}, brightness {brightness}" + (f" and color {color}" if color else ""))
            else:
                logging.warning(f"Received unknown effect name: '{effect_name}'")

        elif event_type == "stop_led_effect":
            effect_name = event.get('data', {}).get('effect_name', None)
            # TODO: Change to uppercase everywhere
            effect_name = effect_name.upper() if effect_name else None
            self.logger.info(f"Attempting to stop LED effect '{effect_name}' now...")
            await self.led_controller.stop_effect(effect_name)
            self.logger.info(f"Stopped LED effect: {effect_name if effect_name else 'current'}")


        elif event_type == "battery_alert":
            alerts = event.get('data', {}).get('alerts', [])
            if "voltage_low" in alerts:
                current_base_brightness = self.led_controller.get_base_brightness()
                new_base_brightness = max(0.0, current_base_brightness - 0.05) # Decrease by 0.05, ensuring it doesn't go below 0
                if new_base_brightness < current_base_brightness: # Only update if there's a change
                    self.led_controller.set_base_brightness(new_base_brightness)
                    logging.warning(f"Low voltage detected! Reducing base LED brightness from {current_base_brightness:.2f} to {new_base_brightness:.2f}")
                else:
                    self.logger.info(f"Low voltage detected, but base brightness already at minimum (0.0)") 

        elif event_type == "touch_stroke_intensity":
            # Only trigger purring effect if we're not in a conversation
            if hasattr(self.global_state, 'conversation_active') and self.global_state.conversation_active:
                return
                
            intensity = event.get('data', {}).get('intensity', 0.0)
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
                logging.debug(f"Starting or updating purring effect with frequency {frequency:.2f}Hz (speed={speed:.4f}) and brightness {brightness:.2f} based on intensity {intensity:.2f}")
                await self.led_controller.start_or_update_effect("PURRING", speed=speed, brightness=brightness)
            else:
                # When intensity drops to 0, return to default effect
                logging.debug("Touch intensity ended, returning to default effect")
                await self.led_controller.start_effect("ROTATING_PINK_BLUE")
