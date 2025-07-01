import time
import colorsys
import math
from threading import Thread, Event
from config import LEDConfig
import logging
import random
from enum import Enum, auto
from typing import Union, Optional
import asyncio

# Try to import board and neopixel, but don't fail if they're not available, e.g. not on Raspberry Pi
try:
    import board
    import neopixel
    LEDS_AVAILABLE = True
    logging.info("LED libraries available. Will use LEDs")
except (ImportError, NotImplementedError):
    LEDS_AVAILABLE = False
    logging.info("LED libraries not available. Won't use LEDs")

COLORS = {
    "red": (255, 0, 0),
    "green": (0, 255, 0),
    "blue": (0, 0, 255),
    "yellow": (255, 255, 0),
    "cyan": (0, 255, 255),
    "purple": (128, 0, 128),
    "pink": (255, 192, 203),
    "orange": (255, 165, 0),
    "brown": (139, 69, 19),
    "gray": (128, 128, 128),
    "black": (0, 0, 0),
    "white": (255, 255, 255),
    # Custom colors for Magic Garden Pea effect
    "magic_green": (0, 255, 0),
    "magic_blue": (0, 0, 255),
    # Planet colors
    "mercury_gray": (128, 128, 128),
    "venus_yellow": (255, 224, 153),
    "earth_blue": (0, 102, 204),
    "earth_green": (0, 153, 51),
    "mars_red": (199, 84, 45),
    "jupiter_orange": (216, 162, 112),
    "jupiter_white": (255, 255, 240),
    "saturn_gold": (234, 214, 184),
    "uranus_blue": (173, 216, 230),
    "neptune_blue": (63, 81, 181),
}

class LEDManager:
    # Map of effects to their corresponding private methods and default speeds
    _EFFECT_MAP = {
        "BLUE_BREATHING": {'method': '_blue_breathing_effect', 'default_speed': 0.05},
        "GREEN_BREATHING": {'method': '_green_breathing_effect', 'default_speed': 0.05},
        "ROTATING_PINK_BLUE": {'method': '_rotating_pink_blue_effect', 'default_speed': 0.05},
        "ROTATING_GREEN_YELLOW": {'method': '_rotating_green_yellow_effect', 'default_speed': 0.05},
        "RAINBOW": {'method': '_rainbow_effect', 'default_speed': 0.02},
        "TWINKLING": {'method': '_random_twinkling_effect', 'default_speed': 0.03},
        "RAIN": {'method': '_rain_effect', 'default_speed': 0.05},
        "LIGHTNING": {'method': '_lightning_effect', 'default_speed': 0.05},
        "PURRING": {'method': '_purring_effect', 'default_speed': 0.01},
        "ROTATING_COLOR": {'method': '_rotating_color_effect', 'default_speed': 0.05},
        "MAGICAL_SPELL": {'method': '_magical_spell_effect', 'default_speed': 0.03},
        "SPARKLING_PINK_BLUE": {'method': '_sparkling_pink_blue_effect', 'default_speed': 0.04},
        "ROTATING_BEACON": {'method': '_rotating_beacon_effect', 'default_speed': 0.1},
        # Planet tour effects
        "WARP_DRIVE": {'method': '_warp_drive_effect', 'default_speed': 0.01},
        "MERCURY": {'method': '_mercury_effect', 'default_speed': 0.1},
        "VENUS": {'method': '_venus_effect', 'default_speed': 0.1},
        "EARTH": {'method': '_earth_effect', 'default_speed': 0.05},
        "MARS": {'method': '_mars_effect', 'default_speed': 0.08},
        "JUPITER": {'method': '_jupiter_effect', 'default_speed': 0.04},
        "SATURN": {'method': '_saturn_effect', 'default_speed': 0.05},
        "URANUS": {'method': '_uranus_effect', 'default_speed': 0.06},
        "NEPTUNE": {'method': '_neptune_effect', 'default_speed': 0.05},
    }

    def __init__(self, initial_brightness=LEDConfig.LED_BRIGHTNESS):
        self._effect_thread = None
        self._stop_event = Event()
        self._current_speed = None
        # Track current effect state (now a string)
        self._current_effect: Optional[str] = None
        self._base_brightness = max(0.0, min(1.0, initial_brightness)) # Store and clamp base brightness
        self._current_relative_brightness = 1.0 # Track the relative brightness set by effects (defaults to 1.0)
        self._loop = asyncio.get_event_loop()
        
        # Initialize the NeoPixel object only on Raspberry Pi
        if LEDS_AVAILABLE:
            # Get the correct board pin based on LED_PIN configuration
            pin = getattr(board, f'D{LEDConfig.LED_PIN}') if hasattr(board, f'D{LEDConfig.LED_PIN}') else LEDConfig.LED_PIN
            self.pixels = neopixel.NeoPixel(
                pin,
                LEDConfig.LED_COUNT,
                brightness=self._base_brightness, # Use base brightness for initial setup
                auto_write=False,
                pixel_order=LEDConfig.LED_ORDER
            )
            logging.info(f"NeoPixel initialized on pin {LEDConfig.LED_PIN} with {LEDConfig.LED_COUNT} LEDs at base brightness {self._base_brightness:.2f}")
        else:
            # Mock pixels for non-Raspberry Pi platforms
            class MockPixels:
                def __init__(self, num_pixels):
                    self.n = num_pixels
                    self._pixels = [(0, 0, 0)] * num_pixels

                def __setitem__(self, index, color):
                    self._pixels[index] = color
                    #logging.info(f"Mock: LED {index} set to color {color}")

                def __getitem__(self, index):
                    return self._pixels[index]

                def fill(self, color):
                    self._pixels = [color] * self.n
                    #logging.info(f"Mock: All LEDs set to color {color}")

                def show(self):
                    #logging.info("Mock: LED state updated")
                    pass
                
                # Add brightness property to mock for consistency
                @property
                def brightness(self):
                    return self._brightness
                
                @brightness.setter
                def brightness(self, value):
                    self._brightness = value
                    # logging.info(f"Mock: Brightness set to {value}")

            self.pixels = MockPixels(LEDConfig.LED_COUNT)
            self.pixels.brightness = self._base_brightness # Set initial mock brightness
            logging.info(f"Mock NeoPixel initialized with {LEDConfig.LED_COUNT} LEDs at base brightness {self._base_brightness:.2f}")
        
        # Wrap the show() method to implement power capping.
        self._original_show = self.pixels.show
        self.pixels.show = self._capped_show
        
        self.clear()

    def _capped_show(self):
        """A wrapper for the real show() method that caps total brightness to prevent power issues."""
        # This check is only meaningful if we have real LEDs that consume power.
        if not LEDS_AVAILABLE:
            self._original_show()
            return

        # Check if the power capping feature is configured.
        if not hasattr(LEDConfig, 'MAX_TOTAL_BRIGHTNESS') or LEDConfig.MAX_TOTAL_BRIGHTNESS <= 0:
            self._original_show()
            return
            
        # Calculate the total brightness of the current frame buffer as a proxy for power consumption.
        try:
            # Reading the entire buffer into a list first is safer and avoids potential
            # issues with modifying the buffer while iterating.
            current_pixels = [self.pixels[i] for i in range(self.pixels.n)]
            total_brightness = sum(sum(p) for p in current_pixels)
        except Exception as e:
            logging.error(f"Could not read pixel buffer for power capping: {e}")
            self._original_show()
            return

        # If total brightness exceeds the configured maximum, scale all pixel values down.
        if total_brightness > LEDConfig.MAX_TOTAL_BRIGHTNESS:
            scale_factor = LEDConfig.MAX_TOTAL_BRIGHTNESS / total_brightness
            # This logging can be spammy, so keep it at debug level.
            logging.warning(f"Power capping triggered. Total brightness: {total_brightness}, scaling by: {scale_factor:.2f}")
            
            # Apply the scaled pixels back to the hardware buffer from our temporary list.
            for i in range(self.pixels.n):
                self.pixels[i] = tuple(int(c * scale_factor) for c in current_pixels[i])
        
        # Call the original, hardware-level show() method.
        self._original_show()

    def _blend_colors(self, color1, color2):
        """Blend two colors by taking the maximum of each component"""
        return (
            max(color1[0], color2[0]),
            max(color1[1], color2[1]),
            max(color1[2], color2[2])
        )

    def _setup_revert_thread(self, previous_effect, duration):
        """Set up a thread to revert to previous effect after duration.
        
        Args:
            previous_effect: Dictionary containing previous effect state
            duration: Duration in milliseconds before reverting
        """
        def revert_after_duration():
            time.sleep(duration / 1000)  # Convert ms to seconds
            if previous_effect and not self._stop_event.is_set():
                asyncio.run_coroutine_threadsafe(
                    self.start_effect(
                        previous_effect['effect'],
                        previous_effect['speed'],
                        previous_effect['brightness'] # This is the relative brightness
                    ),
                    self._loop
                )
                
        revert_thread = Thread(target=revert_after_duration)
        revert_thread.daemon = True
        revert_thread.start()

    async def start_or_update_effect(self, effect: str, speed=None, brightness=1.0, duration=None, color: Optional[str] = None):
        """Start an LED effect if it's not already running, or update its parameters if it is.
        
        This function allows for smooth transitions in effect parameters without restarting the effect
        pattern from the beginning. If the requested effect is already running, it will only update
        the speed and brightness. If it's a different effect, it will start the new effect.
        
        Args:
            effect: The name (string) of the LEDEffect to start or update
            speed: Speed of the effect (if None, uses effect's default speed)
            brightness: Brightness level from 0.0 to 1.0. Multiplied by the LED_BRIGHTNESS from config, and defaults to 1.0
            duration: Optional duration in milliseconds before reverting to previous effect
            color: Optional color name (used by specific effects like ROTATING_COLOR)
        """
        if effect not in self._EFFECT_MAP:
            raise ValueError(f"Unknown effect: {effect}")

        effect_info = self._EFFECT_MAP[effect]
        effect_speed = speed if speed is not None else effect_info['default_speed']

        # Store current state before any changes
        previous_effect = None
        if self._effect_thread is not None:
            previous_effect = {
                'effect': self._current_effect,
                'speed': self._current_speed,
                'brightness': self._current_relative_brightness # Store relative brightness
            }

        # If the same effect is already running, just update parameters
        if effect == self._current_effect and self._effect_thread and self._effect_thread.is_alive():
            self._current_speed = effect_speed
            self._current_relative_brightness = brightness # Store new relative brightness
            self._apply_brightness() # Apply combined brightness
            logging.debug(f"Updated {effect} parameters: speed={effect_speed}, relative_brightness={brightness}, effective_brightness={self.pixels.brightness:.2f}")
            
            # Handle duration-based revert for parameter updates
            if duration is not None:
                self._setup_revert_thread(previous_effect, duration)
        else:
            # Different effect or no effect running, start new effect
            await self.start_effect(effect, speed, brightness, duration, color)

    async def start_effect(self, effect: str, speed=None, brightness=1.0, duration=None, color: Optional[str] = None):
        """Start an LED effect
        
        Args:
            effect: The name (string) of the LEDEffect to start
            speed: Speed of the effect (if None, uses effect's default speed)
            brightness: Relative brightness level from 0.0 to 1.0. Multiplied by the LED_BRIGHTNESS from config, and defaults to 1.0
            duration: Optional duration in milliseconds before reverting to previous effect
            color: Optional color name (used by specific effects like ROTATING_COLOR)
        """
        if effect not in self._EFFECT_MAP:
            raise ValueError(f"Unknown effect: {effect}")

        effect_info = self._EFFECT_MAP[effect]
        effect_speed = speed if speed is not None else effect_info['default_speed']
        effect_method = getattr(self, effect_info['method'])

        # Store current state before stopping the effect
        previous_effect = None
        if self._effect_thread is not None:
            previous_effect = {
                'effect': self._current_effect,
                'speed': self._current_speed,
                'brightness': self._current_relative_brightness # Store relative brightness
            }
            await self.stop_effect()
            
        self._stop_event.clear()
        self._current_speed = effect_speed
        self._current_effect = effect
        self._current_relative_brightness = brightness # Store relative brightness
        self._apply_brightness() # Apply combined brightness

        # --- Conditionally build thread arguments ---
        thread_args = ()
        if effect in ("ROTATING_COLOR", "ROTATING_BEACON"):
            if color is None:
                if effect == "ROTATING_BEACON":
                    logging.warning(f"Color parameter not provided for {effect}, defaulting to 'green'.")
                    color = "green"
                else:
                    logging.error(f"Color parameter is required for {effect} but was not provided. Stopping.")
                    self.clear()
                    return
            thread_args = (color, effect_speed)
            logging.info(f"Starting {effect} with color '{color}' and speed {effect_speed}")
        else:
            # Default case for effects only needing speed
            thread_args = (effect_speed,)
            logging.info(f"Starting {effect} with speed {effect_speed}")
        # --- End conditional arguments ---

        self._effect_thread = Thread(target=effect_method, args=thread_args) # Use dynamic args
        self._effect_thread.daemon = True
        self._effect_thread.start()
        # Logging moved up slightly to be more accurate about what *parameters* were used to start
        # logging.info(f"Started {effect} effect with speed={effect_speed}, relative_brightness={brightness}, effective_brightness={self.pixels.brightness:.2f}")
        
        if duration is not None:
            self._setup_revert_thread(previous_effect, duration)

        self.pixels.show()

    def show_color(self, color):
        """Show a specific color on the LEDs"""
        self.pixels.fill(color)
        self.pixels.show()

    def clear(self):
        """Turn off all LEDs"""
        self.pixels.fill((0, 0, 0))
        self.pixels.show()

    async def stop_effect(self, effect_name: Optional[str] = None):
        """Stop any running effect, or specific effect if provided and currently running"""
        if effect_name is None or effect_name == self._current_effect:
            self._stop_event.set()
            if self._effect_thread:
                await asyncio.to_thread(self._effect_thread.join)
                self._effect_thread = None
            self._current_effect = None
            self._current_speed = None
            self.clear()
        else:
            logging.info(f"Skipping stop of '{effect_name}' as it is not currently running. Currently running '{self._current_effect}'")

    def _apply_brightness(self):
        """Calculate and apply the effective brightness (base * relative) to the pixels."""
        effective_brightness = max(0.0, min(1.0, self._base_brightness * self._current_relative_brightness))
        self.pixels.brightness = effective_brightness
        # No logging here to avoid spamming, logging happens in start/update methods

    def set_base_brightness(self, new_base_brightness: float):
        """Set the base brightness level and update the effective brightness."""
        self._base_brightness = max(0.0, min(1.0, new_base_brightness)) # Clamp between 0.0 and 1.0
        self._apply_brightness() # Re-apply brightness immediately
        logging.info(f"Base brightness set to {self._base_brightness:.2f}. Effective brightness now: {self.pixels.brightness:.2f}")

    def get_base_brightness(self) -> float:
        """Get the current base brightness level."""
        return self._base_brightness

    # ********** Effect methods **********

    def _blue_breathing_effect(self, wait):
        """Gentle breathing effect in a soft blue color"""
        while not self._stop_event.is_set():
            for i in range(0, 100, 1):
                if self._stop_event.is_set():
                    break
                # Use sine wave for smooth breathing
                brightness = (math.sin(i * math.pi / 50) + 1) / 2
                # Soft blue color (R, G, B)
                color = (int(0 * brightness * 255),
                        int(0.5 * brightness * 255),
                        int(brightness * 255))
                self.pixels.fill(color)
                self.pixels.show()
                time.sleep(wait)

    def _green_breathing_effect(self, wait):
        """Gentle pulsing green effect indicating active conversation"""
        base_hue = 0.3  # Green in HSV
        while not self._stop_event.is_set():
            for i in range(0, 100, 1):
                if self._stop_event.is_set():
                    break
                # Subtle brightness pulsing
                brightness = 0.5 + 0.3 * (math.sin(i * math.pi / 50) + 1) / 2
                r, g, b = [int(x * 255) for x in colorsys.hsv_to_rgb(base_hue, 0.8, brightness)]
                self.pixels.fill((r, g, b))
                self.pixels.show()
                time.sleep(wait)

    def _rainbow_effect(self, wait):
        """Generate rainbow colors across all pixels"""
        while not self._stop_event.is_set():
            for j in range(255):
                if self._stop_event.is_set():
                    break
                for i in range(LEDConfig.LED_COUNT):
                    hue = (i / LEDConfig.LED_COUNT) + (j / 255.0)
                    hue = hue % 1.0
                    r, g, b = [int(x * 255) for x in colorsys.hsv_to_rgb(hue, 1.0, 1.0)]
                    self.pixels[i] = (r, g, b)
                self.pixels.show()
                time.sleep(wait)

    def _rotating_pink_blue_effect(self, wait):
        """Generate a slow rotating gradient between pink and blue colors"""
        # Call the generalized method
        self._two_color_rotation_effect("pink", "blue", wait)

    def _two_color_rotation_effect(self, color1_name: str, color2_name: str, wait: float):
        """Generate a slow rotating gradient between two specified colors"""
        try:
            rgb1 = COLORS[color1_name]
            rgb2 = COLORS[color2_name]
        except KeyError as e:
            logging.error(f"Invalid color name for two_color_rotation: {e}. Using pink/blue.")
            rgb1 = COLORS["pink"]
            rgb2 = COLORS["blue"]

        # Convert RGB to HSV to easily interpolate hues
        hsv1 = colorsys.rgb_to_hsv(rgb1[0] / 255.0, rgb1[1] / 255.0, rgb1[2] / 255.0)
        hsv2 = colorsys.rgb_to_hsv(rgb2[0] / 255.0, rgb2[1] / 255.0, rgb2[2] / 255.0)
        hue1 = hsv1[0]
        hue2 = hsv2[0]
        # Use the average saturation and value of the input colors
        saturation = (hsv1[1] + hsv2[1]) / 2.0
        value = (hsv1[2] + hsv2[2]) / 2.0

        while not self._stop_event.is_set():
            for j in range(100):  # Slower cycle with 100 steps
                if self._stop_event.is_set():
                    break
                # Create a moving gradient across all pixels
                for i in range(LEDConfig.LED_COUNT):
                    # Calculate position in the gradient cycle
                    position = (i / LEDConfig.LED_COUNT + j / 100.0) % 1.0

                    # Modified logic: A portion of the ring is off to save power.
                    # We light 75% of the ring and fade it out at the edges for a smooth look.
                    if position < 0.75:
                        # Scale position to 0-1 for the lit portion of the ring
                        gradient_position = position / 0.75
                        
                        # Interpolate hue across the lit portion
                        if gradient_position < 0.5:
                            hue = hue1 + (hue2 - hue1) * (gradient_position * 2)
                        else:
                            hue = hue2 + (hue1 - hue2) * ((gradient_position - 0.5) * 2)
                        hue %= 1.0
                        
                        # Use a sine wave for a smooth fade-in/fade-out at the gradient ends.
                        brightness_multiplier = math.sin(gradient_position * math.pi)
                        current_value = value * brightness_multiplier
                        
                        r, g, b = [int(x * 255) for x in colorsys.hsv_to_rgb(hue, saturation, current_value)]
                        self.pixels[i] = (r, g, b)
                    else:
                        # The other 25% of the ring is off.
                        self.pixels[i] = (0, 0, 0)

                self.pixels.show()
                time.sleep(wait)

    def _random_twinkling_effect(self, wait):
        """Create random twinkling pixels with dynamic fade speeds"""
        # Track the state of each pixel
        pixel_states = []
        for _ in range(LEDConfig.LED_COUNT):
            pixel_states.append({
                'active': False,
                'brightness': 0.0,
                'hue': random.random(),
                'direction': 1
            })

        while not self._stop_event.is_set():
            # Give each inactive pixel a small chance to start twinkling
            for pixel in pixel_states:
                if not pixel['active'] and random.random() < 0.01:  # 1% chance per update
                    pixel['active'] = True
                    pixel['brightness'] = 0.0
                    pixel['hue'] = random.random()  # Random hue
                    pixel['direction'] = 1
            
            # Update each active pixel
            for i, pixel in enumerate(pixel_states):
                if pixel['active']:
                    # Calculate speed based on brightness - faster near zero
                    speed_factor = 1.0 - (pixel['brightness'] ** 2)  # Quadratic falloff
                    base_step = 0.02
                    step = base_step + (base_step * 2 * speed_factor)
                    
                    # Update brightness
                    pixel['brightness'] += step * pixel['direction']
                    
                    # Check bounds and reverse direction or deactivate
                    if pixel['brightness'] >= 1.0:
                        pixel['brightness'] = 1.0
                        pixel['direction'] = -1
                    elif pixel['brightness'] <= 0.0:
                        if pixel['direction'] == -1:  # Only deactivate if we were fading out
                            pixel['active'] = False
                        pixel['brightness'] = 0.0
                    
                    # Set pixel color
                    if pixel['active']:
                        r, g, b = [int(x * 255) for x in colorsys.hsv_to_rgb(pixel['hue'], 1.0, pixel['brightness'])]
                        self.pixels[i] = (r, g, b)
                    else:
                        self.pixels[i] = (0, 0, 0)
            
            self.pixels.show()
            time.sleep(wait)

    def _rain_effect(self, wait):
        """Create a rain effect with droplets falling inward on the LED ring"""
        # Track raindrops - each is a dict with position (0.0 to 1.0) and intensity
        raindrops = []
        
        while not self._stop_event.is_set():
            # Chance to create new raindrop
            if random.random() < 0.1:  # 10% chance each cycle
                # Position is now an angle (0.0 to 1.0, representing 0 to 360 degrees)
                raindrops.append({
                    'position': random.random(),  # Random position around the ring
                    'radius': 0.0,  # Start at outer edge (0.0) and move inward (to 1.0)
                    'intensity': random.uniform(0.5, 1.0),
                    'speed': random.uniform(0.05, 0.15)  # Speed of inward movement
                })
            
            # Clear all pixels
            self.pixels.fill((0, 0, 0))
            
            # Update existing raindrops
            new_raindrops = []
            for drop in raindrops:
                # Update radius (moving inward)
                drop['radius'] += drop['speed']
                
                # If not yet fully moved to center, draw and keep the drop
                if drop['radius'] < 1.0:
                    # Calculate which LED to light based on position around ring
                    led_position = int(drop['position'] * LEDConfig.LED_COUNT) % LEDConfig.LED_COUNT
                    intensity = drop['intensity'] * (1.0 - drop['radius'])  # Fade as it moves inward
                    
                    # Blue color for the raindrop
                    blue = int(255 * intensity)
                    white = int(20 * intensity)
                    color = (white, white, blue)
                    
                    # Draw main drop pixel
                    self.pixels[led_position] = color
                    
                    # Calculate splash size based on how far inward the drop has moved
                    # No splash at start, maximum splash when halfway in
                    splash_progress = min(1.0, drop['radius'] * 2)  # Reaches max at radius 0.5
                    trail_length = int(splash_progress * 3)  # Maximum trail length of 3
                    
                    # Only draw trail if we've moved inward enough to start splashing
                    if trail_length > 0:
                        for i in range(1, trail_length + 1):
                            # Calculate trail positions (both clockwise and counter-clockwise)
                            trail_pos_cw = (led_position + i) % LEDConfig.LED_COUNT
                            trail_pos_ccw = (led_position - i) % LEDConfig.LED_COUNT
                            
                            # Calculate trail intensity - reduces with distance and overall drop intensity
                            trail_intensity = intensity * (1 - (i / (trail_length + 1))) * splash_progress * 0.7
                            trail_blue = int(255 * trail_intensity)
                            trail_white = int(50 * trail_intensity)  # Reduced white for trail
                            trail_color = (trail_white, trail_white, trail_blue)
                            
                            # Apply trail colors
                            self.pixels[trail_pos_cw] = self._blend_colors(
                                self.pixels[trail_pos_cw], trail_color)
                            self.pixels[trail_pos_ccw] = self._blend_colors(
                                self.pixels[trail_pos_ccw], trail_color)
                    
                    new_raindrops.append(drop)
            
            raindrops = new_raindrops
            self.pixels.show()
            time.sleep(wait)

    def _lightning_effect(self, wait):
        """Create a realistic lightning effect that arcs across the LED ring"""
        while not self._stop_event.is_set():
            # Determine direction of the lightning (clockwise or counterclockwise)
            clockwise = random.choice([True, False])
            
            # Choose random starting point
            start_led = random.randint(0, LEDConfig.LED_COUNT - 1)
            
            # Main lightning strike
            for intensity in [1.0, 0.8]:  # Two quick flashes
                # Clear all pixels first
                self.pixels.fill((0, 0, 0))
                
                # Calculate arc length (between 1/3 and 2/3 of the ring)
                arc_length = random.randint(LEDConfig.LED_COUNT // 3, (LEDConfig.LED_COUNT * 2) // 3)
                
                # Create the main lightning arc
                for i in range(arc_length):
                    if self._stop_event.is_set():
                        return
                        
                    current_pos = (start_led + (i if clockwise else -i)) % LEDConfig.LED_COUNT
                    
                    # Add some randomness to the arc path
                    if random.random() < 0.3:  # 30% chance to create a branch
                        branch_length = random.randint(2, 5)
                        branch_direction = random.choice([1, -1])
                        for j in range(branch_length):
                            branch_pos = (current_pos + (j * branch_direction)) % LEDConfig.LED_COUNT
                            # Dimmer branch
                            brightness = min(1.0, (1 - (j / branch_length)) * intensity * 0.7)
                            # Ensure blue tint doesn't exceed 255
                            white_val = int(255 * brightness)
                            blue_val = min(255, int(255 * brightness * 1.1))  # Reduced blue tint multiplier
                            self.pixels[branch_pos] = (white_val, white_val, blue_val)
                    
                    # Main arc - bright white with slight blue tint
                    brightness = min(1.0, intensity * (1 - (i / arc_length) * 0.3))  # Ensure brightness doesn't exceed 1.0
                    # Ensure blue tint doesn't exceed 255
                    white_val = int(255 * brightness)
                    blue_val = min(255, int(255 * brightness * 1.1))  # Reduced blue tint multiplier
                    self.pixels[current_pos] = (white_val, white_val, blue_val)
                
                self.pixels.show()
                time.sleep(0.02)  # Quick flash
            
            # Afterglow effect - ensure values stay within range
            afterglow_steps = [
                (0.5, (100, 100, min(255, 120))),  # Bluish white
                (0.3, (50, 50, min(255, 80))),     # Dimmer blue
                (0.2, (20, 20, min(255, 35)))      # Very dim blue
            ]
            
            for brightness, color in afterglow_steps:
                if self._stop_event.is_set():
                    return
                    
                # Apply afterglow only to the pixels that were part of the lightning
                for i in range(arc_length):
                    current_pos = (start_led + (i if clockwise else -i)) % LEDConfig.LED_COUNT
                    # Ensure color values stay within range
                    safe_color = tuple(min(255, int(c * brightness)) for c in color)
                    self.pixels[current_pos] = safe_color
                self.pixels.show()
                time.sleep(0.05)
            
            # Clear and wait for next strike
            self.pixels.fill((0, 0, 0))
            self.pixels.show()
            
            # Random wait between lightning strikes
            time.sleep(random.uniform(0.3, 2.0))

    def _purring_effect(self, wait):
        """Create a gentle pulsing effect that simulates a cat's purring.
        The effect creates a soft, warm glow that pulses at a speed determined by the stroke intensity.
        A faster stroke will create a more rapid purring effect."""
        # Warm, gentle color for the purr (soft peachy-pink)
        base_color = (255, 180, 147)  # RGB values for a warm, cozy glow
        
        while not self._stop_event.is_set():
            # Create two pulses per cycle to simulate the inhale/exhale of purring
            for i in range(0, 100, 1):
                if self._stop_event.is_set():
                    break
                    
                # Use two overlapping sine waves to create a more natural purring rhythm
                wave1 = math.sin(i * math.pi / 25)  # Faster wave
                wave2 = math.sin(i * math.pi / 50)  # Slower wave
                
                # # Calculate brightness variation - varies between 0.3 and 1.0
                brightness = 0.3 + (((wave1 + wave2 + 2) / 4) * 0.7)

            #    # Calculate base variation and scale it based on global brightness
            #     base_variation = ((wave1 + wave2 + 2) / 4)  # Normalized to 0-1 range
            #     # Scale variation to be proportional to global brightness
            #     # At low brightness, reduce the variation range to be more subtle
            #     variation_range = 0.3 * self.pixels.brightness  # Smaller range at lower brightness
            #     min_brightness = 1.0 - variation_range  # Higher minimum at lower brightness
            #     brightness = min_brightness + (base_variation * variation_range)

                # Apply brightness to base color
                color = tuple(int(c * brightness) for c in base_color)
                self.pixels.fill(color)
                self.pixels.show()
                time.sleep(wait)

    def _rotating_color_effect(self, color, wait):
        """Create a rotating color effect that oscillates around the given color"""
        while not self._stop_event.is_set():
            rgb_base_color = COLORS[color]
            for i in range(self.pixels.n):
                if self._stop_event.is_set():
                    break

                # Calculate the color for the current pixel
                hue = (i / self.pixels.n) + (time.time() % 1)
                hue = hue % 1.0  # Ensure hue stays within [0, 1] range
                r, g, b = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
                
                # Apply brightness to the color
                brightness = self._current_relative_brightness  # Use the current relative brightness
                r = int(r * rgb_base_color[0] * brightness)
                g = int(g * rgb_base_color[1] * brightness)
                b = int(b * rgb_base_color[2] * brightness)

                self.pixels[i] = (r, g, b)
            
            self.pixels.show()
            time.sleep(wait)

    def _rotating_green_yellow_effect(self, wait):
        """Generate a slow rotating gradient between magic green and magic blue colors"""
        # Call the generalized method with custom colors
        self._two_color_rotation_effect("magic_green", "magic_blue", wait)

    def _magical_spell_effect(self, wait):
        """Create a magical spell casting effect with charging, burst, and sparkle phases"""
        # Define magical colors
        spell_colors = [
            (138, 43, 226),   # Blue Violet
            (255, 0, 255),    # Magenta
            (0, 191, 255),    # Deep Sky Blue
            (255, 20, 147),   # Deep Pink
            (148, 0, 211),    # Dark Violet
        ]
        
        while not self._stop_event.is_set():
            # Phase 1: Charging (1-2 seconds)
            charge_duration = random.uniform(1.0, 2.0)
            charge_steps = int(charge_duration / wait)
            
            for step in range(charge_steps):
                if self._stop_event.is_set():
                    break
                
                # Calculate charge intensity (0 to 1)
                charge_progress = step / charge_steps
                
                # Create swirling effect during charge
                for i in range(LEDConfig.LED_COUNT):
                    # Multiple color waves at different speeds
                    wave1 = math.sin((i / LEDConfig.LED_COUNT + step * 0.1) * math.pi * 2) * 0.5 + 0.5
                    wave2 = math.sin((i / LEDConfig.LED_COUNT - step * 0.15) * math.pi * 3) * 0.5 + 0.5
                    
                    # Pick color based on position and time
                    color_index = int((wave1 + step * 0.05) * len(spell_colors)) % len(spell_colors)
                    base_color = spell_colors[color_index]
                    
                    # Intensity increases as we charge
                    intensity = charge_progress * wave2 * 0.8
                    
                    # Add some random flickering
                    if random.random() < 0.1:
                        intensity *= random.uniform(0.7, 1.3)
                    
                    intensity = min(1.0, intensity)
                    
                    color = tuple(int(c * intensity) for c in base_color)
                    self.pixels[i] = color
                
                self.pixels.show()
                time.sleep(wait)
            
            # Phase 2: Cast burst (0.2-0.4 seconds)
            burst_duration = random.uniform(0.2, 0.4)
            burst_steps = max(1, int(burst_duration / wait))
            burst_center = random.randint(0, LEDConfig.LED_COUNT - 1)
            
            for step in range(burst_steps):
                if self._stop_event.is_set():
                    break
                
                burst_progress = step / burst_steps
                
                # Create expanding ring effect
                for i in range(LEDConfig.LED_COUNT):
                    # Calculate distance from burst center
                    distance = min(abs(i - burst_center), 
                                 abs(i - burst_center + LEDConfig.LED_COUNT),
                                 abs(i - burst_center - LEDConfig.LED_COUNT))
                    
                    # Normalize distance
                    norm_distance = distance / (LEDConfig.LED_COUNT / 2)
                    
                    # Calculate if this pixel is in the current ring
                    ring_position = burst_progress * 1.5  # Ring expands beyond 1.0
                    ring_width = 0.3
                    
                    if abs(norm_distance - ring_position) < ring_width:
                        # Pixel is in the ring
                        ring_intensity = 1.0 - abs(norm_distance - ring_position) / ring_width
                        ring_intensity *= (1.0 - burst_progress * 0.5)  # Fade as it expands
                        
                        # Bright white-ish color for the burst
                        color = (int(255 * ring_intensity),
                                int(200 * ring_intensity),
                                int(255 * ring_intensity))
                    else:
                        color = (0, 0, 0)
                    
                    self.pixels[i] = self._blend_colors(self.pixels[i], color)
                
                self.pixels.show()
                time.sleep(wait)
            
            # Phase 3: Magical sparkles (1-2 seconds)
            sparkle_duration = random.uniform(1.0, 2.0)
            sparkle_steps = int(sparkle_duration / wait)
            
            # Initialize sparkle particles
            sparkles = []
            for _ in range(random.randint(10, 20)):
                sparkles.append({
                    'position': random.randint(0, LEDConfig.LED_COUNT - 1),
                    'lifetime': random.uniform(0.3, 1.0),
                    'age': 0.0,
                    'color': random.choice(spell_colors),
                    'twinkle_speed': random.uniform(5, 15)
                })
            
            for step in range(sparkle_steps):
                if self._stop_event.is_set():
                    break
                
                # Clear pixels
                self.pixels.fill((0, 0, 0))
                
                # Update and draw sparkles
                active_sparkles = []
                for sparkle in sparkles:
                    sparkle['age'] += wait
                    
                    if sparkle['age'] < sparkle['lifetime']:
                        # Calculate sparkle intensity
                        age_factor = 1.0 - (sparkle['age'] / sparkle['lifetime'])
                        twinkle = (math.sin(sparkle['age'] * sparkle['twinkle_speed']) + 1) / 2
                        intensity = age_factor * twinkle
                        
                        # Apply color
                        color = tuple(int(c * intensity) for c in sparkle['color'])
                        pos = sparkle['position']
                        self.pixels[pos] = self._blend_colors(self.pixels[pos], color)
                        
                        # Small chance to create a new sparkle nearby
                        if random.random() < 0.05 and len(active_sparkles) < 30:
                            new_pos = (pos + random.randint(-2, 2)) % LEDConfig.LED_COUNT
                            active_sparkles.append({
                                'position': new_pos,
                                'lifetime': random.uniform(0.2, 0.5),
                                'age': 0.0,
                                'color': sparkle['color'],
                                'twinkle_speed': random.uniform(8, 20)
                            })
                        
                        active_sparkles.append(sparkle)
                
                sparkles = active_sparkles
                self.pixels.show()
                time.sleep(wait)
            
            # Brief pause before next spell
            self.pixels.fill((0, 0, 0))
            self.pixels.show()
            time.sleep(random.uniform(0.3, 0.8))

    def _sparkling_pink_blue_effect(self, wait):
        """A low-power twinkling effect using a pink and blue palette."""
        pixel_states = [{'active': False, 'brightness': 0.0, 'hue': 0.0, 'direction': 1} for _ in range(LEDConfig.LED_COUNT)]
        
        # Pre-calculate pink and blue hues
        pink_hue = colorsys.rgb_to_hsv(*[c/255.0 for c in COLORS["pink"]])[0]
        blue_hue = colorsys.rgb_to_hsv(*[c/255.0 for c in COLORS["blue"]])[0]
        palette = [pink_hue, blue_hue]

        while not self._stop_event.is_set():
            # Chance for inactive pixels to start twinkling
            for pixel in pixel_states:
                if not pixel['active'] and random.random() < 0.02: # Slightly higher activation chance
                    pixel['active'] = True
                    pixel['brightness'] = 0.0
                    pixel['hue'] = random.choice(palette)
                    pixel['direction'] = 1
            
            # Update active pixels
            for i, pixel in enumerate(pixel_states):
                if pixel['active']:
                    speed_factor = 1.0 - (pixel['brightness'] ** 2)
                    base_step = 0.03 # A bit faster twinkling
                    step = base_step + (base_step * 2 * speed_factor)
                    
                    pixel['brightness'] += step * pixel['direction']
                    
                    if pixel['brightness'] >= 1.0:
                        pixel['brightness'] = 1.0
                        pixel['direction'] = -1
                    elif pixel['brightness'] <= 0.0:
                        if pixel['direction'] == -1:
                            pixel['active'] = False
                        pixel['brightness'] = 0.0
                    
                    if pixel['active']:
                        # Use a fixed saturation for more vibrant colors
                        saturation = 0.85 
                        r, g, b = [int(x * 255) for x in colorsys.hsv_to_rgb(pixel['hue'], saturation, pixel['brightness'])]
                        self.pixels[i] = (r, g, b)
                    else:
                        self.pixels[i] = (0, 0, 0)
            
            self.pixels.show()
            time.sleep(wait)

    def _rotating_beacon_effect(self, color_name, wait):
        """A rotating light with a fading tail, in a specified color."""
        if color_name not in COLORS:
            logging.error(f"Invalid color name '{color_name}' for rotating_beacon. Defaulting to green.")
            color_name = 'green'
        
        head_color = COLORS[color_name]
        trail_length = 8
        
        # Create a color palette for the trail with exponential decay
        trail_colors = [tuple(int(c * math.pow(0.65, i)) for c in head_color) for i in range(1, trail_length + 1)]

        position = 0
        while not self._stop_event.is_set():
            if self._stop_event.is_set():
                break

            self.pixels.fill((0, 0, 0))

            # Draw the head
            head_pixel_index = int(position) % LEDConfig.LED_COUNT
            self.pixels[head_pixel_index] = head_color

            # Draw the trail
            for i in range(trail_length):
                pixel_index = (int(position) - 1 - i + LEDConfig.LED_COUNT) % LEDConfig.LED_COUNT
                if i < len(trail_colors):
                    self.pixels[pixel_index] = trail_colors[i]
            
            self.pixels.show()

            # Using self._current_speed allows for dynamic updates from start_or_update_effect.
            # A lower speed value (wait time) means a faster rotation.
            time.sleep(self._current_speed)
            position = (position + 1) % LEDConfig.LED_COUNT

    # ********** Planet Tour Effects **********

    def _warp_drive_effect(self, wait):
        """Simulates traveling through space at high speed, with stars streaking past."""
        # This effect should create the illusion of forward motion.
        # It could be achieved with pixels moving from the center outwards,
        # or from one point on the ring expanding across.
        # For a single ring, we can have lights streaking from a "front" point.
        pass

    def _mercury_effect(self, wait):
        """Represents Mercury. A rocky, cratered surface with a slow, dim rotation."""
        # This could be a slow rotation of gray/dark gray patches to show a rocky surface.
        # The light should be dim to reflect its lack of atmosphere.
        pass

    def _venus_effect(self, wait):
        """Represents Venus. A thick, swirling atmosphere of yellowish clouds."""
        # This could be a slow, swirling mix of yellow and white colors,
        # maybe with a gentle breathing effect to simulate a dense atmosphere.
        pass

    def _earth_effect(self, wait):
        """Represents Earth. Rotating blue oceans and green/brown continents."""
        # A rotation effect mixing blue (oceans) and green (land).
        # We can reuse the logic from _two_color_rotation_effect.
        self._two_color_rotation_effect("earth_blue", "earth_green", wait)

    def _mars_effect(self, wait):
        """Represents Mars. The 'Red Planet' with a slow rotation and reddish-orange color."""
        # A simple rotation of reddish-orange colors, perhaps with some darker patches for terrain.
        self._two_color_rotation_effect("mars_red", "black", wait)

    def _jupiter_effect(self, wait):
        """Represents Jupiter. Fast-rotating bands of orange, brown, and white clouds, with a Great Red Spot."""
        # This effect should show bands of color rotating. The Great Red Spot could be a persistent
        # cluster of red LEDs that moves with the rotation.
        num_leds = LEDConfig.LED_COUNT
        offset = 0
        great_red_spot_pos = num_leds // 4
        great_red_spot_size = 3

        while not self._stop_event.is_set():
            offset += 1 # Faster rotation
            for i in range(num_leds):
                pos = (i + offset) % num_leds
                
                # Check for Great Red Spot
                is_spot = False
                for s in range(great_red_spot_size):
                    if pos == (great_red_spot_pos + s) % num_leds:
                        is_spot = True
                        break

                if is_spot:
                    self.pixels[i] = COLORS["mars_red"]
                else:
                    # Create bands
                    if (pos // 4) % 3 == 0:
                        self.pixels[i] = COLORS["jupiter_orange"]
                    elif (pos // 4) % 3 == 1:
                        self.pixels[i] = COLORS["jupiter_white"]
                    else:
                        self.pixels[i] = COLORS["brown"]

            self.pixels.show()
            time.sleep(wait)


    def _saturn_effect(self, wait):
        """Represents Saturn. Pale gold planet with its iconic rings."""
        # For a single ring, this is difficult. It will be a static pale gold color
        # with a slightly brighter band to represent the rings.
        num_leds = LEDConfig.LED_COUNT
        planet_color = COLORS["saturn_gold"]
        ring_color = COLORS["white"]
        
        for i in range(num_leds):
            # Make a band of LEDs slightly brighter for the "ring"
            if num_leds // 3 <= i <= num_leds * 2 // 3:
                # Simple blend to make ring color brighter
                r = min(255, planet_color[0] + 40)
                g = min(255, planet_color[1] + 40)
                b = min(255, planet_color[2] + 40)
                self.pixels[i] = (r, g, b)
            else:
                self.pixels[i] = planet_color
        
        self.pixels.show()
        # This is a static effect, but we still need to loop to prevent the thread from exiting.
        while not self._stop_event.is_set():
            time.sleep(0.1)


    def _uranus_effect(self, wait):
        """Represents Uranus. A pale blue, hazy planet, tilted on its side."""
        # A soft, uniform pale blue with a very slow, subtle pulse.
        self.pixels.fill(COLORS["uranus_blue"])
        self.pixels.show()
        # This is a static effect, but we still need to loop to prevent the thread from exiting.
        while not self._stop_event.is_set():
            time.sleep(0.1)


    def _neptune_effect(self, wait):
        """Represents Neptune. A deep blue, windy planet."""
        # A deep blue color with fast-moving, subtle streaks of lighter blue to show high-speed winds.
        num_leds = LEDConfig.LED_COUNT
        base_color = COLORS["neptune_blue"]
        streaks = []

        while not self._stop_event.is_set():
            if random.random() < 0.4: # Chance for new streak
                streaks.append({
                    'pos': random.randint(0, num_leds -1),
                    'len': random.randint(3, 7),
                    'brightness': random.uniform(0.3, 0.7),
                    'life': random.randint(10, 20) # frames to live
                })
            
            self.pixels.fill(base_color)
            
            active_streaks = []
            for streak in streaks:
                streak['life'] -= 1
                if streak['life'] > 0:
                    active_streaks.append(streak)
                    for i in range(streak['len']):
                        pos = (streak['pos'] + i) % num_leds
                        # Fade the streak along its length
                        brightness = streak['brightness'] * (1 - (i / streak['len']))
                        # Blend the streak color with the base color
                        streak_color = (
                            int(base_color[0] + (255 - base_color[0]) * brightness),
                            int(base_color[1] + (255 - base_color[1]) * brightness),
                            int(base_color[2] + (255 - base_color[2]) * brightness)
                        )
                        self.pixels[pos] = streak_color
            
            streaks = active_streaks
            self.pixels.show()
            time.sleep(wait)


class LEDManagerRings(LEDManager):
    """
    LED Manager specifically for setups with two concentric rings.
    Assumes the first LED_COUNT_RING1 LEDs belong to the outer ring,
    and the next LED_COUNT_RING2 LEDs belong to the inner ring.
    """
    def __init__(self, initial_brightness=LEDConfig.LED_BRIGHTNESS):
        super().__init__(initial_brightness)
        if LEDConfig.LED_COUNT != (LEDConfig.LED_COUNT_RING1 + LEDConfig.LED_COUNT_RING2):
            logging.warning(f"LED_COUNT ({LEDConfig.LED_COUNT}) does not match sum of RING1 ({LEDConfig.LED_COUNT_RING1}) and RING2 ({LEDConfig.LED_COUNT_RING2}). Ring slicing might be incorrect.")
        logging.info(f"LEDManagerRings initialized for dual rings: Ring 1 ({LEDConfig.LED_COUNT_RING1} LEDs), Ring 2 ({LEDConfig.LED_COUNT_RING2} LEDs)")

    @property
    def ring1_pixels(self):
        """Returns a slice representing the pixels of the first (outer) ring."""
        return self.pixels[0:LEDConfig.LED_COUNT_RING1]

    @property
    def ring2_pixels(self):
        """Returns a slice representing the pixels of the second (inner) ring."""
        return self.pixels[LEDConfig.LED_COUNT_RING1:LEDConfig.LED_COUNT]

    def _blue_breathing_effect(self, wait):
        """Gentle blue breathing, inner ring slightly out of phase."""
        num_leds_ring1 = LEDConfig.LED_COUNT_RING1
        num_leds_ring2 = LEDConfig.LED_COUNT_RING2
        
        if num_leds_ring1 <= 0 or num_leds_ring2 <= 0:
            logging.warning("Blue breathing effect requires both rings to have LEDs. Falling back to default.")
            return super()._blue_breathing_effect(wait)

        phase_offset = math.pi / 2 # 90 degrees out of phase

        while not self._stop_event.is_set():
            for i in range(0, 100, 1):
                if self._stop_event.is_set():
                    break
                
                # Calculate brightness for outer ring
                angle_outer = i * math.pi / 50
                brightness_outer = (math.sin(angle_outer) + 1) / 2
                color_outer = (int(0 * brightness_outer * 255),
                               int(0.5 * brightness_outer * 255),
                               int(brightness_outer * 255))

                # Calculate brightness for inner ring (out of phase)
                angle_inner = angle_outer + phase_offset
                brightness_inner = (math.sin(angle_inner) + 1) / 2
                color_inner = (int(0 * brightness_inner * 255),
                               int(0.5 * brightness_inner * 255),
                               int(brightness_inner * 255))

                # Apply colors to rings
                for idx in range(num_leds_ring1):
                    self.pixels[idx] = color_outer
                for idx in range(num_leds_ring2):
                    self.pixels[num_leds_ring1 + idx] = color_inner
                    
                self.pixels.show()
                time.sleep(wait)

    def _green_breathing_effect(self, wait):
        """Override: Gentle green breathing, inner ring slightly out of phase."""
        num_leds_ring1 = LEDConfig.LED_COUNT_RING1
        num_leds_ring2 = LEDConfig.LED_COUNT_RING2

        if num_leds_ring1 <= 0 or num_leds_ring2 <= 0:
            logging.warning("Green breathing effect requires both rings to have LEDs. Falling back to default.")
            return super()._green_breathing_effect(wait)

        base_hue = 0.3  # Green in HSV
        phase_offset = math.pi / 2 # 90 degrees out of phase

        while not self._stop_event.is_set():
            for i in range(0, 100, 1):
                if self._stop_event.is_set():
                    break
                
                # Calculate brightness for outer ring
                angle_outer = i * math.pi / 50
                # Subtle brightness pulsing (0.5 to 0.8)
                brightness_outer = 0.5 + 0.3 * (math.sin(angle_outer) + 1) / 2
                r_outer, g_outer, b_outer = [int(x * 255) for x in colorsys.hsv_to_rgb(base_hue, 0.8, brightness_outer)]
                color_outer = (r_outer, g_outer, b_outer)

                # Calculate brightness for inner ring (out of phase)
                angle_inner = angle_outer + phase_offset
                brightness_inner = 0.5 + 0.3 * (math.sin(angle_inner) + 1) / 2
                r_inner, g_inner, b_inner = [int(x * 255) for x in colorsys.hsv_to_rgb(base_hue, 0.8, brightness_inner)]
                color_inner = (r_inner, g_inner, b_inner)

                # Apply colors to rings
                for idx in range(num_leds_ring1):
                    self.pixels[idx] = color_outer
                for idx in range(num_leds_ring2):
                    self.pixels[num_leds_ring1 + idx] = color_inner
                    
                self.pixels.show()
                time.sleep(wait)

    def _rotating_pink_blue_effect(self, wait):
        """Override: Generate rotating gradients between pink and blue, counter-rotating on the inner ring."""
        # Call the generalized method for rings
        self._two_color_rotation_effect("pink", "blue", wait)

    def _two_color_rotation_effect(self, color1_name: str, color2_name: str, wait: float):
        """Override: Generate rotating gradients between two specified colors, counter-rotating on the inner ring."""
        try:
            rgb1 = COLORS[color1_name]
            rgb2 = COLORS[color2_name]
        except KeyError as e:
            logging.error(f"Invalid color name for two_color_rotation (rings): {e}. Using pink/blue.")
            rgb1 = COLORS["pink"]
            rgb2 = COLORS["blue"]

        # Convert RGB to HSV
        hsv1 = colorsys.rgb_to_hsv(rgb1[0] / 255.0, rgb1[1] / 255.0, rgb1[2] / 255.0)
        hsv2 = colorsys.rgb_to_hsv(rgb2[0] / 255.0, rgb2[1] / 255.0, rgb2[2] / 255.0)
        hue1 = hsv1[0]
        hue2 = hsv2[0]
        # Use the average saturation and value of the input colors
        saturation = (hsv1[1] + hsv2[1]) / 2.0
        value = (hsv1[2] + hsv2[2]) / 2.0

        num_leds_ring1 = LEDConfig.LED_COUNT_RING1
        num_leds_ring2 = LEDConfig.LED_COUNT_RING2

        if num_leds_ring1 <= 0 or num_leds_ring2 <= 0:
            logging.warning("Two color rotation effect requires both rings to have LEDs. Stopping effect.")
            self.clear()
            return

        while not self._stop_event.is_set():
            for j in range(100):  # Cycle steps
                if self._stop_event.is_set():
                    break

                # Outer ring (Ring 1) - Normal rotation
                for i in range(num_leds_ring1):
                    position = (i / num_leds_ring1 + j / 100.0) % 1.0
                    if position < 0.75:
                        gradient_position = position / 0.75
                        if gradient_position < 0.5:
                            hue = hue1 + (hue2 - hue1) * (gradient_position * 2)
                        else:
                            hue = hue2 + (hue1 - hue2) * ((gradient_position - 0.5) * 2)
                        hue %= 1.0
                        brightness_multiplier = math.sin(gradient_position * math.pi)
                        current_value = value * brightness_multiplier
                        r, g, b = [int(x * 255) for x in colorsys.hsv_to_rgb(hue, saturation, current_value)]
                        self.pixels[i] = (r, g, b)
                    else:
                        self.pixels[i] = (0, 0, 0)

                # Inner ring (Ring 2) - Counter-rotation
                for i in range(num_leds_ring2):
                    # Use negative j for counter-rotation
                    position = (i / num_leds_ring2 - j / 100.0) % 1.0
                    if position < 0.75:
                        gradient_position = position / 0.75
                        if gradient_position < 0.5:
                            hue = hue1 + (hue2 - hue1) * (gradient_position * 2)
                        else:
                            hue = hue2 + (hue1 - hue2) * ((gradient_position - 0.5) * 2)
                        hue %= 1.0
                        brightness_multiplier = math.sin(gradient_position * math.pi)
                        current_value = value * brightness_multiplier
                        r, g, b = [int(x * 255) for x in colorsys.hsv_to_rgb(hue, saturation, current_value)]
                        # Apply to the correct slice of pixels
                        self.pixels[num_leds_ring1 + i] = (r, g, b)
                    else:
                        self.pixels[num_leds_ring1 + i] = (0, 0, 0)

                self.pixels.show()
                time.sleep(wait)

    def _rainbow_effect(self, wait):
        """Override: Generate counter-rotating rainbow colors on the two rings."""
        num_leds_ring1 = LEDConfig.LED_COUNT_RING1
        num_leds_ring2 = LEDConfig.LED_COUNT_RING2

        if num_leds_ring1 <= 0 or num_leds_ring2 <= 0:
            logging.warning("Rotating rainbow effect requires both rings to have LEDs. Falling back to default.")
            # Fallback to the original implementation if rings aren't configured properly
            return super()._rainbow_effect(wait)

        while not self._stop_event.is_set():
            for j in range(255):
                if self._stop_event.is_set():
                    break

                # Outer ring (Ring 1) - Clockwise rotation
                for i in range(num_leds_ring1):
                    hue = (i / num_leds_ring1 + j / 255.0) % 1.0
                    r, g, b = [int(x * 255) for x in colorsys.hsv_to_rgb(hue, 1.0, 1.0)]
                    self.pixels[i] = (r, g, b)

                # Inner ring (Ring 2) - Counter-clockwise rotation
                for i in range(num_leds_ring2):
                    # Use negative j for counter-rotation
                    hue = (i / num_leds_ring2 - j / 255.0) % 1.0
                    r, g, b = [int(x * 255) for x in colorsys.hsv_to_rgb(hue, 1.0, 1.0)]
                    # Apply to the correct slice of pixels
                    self.pixels[num_leds_ring1 + i] = (r, g, b)

                self.pixels.show()
                time.sleep(wait)

    def _random_twinkling_effect(self, wait):
        """Override: Create random twinkling pixels on the outer ring and a slow white pulse on the inner ring."""
        num_leds_ring1 = LEDConfig.LED_COUNT_RING1
        num_leds_ring2 = LEDConfig.LED_COUNT_RING2

        if num_leds_ring1 <= 0 or num_leds_ring2 <= 0:
            logging.warning("Random twinkling effect requires both rings to have LEDs. Falling back to default.")
            return super()._random_twinkling_effect(wait)

        # Track the state of each pixel for the outer ring
        pixel_states_ring1 = [{'active': False, 'brightness': 0.0, 'hue': random.random(), 'direction': 1} for _ in range(num_leds_ring1)]
        # Track the state of each pixel for the inner ring
        pixel_states_ring2 = [{'active': False, 'brightness': 0.0, 'hue': random.random(), 'direction': 1} for _ in range(num_leds_ring2)]
        # Parameters for inner ring twinkling
        inner_ring_activation_chance = 0.02 # Double the chance of the outer ring (0.01)
        inner_ring_base_step = 0.04 # Double the base speed of the outer ring (0.02)

        while not self._stop_event.is_set():
            # Update Ring 1 (Outer Ring) - Twinkling
            for i, pixel in enumerate(pixel_states_ring1):
                # Chance to activate
                if not pixel['active'] and random.random() < 0.01: # Outer ring activation chance
                    pixel['active'] = True
                    pixel['brightness'] = 0.0
                    pixel['hue'] = random.random()
                    pixel['direction'] = 1

                # Update active pixel
                if pixel['active']:
                    speed_factor = 1.0 - (pixel['brightness'] ** 2)
                    base_step = 0.02 # Outer ring base step
                    step = base_step + (base_step * 2 * speed_factor)
                    pixel['brightness'] += step * pixel['direction']

                    # Check bounds
                    if pixel['brightness'] >= 1.0:
                        pixel['brightness'] = 1.0
                        pixel['direction'] = -1
                    elif pixel['brightness'] <= 0.0:
                        if pixel['direction'] == -1:
                             # Only deactivate when fading out
                            pixel['active'] = False
                        pixel['brightness'] = 0.0

                    # Set pixel color
                    if pixel['active']:
                        r, g, b = [int(x * 255) for x in colorsys.hsv_to_rgb(pixel['hue'], 1.0, pixel['brightness'])]
                        self.pixels[i] = (r, g, b)
                    else:
                         # Ensure pixel is off when deactivated after fading
                        self.pixels[i] = (0, 0, 0)
                elif not pixel['active']: # Ensure inactive pixels are off
                    self.pixels[i] = (0, 0, 0)

            # Update Ring 2 (Inner Ring) - Faster Colorful Twinkling
            for i, pixel in enumerate(pixel_states_ring2):
                pixel_index_in_strip = num_leds_ring1 + i
                # Chance to activate
                if not pixel['active'] and random.random() < inner_ring_activation_chance:
                    pixel['active'] = True
                    pixel['brightness'] = 0.0
                    pixel['hue'] = random.random()
                    pixel['direction'] = 1

                # Update active pixel
                if pixel['active']:
                    speed_factor = 1.0 - (pixel['brightness'] ** 2)
                    step = inner_ring_base_step + (inner_ring_base_step * 2 * speed_factor)
                    pixel['brightness'] += step * pixel['direction']

                    # Check bounds
                    if pixel['brightness'] >= 1.0:
                        pixel['brightness'] = 1.0
                        pixel['direction'] = -1
                    elif pixel['brightness'] <= 0.0:
                        if pixel['direction'] == -1:
                             # Only deactivate when fading out
                            pixel['active'] = False
                        pixel['brightness'] = 0.0

                    # Set pixel color
                    if pixel['active']:
                        r, g, b = [int(x * 255) for x in colorsys.hsv_to_rgb(pixel['hue'], 1.0, pixel['brightness'])]
                        self.pixels[pixel_index_in_strip] = (r, g, b)
                    else:
                         # Ensure pixel is off when deactivated after fading
                        self.pixels[pixel_index_in_strip] = (0, 0, 0)
                elif not pixel['active']: # Ensure inactive pixels are off
                    self.pixels[pixel_index_in_strip] = (0, 0, 0)

            self.pixels.show()
            time.sleep(wait)

    def _rain_effect(self, wait):
        """Override: Rain appears as a splash on the inner ring, then falls to the outer ring and fades."""
        num_leds_ring1 = LEDConfig.LED_COUNT_RING1
        num_leds_ring2 = LEDConfig.LED_COUNT_RING2
        if num_leds_ring1 <= 0 or num_leds_ring2 <= 0:
            logging.warning("Rain effect requires both rings to have LEDs. Falling back to default.")
            return super()._rain_effect(wait)

        raindrops = [] # List to store active raindrops
        # Phase durations (these are relative multipliers for 'wait')
        splash_duration_factor = 15
        fall_duration_factor = 10
        fade_duration_factor = 50

        # Splash visual parameters
        splash_color = (180, 255, 255) # Bright cyan/white
        splash_spread = 1 # Number of LEDs adjacent to center to light up

        # Fall/Fade visual parameters
        fall_color = (50, 50, 255) # Blue

        while not self._stop_event.is_set():
            # Chance to create new raindrop
            if random.random() < 0.08: # Adjust probability as needed
                raindrops.append({
                    'angle': random.random(), # 0.0 to 1.0
                    'phase': 'inner_splash',
                    'progress': 0.0, # Normalized progress within phase (0.0 to 1.0)
                    'speed': random.uniform(0.8, 1.2) # Slight speed variation per drop
                })

            # Clear all pixels (using temporary buffer for blending)
            current_pixels = [(0, 0, 0)] * LEDConfig.LED_COUNT

            new_raindrops = []
            for drop in raindrops:
                # Update progress
                phase_duration = 1.0 # Default, will be overridden
                if drop['phase'] == 'inner_splash':
                    phase_duration = splash_duration_factor * wait
                elif drop['phase'] == 'outer_fall':
                    phase_duration = fall_duration_factor * wait
                elif drop['phase'] == 'outer_fade':
                    phase_duration = fade_duration_factor * wait

                # Avoid division by zero if wait is very small or zero
                if phase_duration > 0:
                     drop['progress'] += (drop['speed'] * wait) / phase_duration
                else: # If duration is zero, instantly finish phase
                     drop['progress'] = 1.0

                keep_drop = True
                if drop['phase'] == 'inner_splash':
                    if drop['progress'] >= 1.0:
                        drop['phase'] = 'outer_fall'
                        drop['progress'] = 0.0
                    else:
                        # Calculate splash effect - peak brightness mid-phase
                        brightness = math.sin(drop['progress'] * math.pi) # 0 -> 1 -> 0
                        center_led = int(drop['angle'] * num_leds_ring2) % num_leds_ring2
                        for i in range(-splash_spread, splash_spread + 1):
                            led_index_inner = (center_led + i) % num_leds_ring2
                            # Fade intensity with distance from center
                            dist_factor = 1.0 - (abs(i) / (splash_spread + 1))
                            current_brightness = brightness * dist_factor
                            color = tuple(int(c * current_brightness) for c in splash_color)
                            # Apply to inner ring slice
                            pixel_index_in_strip = num_leds_ring1 + led_index_inner
                            current_pixels[pixel_index_in_strip] = self._blend_colors(
                                current_pixels[pixel_index_in_strip], color)

                elif drop['phase'] == 'outer_fall':
                    if drop['progress'] >= 1.0:
                        drop['phase'] = 'outer_fade'
                        drop['progress'] = 0.0
                    else:
                        # Light up the single LED on the outer ring
                        led_index_outer = int(drop['angle'] * num_leds_ring1) % num_leds_ring1
                        current_pixels[led_index_outer] = self._blend_colors(
                            current_pixels[led_index_outer], fall_color)

                elif drop['phase'] == 'outer_fade':
                    if drop['progress'] >= 1.0:
                        keep_drop = False # Drop fades out completely
                    else:
                        # Fade out the LED on the outer ring
                        brightness = 1.0 - drop['progress']
                        led_index_outer = int(drop['angle'] * num_leds_ring1) % num_leds_ring1
                        color = tuple(int(c * brightness) for c in fall_color)
                        current_pixels[led_index_outer] = self._blend_colors(
                            current_pixels[led_index_outer], color)

                if keep_drop:
                    new_raindrops.append(drop)

            raindrops = new_raindrops

            # Update the actual pixels
            for i in range(LEDConfig.LED_COUNT):
                self.pixels[i] = current_pixels[i]
            self.pixels.show()
            time.sleep(wait)

    def _lightning_effect(self, wait):
        """Override: Lightning originates with a flicker on the inner ring, then arcs across the outer ring."""
        num_leds_ring1 = LEDConfig.LED_COUNT_RING1
        num_leds_ring2 = LEDConfig.LED_COUNT_RING2
        if num_leds_ring1 <= 0 or num_leds_ring2 <= 0:
            logging.warning("Lightning effect requires both rings to have LEDs. Falling back to default.")
            return super()._lightning_effect(wait)

        flicker_color = (220, 220, 255) # Very light blue/white
        arc_color_base = (255, 255, 255)
        arc_color_tint = (0, 0, 50) # Slight blue tint added to arc
        afterglow_colors = [
            (150, 150, 180), # Bluish white
            (80, 80, 120),   # Dimmer blue
            (30, 30, 50)     # Very dim blue
        ]

        while not self._stop_event.is_set():
            # Choose origin angle and calculate corresponding LEDs
            origin_angle = random.random()
            origin_led_inner = int(origin_angle * num_leds_ring2) % num_leds_ring2
            start_led_outer = int(origin_angle * num_leds_ring1) % num_leds_ring1

            # 1. Inner Ring Flicker
            flicker_frames = random.randint(2, 4)
            for frame in range(flicker_frames):
                if self._stop_event.is_set(): return
                self.pixels.fill((0, 0, 0))
                # Light up 1 or 2 pixels around origin
                flicker_brightness = random.uniform(0.6, 1.0)
                color = tuple(int(c * flicker_brightness) for c in flicker_color)
                inner_idx1 = num_leds_ring1 + origin_led_inner
                self.pixels[inner_idx1] = color
                # Occasionally light adjacent pixel too
                if random.random() < 0.5:
                    adj_offset = random.choice([-1, 1])
                    inner_idx2 = num_leds_ring1 + (origin_led_inner + adj_offset) % num_leds_ring2
                    self.pixels[inner_idx2] = color
                self.pixels.show()
                time.sleep(0.015) # Very quick flicker frames

            # 2. Outer Ring Arc (adapting parent logic)
            clockwise = random.choice([True, False])
            arc_length = random.randint(num_leds_ring1 // 3, (num_leds_ring1 * 2) // 3)

            for intensity_factor in [1.0, 0.8]: # Two quick flashes
                if self._stop_event.is_set(): return
                # Clear only outer ring for the arc drawing phase
                for i in range(num_leds_ring1):
                    self.pixels[i] = (0, 0, 0)
                # Keep inner flicker briefly visible during first arc flash if desired
                # Or clear inner ring too: self.pixels.fill((0,0,0))

                arc_pixels_indices = set()
                for i in range(arc_length):
                    if self._stop_event.is_set(): return
                    current_pos_outer = (start_led_outer + (i if clockwise else -i)) % num_leds_ring1
                    arc_pixels_indices.add(current_pos_outer)

                    # Branching logic (applied to outer ring)
                    if random.random() < 0.3:
                        branch_length = random.randint(2, 4)
                        branch_direction = random.choice([1, -1])
                        for j in range(branch_length):
                            branch_pos_outer = (current_pos_outer + (j * branch_direction)) % num_leds_ring1
                            arc_pixels_indices.add(branch_pos_outer)
                            brightness = max(0, min(1.0, (1 - (j / branch_length)) * intensity_factor * 0.7))
                            color = tuple(min(255, int(base * brightness + tint * brightness)) for base, tint in zip(arc_color_base, arc_color_tint))
                            self.pixels[branch_pos_outer] = self._blend_colors(self.pixels[branch_pos_outer], color)

                    # Main arc segment (applied to outer ring)
                    brightness = max(0, min(1.0, intensity_factor * (1 - (i / arc_length) * 0.3)))
                    color = tuple(min(255, int(base * brightness + tint * brightness)) for base, tint in zip(arc_color_base, arc_color_tint))
                    self.pixels[current_pos_outer] = self._blend_colors(self.pixels[current_pos_outer], color)

                self.pixels.show()
                time.sleep(0.025) # Quick flash

            # 3. Afterglow (Outer Ring focus)
            # Store final arc pixels before clearing inner ring
            final_arc_pixels = {idx: self.pixels[idx] for idx in arc_pixels_indices}
            self.pixels.fill((0, 0, 0)) # Clear everything before afterglow

            for i, ag_color in enumerate(afterglow_colors):
                if self._stop_event.is_set(): return
                # Apply afterglow to the pixels that were part of the outer arc
                for idx in arc_pixels_indices:
                     # Use the brightness of the final arc pixel to scale the afterglow color?
                     # Or just apply the afterglow color directly? Let's try direct first.
                    self.pixels[idx] = ag_color
                # Optional: very faint quick afterglow on inner origin
                if i == 0: # Only on first step
                     inner_idx = num_leds_ring1 + origin_led_inner
                     self.pixels[inner_idx] = tuple(int(c*0.3) for c in afterglow_colors[-1]) # Faint version of last afterglow color

                self.pixels.show()
                time.sleep(0.06)

            # 4. Clear and Wait
            self.pixels.fill((0, 0, 0))
            self.pixels.show()
            time.sleep(random.uniform(0.5, 2.5)) # Wait for next strike

    def _purring_effect(self, wait):
        """Override: Outer ring pulses warm color, inner ring steady warm glow."""
        num_leds_ring1 = LEDConfig.LED_COUNT_RING1
        num_leds_ring2 = LEDConfig.LED_COUNT_RING2

        if num_leds_ring1 <= 0 or num_leds_ring2 <= 0:
            logging.warning("Purring effect requires both rings to have LEDs. Falling back to default.")
            return super()._purring_effect(wait)

        base_color = (255, 180, 147)  # Warm peachy-pink
        inner_ring_brightness = 0.2 # Dim steady glow for inner ring
        inner_ring_color = tuple(int(c * inner_ring_brightness) for c in base_color)
        
        while not self._stop_event.is_set():
            # Calculate purring brightness for outer ring
            for i in range(0, 100, 1):
                if self._stop_event.is_set():
                    break
                    
                # Use two overlapping sine waves for outer ring pulse
                wave1 = math.sin(i * math.pi / 25)  # Faster wave
                wave2 = math.sin(i * math.pi / 50)  # Slower wave
                
                # Brightness varies between 0.3 and 1.0 for outer ring
                brightness_outer = 0.3 + (((wave1 + wave2 + 2) / 4) * 0.7)
                color_outer = tuple(int(c * brightness_outer) for c in base_color)

                # Apply colors
                # Outer ring - pulsing purr
                for idx in range(num_leds_ring1):
                    self.pixels[idx] = color_outer
                # Inner ring - steady dim glow
                for idx in range(num_leds_ring2):
                    self.pixels[num_leds_ring1 + idx] = inner_ring_color
                    
                self.pixels.show()
                time.sleep(wait)

    def _rotating_color_effect(self, color, wait):
        """Override: Rotates hues around a base color, counter-rotating on inner ring."""
        num_leds_ring1 = LEDConfig.LED_COUNT_RING1
        num_leds_ring2 = LEDConfig.LED_COUNT_RING2

        if num_leds_ring1 <= 0 or num_leds_ring2 <= 0:
            logging.warning("Rotating color effect requires both rings to have LEDs. Falling back to default.")
            # Call super, but need to pass the color argument
            return super()._rotating_color_effect(color, wait) 

        if color not in COLORS:
            logging.error(f"Invalid color name '{color}' for rotating_color_effect. Falling back to white.")
            rgb_base_color = COLORS["white"]
        else:
            rgb_base_color = COLORS[color]

        # Normalize base color components to 0-1 range for multiplication
        rgb_base_normalized = tuple(c / 255.0 for c in rgb_base_color)

        offset = 0.0
        while not self._stop_event.is_set():
            # Outer ring - Clockwise rotation
            for i in range(num_leds_ring1):
                # Calculate hue based on position and time offset
                hue = (i / num_leds_ring1 + offset) % 1.0
                # Convert hue to RGB (full saturation and value)
                r_hue, g_hue, b_hue = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
                # Modulate by base color and apply global brightness implicitly via self.pixels.brightness
                r = int(r_hue * rgb_base_color[0])
                g = int(g_hue * rgb_base_color[1])
                b = int(b_hue * rgb_base_color[2])
                self.pixels[i] = (r, g, b)

            # Inner ring - Counter-clockwise rotation
            for i in range(num_leds_ring2):
                # Negative offset for counter-rotation
                hue = (i / num_leds_ring2 - offset) % 1.0 
                r_hue, g_hue, b_hue = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
                r = int(r_hue * rgb_base_color[0])
                g = int(g_hue * rgb_base_color[1])
                b = int(b_hue * rgb_base_color[2])
                self.pixels[num_leds_ring1 + i] = (r, g, b)
            
            self.pixels.show()
            # Increment offset based on speed (wait time)
            # Adjust the multiplier (e.g., 10) to control rotation speed relative to 'wait'
            offset += (wait * 10) 
            offset %= 1.0 # Keep offset within [0, 1]
            time.sleep(wait) # Use the actual wait time for frame delay

    # Correctly placed override for green/yellow rotation
    def _rotating_green_yellow_effect(self, wait):
        """Override: Generate rotating magic green/blue gradients, counter-rotating on the inner ring."""
        # Call the generalized method for rings with custom colors
        self._two_color_rotation_effect("magic_green", "magic_blue", wait)

    def _magical_spell_effect(self, wait):
        """Override: Magical spell with inner ring charging and outer ring burst"""
        num_leds_ring1 = LEDConfig.LED_COUNT_RING1
        num_leds_ring2 = LEDConfig.LED_COUNT_RING2
        
        if num_leds_ring1 <= 0 or num_leds_ring2 <= 0:
            logging.warning("Magical spell effect requires both rings to have LEDs. Falling back to default.")
            return super()._magical_spell_effect(wait)
        
        # Define magical colors
        spell_colors = [
            (138, 43, 226),   # Blue Violet
            (255, 0, 255),    # Magenta
            (0, 191, 255),    # Deep Sky Blue
            (255, 20, 147),   # Deep Pink
            (148, 0, 211),    # Dark Violet
        ]
        
        while not self._stop_event.is_set():
            # Phase 1: Inner ring charges with swirling energy
            charge_duration = random.uniform(1.5, 2.5)
            charge_steps = int(charge_duration / wait)
            
            for step in range(charge_steps):
                if self._stop_event.is_set():
                    break
                
                charge_progress = step / charge_steps
                
                # Inner ring - intense swirling charge
                for i in range(num_leds_ring2):
                    wave = math.sin((i / num_leds_ring2 - step * 0.2) * math.pi * 4) * 0.5 + 0.5
                    color_index = int((i + step * 0.1) * len(spell_colors)) % len(spell_colors)
                    base_color = spell_colors[color_index]
                    
                    # Intensity builds up
                    intensity = charge_progress * wave
                    if random.random() < 0.2:  # More frequent flickers
                        intensity *= random.uniform(0.8, 1.2)
                    intensity = min(1.0, intensity)
                    
                    color = tuple(int(c * intensity) for c in base_color)
                    self.pixels[num_leds_ring1 + i] = color
                
                # Outer ring - subtle anticipation glow
                outer_glow = charge_progress * 0.2
                for i in range(num_leds_ring1):
                    # Faint pulsing in sync with charge
                    pulse = (math.sin(step * 0.1) + 1) / 2
                    intensity = outer_glow * pulse
                    color_index = (step // 10) % len(spell_colors)
                    base_color = spell_colors[color_index]
                    color = tuple(int(c * intensity) for c in base_color)
                    self.pixels[i] = color
                
                self.pixels.show()
                time.sleep(wait)
            
            # Phase 2: Energy transfers from inner to outer ring
            transfer_steps = int(0.3 / wait)  # Quick transfer
            
            for step in range(transfer_steps):
                if self._stop_event.is_set():
                    break
                
                transfer_progress = step / transfer_steps
                
                # Inner ring fades
                for i in range(num_leds_ring2):
                    current_color = self.pixels[num_leds_ring1 + i]
                    fade_factor = 1.0 - transfer_progress
                    new_color = tuple(int(c * fade_factor) for c in current_color)
                    self.pixels[num_leds_ring1 + i] = new_color
                
                # Outer ring brightens with energy waves
                for i in range(num_leds_ring1):
                    # Create wave effect moving outward
                    wave_pos = transfer_progress * 2 * math.pi
                    wave = (math.sin(i / num_leds_ring1 * math.pi * 2 + wave_pos) + 1) / 2
                    intensity = transfer_progress * wave
                    
                    # Mix of colors for energy transfer
                    r = int(255 * intensity)
                    g = int(200 * intensity * 0.8)
                    b = int(255 * intensity)
                    self.pixels[i] = (r, g, b)
                
                self.pixels.show()
                time.sleep(wait)
            
            # Phase 3: Outer ring explosion with inner ring echo
            explosion_steps = int(0.5 / wait)
            explosion_center = random.randint(0, num_leds_ring1 - 1)
            
            for step in range(explosion_steps):
                if self._stop_event.is_set():
                    break
                
                explosion_progress = step / explosion_steps
                
                # Outer ring - main explosion
                for i in range(num_leds_ring1):
                    distance = min(abs(i - explosion_center),
                                 abs(i - explosion_center + num_leds_ring1),
                                 abs(i - explosion_center - num_leds_ring1))
                    norm_distance = distance / (num_leds_ring1 / 2)
                    
                    # Expanding shockwave
                    wave_position = explosion_progress * 2
                    wave_width = 0.4
                    
                    if abs(norm_distance - wave_position) < wave_width:
                        wave_intensity = 1.0 - abs(norm_distance - wave_position) / wave_width
                        wave_intensity *= (1.0 - explosion_progress * 0.7)
                        
                        # Bright explosion colors
                        if explosion_progress < 0.3:
                            # Initial white flash
                            color = tuple(int(255 * wave_intensity) for _ in range(3))
                        else:
                            # Colorful aftermath
                            color_index = int(norm_distance * len(spell_colors)) % len(spell_colors)
                            base_color = spell_colors[color_index]
                            color = tuple(int(c * wave_intensity) for c in base_color)
                        
                        self.pixels[i] = color
                    else:
                        self.pixels[i] = (0, 0, 0)
                
                # Inner ring - echo effect
                echo_delay = 0.2
                if explosion_progress > echo_delay:
                    echo_progress = (explosion_progress - echo_delay) / (1.0 - echo_delay)
                    echo_intensity = (1.0 - echo_progress) * 0.6
                    
                    for i in range(num_leds_ring2):
                        # Radial pulse on inner ring
                        angle = i / num_leds_ring2 * math.pi * 2
                        pulse = (math.sin(echo_progress * math.pi * 3 + angle) + 1) / 2
                        intensity = echo_intensity * pulse
                        
                        color_index = (i + int(echo_progress * 10)) % len(spell_colors)
                        base_color = spell_colors[color_index]
                        color = tuple(int(c * intensity) for c in base_color)
                        self.pixels[num_leds_ring1 + i] = color
                
                self.pixels.show()
                time.sleep(wait)
            
            # Phase 4: Magical sparkles on both rings
            sparkle_duration = random.uniform(1.5, 2.5)
            sparkle_steps = int(sparkle_duration / wait)
            
            # Initialize sparkles for both rings
            sparkles = []
            # More sparkles on outer ring
            for _ in range(random.randint(15, 25)):
                sparkles.append({
                    'ring': 1,
                    'position': random.randint(0, num_leds_ring1 - 1),
                    'lifetime': random.uniform(0.3, 1.2),
                    'age': 0.0,
                    'color': random.choice(spell_colors),
                    'twinkle_speed': random.uniform(5, 15)
                })
            # Fewer sparkles on inner ring
            for _ in range(random.randint(5, 10)):
                sparkles.append({
                    'ring': 2,
                    'position': random.randint(0, num_leds_ring2 - 1),
                    'lifetime': random.uniform(0.5, 1.5),
                    'age': 0.0,
                    'color': random.choice(spell_colors),
                    'twinkle_speed': random.uniform(3, 10)
                })
            
            for step in range(sparkle_steps):
                if self._stop_event.is_set():
                    break
                
                self.pixels.fill((0, 0, 0))
                
                active_sparkles = []
                for sparkle in sparkles:
                    sparkle['age'] += wait
                    
                    if sparkle['age'] < sparkle['lifetime']:
                        age_factor = 1.0 - (sparkle['age'] / sparkle['lifetime'])
                        twinkle = (math.sin(sparkle['age'] * sparkle['twinkle_speed']) + 1) / 2
                        intensity = age_factor * twinkle
                        
                        color = tuple(int(c * intensity) for c in sparkle['color'])
                        
                        if sparkle['ring'] == 1:
                            self.pixels[sparkle['position']] = color
                        else:
                            self.pixels[num_leds_ring1 + sparkle['position']] = color
                        
                        active_sparkles.append(sparkle)
                
                sparkles = active_sparkles
                self.pixels.show()
                time.sleep(wait)
            
            # Clear and pause
            self.pixels.fill((0, 0, 0))
            self.pixels.show()
            time.sleep(random.uniform(0.5, 1.0))

    def _sparkling_pink_blue_effect(self, wait):
        """Override: Pink and blue sparkles on outer ring, with a soft, slow blue/pink pulse on the inner ring."""
        num_leds_ring1 = LEDConfig.LED_COUNT_RING1
        num_leds_ring2 = LEDConfig.LED_COUNT_RING2

        if num_leds_ring1 <= 0 or num_leds_ring2 <= 0:
            logging.warning("Sparkling pink/blue effect requires both rings to have LEDs. Falling back to default.")
            return super()._sparkling_pink_blue_effect(wait)

        # --- Ring 1: Outer Ring Sparkles ---
        pixel_states_ring1 = [{'active': False, 'brightness': 0.0, 'hue': 0.0, 'direction': 1} for _ in range(num_leds_ring1)]
        pink_hue = colorsys.rgb_to_hsv(*[c/255.0 for c in COLORS["pink"]])[0]
        blue_hue = colorsys.rgb_to_hsv(*[c/255.0 for c in COLORS["blue"]])[0]
        palette = [pink_hue, blue_hue]
        
        # --- Ring 2: Inner Ring slow pulse ---
        # Will interpolate between pink and a soft blue
        inner_color1 = COLORS["pink"]
        inner_color2 = (30, 80, 200) # A soft, darker blue to save power
        
        cycle_step = 0
        while not self._stop_event.is_set():
            # --- Update Ring 1 (Outer Ring) - Sparkles ---
            for pixel in pixel_states_ring1:
                if not pixel['active'] and random.random() < 0.03: # Activation chance
                    pixel['active'] = True
                    pixel['brightness'] = 0.0
                    pixel['hue'] = random.choice(palette)
                    pixel['direction'] = 1

            for i, pixel in enumerate(pixel_states_ring1):
                if pixel['active']:
                    pixel['brightness'] += (0.03 + (0.03 * 2 * (1.0 - (pixel['brightness'] ** 2)))) * pixel['direction']

                    if pixel['brightness'] >= 1.0: 
                        pixel['brightness'], pixel['direction'] = 1.0, -1
                    elif pixel['brightness'] <= 0.0 and pixel['direction'] == -1: 
                        pixel['active'], pixel['brightness'] = False, 0.0
                    
                    if pixel['active']:
                        r, g, b = [int(x * 255) for x in colorsys.hsv_to_rgb(pixel['hue'], 0.9, pixel['brightness'])]
                        self.pixels[i] = (r, g, b)
                    else: 
                        self.pixels[i] = (0, 0, 0)
                else: 
                    self.pixels[i] = (0, 0, 0)
                
            # --- Update Ring 2 (Inner Ring) - Slow Pulse ---
            # Use a sine wave to smoothly transition between the two colors.
            pulse_pos = (math.sin(cycle_step * math.pi / 100) + 1) / 2 # Normalized to 0-1
            
            # Linear interpolation between the two colors
            r = int(inner_color1[0] * (1 - pulse_pos) + inner_color2[0] * pulse_pos)
            g = int(inner_color1[1] * (1 - pulse_pos) + inner_color2[1] * pulse_pos)
            b = int(inner_color1[2] * (1 - pulse_pos) + inner_color2[2] * pulse_pos)
            
            for i in range(num_leds_ring2):
                self.pixels[num_leds_ring1 + i] = (r, g, b)

            cycle_step = (cycle_step + 1) % 200
            
            self.pixels.show()
            time.sleep(wait)

    def _rotating_beacon_effect(self, color_name, wait):
        """Override: Rotating beacon on outer ring, with inner ring pulsing based on speed."""
        num_leds_ring1 = LEDConfig.LED_COUNT_RING1
        num_leds_ring2 = LEDConfig.LED_COUNT_RING2

        if num_leds_ring1 <= 0 or num_leds_ring2 <= 0:
            logging.warning("Rotating beacon effect requires both rings. Falling back to default.")
            return super()._rotating_beacon_effect(color_name, wait)

        if color_name not in COLORS:
            logging.error(f"Invalid color name '{color_name}' for rotating_beacon. Defaulting to green.")
            color_name = 'green'
        head_color = COLORS[color_name]
        
        trail_length = 6
        # Create trail colors based on head color
        trail_colors = [tuple(int(c * math.pow(0.6, i)) for c in head_color) for i in range(1, trail_length + 1)]

        position = 0
        cycle_step = 0
        while not self._stop_event.is_set():
            # --- Outer Ring: Beacon ---
            # Clear only the outer ring part of the pixel buffer
            for i in range(num_leds_ring1):
                self.pixels[i] = (0,0,0)

            head_pos = int(position) % num_leds_ring1
            self.pixels[head_pos] = head_color
            for i in range(trail_length):
                trail_pos = (head_pos - 1 - i + num_leds_ring1) % num_leds_ring1
                # Make sure we don't try to access a negative index in trail_colors
                if i < len(trail_colors):
                    self.pixels[trail_pos] = trail_colors[i]
            
            # --- Inner Ring: Pulse ---
            # Pulse speed is related to rotation speed. Faster rotation = faster pulse.
            # self._current_speed is the delay, so smaller is faster.
            # A smaller speed -> larger pulse_rate_factor -> faster pulse
            pulse_rate_factor = 0.1 / self._current_speed if self._current_speed > 0.001 else 100
            pulse_pos = (math.sin(cycle_step * math.pi * pulse_rate_factor / 50) + 1) / 2 # 0 to 1
            brightness = 0.1 + (pulse_pos * 0.5) # Varies from 0.1 to 0.6
            inner_color = tuple(int(c * brightness) for c in head_color)
            
            for i in range(num_leds_ring2):
                self.pixels[num_leds_ring1 + i] = inner_color

            self.pixels.show()
            
            time.sleep(self._current_speed)
            
            position = (position + 1) % num_leds_ring1
            cycle_step += 1

    # ********** Planet Tour Effects (Ring Overrides) **********

    def _warp_drive_effect(self, wait):
        """Override for warp drive. Outer ring has faster streaks, inner ring is a bright core."""
        # Outer ring: white/blue streaks moving rapidly away from a 'front' point.
        # Inner ring: a bright, pulsing white/blue to represent the engine core.
        pass

    def _mercury_effect(self, wait):
        """Override for Mercury. Both rings show a rocky, gray, slow rotation."""
        # Both rings could have a similar gray, rotating pattern, maybe slightly out of sync.
        return super()._mercury_effect(wait)

    def _venus_effect(self, wait):
        """Override for Venus. Outer ring has faster swirling clouds than inner ring."""
        # Both rings show yellowish-white swirling clouds, but the outer ring's
        # pattern could move faster to create a sense of depth in the atmosphere.
        pass

    def _earth_effect(self, wait):
        """Represents Earth. Rotating blue oceans and green/brown continents."""
        # A rotation effect mixing blue (oceans) and green (land).
        # We can reuse the logic from _two_color_rotation_effect.
        self._two_color_rotation_effect("earth_blue", "earth_green", wait)

    def _mars_effect(self, wait):
        """Represents Mars. The 'Red Planet' with a slow rotation and reddish-orange color."""
        # A simple rotation of reddish-orange colors, perhaps with some darker patches for terrain.
        self._two_color_rotation_effect("mars_red", "black", wait)

    def _jupiter_effect(self, wait):
        """Represents Jupiter. Fast-rotating bands of orange, brown, and white clouds, with a Great Red Spot."""
        # This effect should show bands of color rotating. The Great Red Spot could be a persistent
        # cluster of red LEDs that moves with the rotation.
        num_leds = LEDConfig.LED_COUNT
        offset = 0
        great_red_spot_pos = num_leds // 4
        great_red_spot_size = 3

        while not self._stop_event.is_set():
            offset += 1 # Faster rotation
            for i in range(num_leds):
                pos = (i + offset) % num_leds
                
                # Check for Great Red Spot
                is_spot = False
                for s in range(great_red_spot_size):
                    if pos == (great_red_spot_pos + s) % num_leds:
                        is_spot = True
                        break

                if is_spot:
                    self.pixels[i] = COLORS["mars_red"]
                else:
                    # Create bands
                    if (pos // 4) % 3 == 0:
                        self.pixels[i] = COLORS["jupiter_orange"]
                    elif (pos // 4) % 3 == 1:
                        self.pixels[i] = COLORS["jupiter_white"]
                    else:
                        self.pixels[i] = COLORS["brown"]

            self.pixels.show()
            time.sleep(wait)


    def _saturn_effect(self, wait):
        """Represents Saturn. Pale gold planet with its iconic rings."""
        # For a single ring, this is difficult. It will be a static pale gold color
        # with a slightly brighter band to represent the rings.
        num_leds = LEDConfig.LED_COUNT
        planet_color = COLORS["saturn_gold"]
        ring_color = COLORS["white"]
        
        for i in range(num_leds):
            # Make a band of LEDs slightly brighter for the "ring"
            if num_leds // 3 <= i <= num_leds * 2 // 3:
                # Simple blend to make ring color brighter
                r = min(255, planet_color[0] + 40)
                g = min(255, planet_color[1] + 40)
                b = min(255, planet_color[2] + 40)
                self.pixels[i] = (r, g, b)
            else:
                self.pixels[i] = planet_color
        
        self.pixels.show()
        # This is a static effect, but we still need to loop to prevent the thread from exiting.
        while not self._stop_event.is_set():
            time.sleep(0.1)


    def _uranus_effect(self, wait):
        """Represents Uranus. A pale blue, hazy planet, tilted on its side."""
        # A soft, uniform pale blue with a very slow, subtle pulse.
        self.pixels.fill(COLORS["uranus_blue"])
        self.pixels.show()
        # This is a static effect, but we still need to loop to prevent the thread from exiting.
        while not self._stop_event.is_set():
            time.sleep(0.1)


    def _neptune_effect(self, wait):
        """Represents Neptune. A deep blue, windy planet."""
        # A deep blue color with fast-moving, subtle streaks of lighter blue to show high-speed winds.
        num_leds = LEDConfig.LED_COUNT
        base_color = COLORS["neptune_blue"]
        streaks = []

        while not self._stop_event.is_set():
            if random.random() < 0.4: # Chance for new streak
                streaks.append({
                    'pos': random.randint(0, num_leds -1),
                    'len': random.randint(3, 7),
                    'brightness': random.uniform(0.3, 0.7),
                    'life': random.randint(10, 20) # frames to live
                })
            
            self.pixels.fill(base_color)
            
            active_streaks = []
            for streak in streaks:
                streak['life'] -= 1
                if streak['life'] > 0:
                    active_streaks.append(streak)
                    for i in range(streak['len']):
                        pos = (streak['pos'] + i) % num_leds
                        # Fade the streak along its length
                        brightness = streak['brightness'] * (1 - (i / streak['len']))
                        # Blend the streak color with the base color
                        streak_color = (
                            int(base_color[0] + (255 - base_color[0]) * brightness),
                            int(base_color[1] + (255 - base_color[1]) * brightness),
                            int(base_color[2] + (255 - base_color[2]) * brightness)
                        )
                        self.pixels[pos] = streak_color
            
            streaks = active_streaks
            self.pixels.show()
            time.sleep(wait)

class LEDManagerRings(LEDManager):
    """
// ... existing code ...
            self.pixels.show()
            time.sleep(wait)

    def _earth_effect(self, wait):
        """Override for Earth. Rotating blue and green on both rings, slightly offset."""
        # Both rings show a rotation of blue and green, this just calls the two_color_rotation_effect
        # from the parent class, which is perfect for this.
        self._two_color_rotation_effect("earth_blue", "earth_green", wait)

    def _mars_effect(self, wait):
        """Override for Mars. Both rings show a slow, reddish-orange rotation."""
        # Similar to Mercury, both rings can show the same effect, maybe with the inner
        # ring being slightly darker.
        return super()._mars_effect(wait)

    def _jupiter_effect(self, wait):
        """Override for Jupiter. Rings show counter-rotating bands of color."""
        # This can be very effective with two rings. Each ring can represent different
        # cloud bands rotating at different speeds or in opposite directions.
        # The Great Red Spot could be on the outer ring.
        num_leds_ring1 = LEDConfig.LED_COUNT_RING1
        num_leds_ring2 = LEDConfig.LED_COUNT_RING2
        offset1 = 0
        offset2 = 0
        great_red_spot_pos = num_leds_ring1 // 4
        great_red_spot_size = 3

        while not self._stop_event.is_set():
            offset1 += 2 # Outer ring rotates faster
            offset2 -= 1 # Inner ring rotates slower and counter

            # Outer Ring
            for i in range(num_leds_ring1):
                pos = (i + offset1) % num_leds_ring1
                is_spot = great_red_spot_pos <= pos < great_red_spot_pos + great_red_spot_size
                if is_spot:
                    self.pixels[i] = COLORS["mars_red"]
                else: # Bands
                    if (pos // 4) % 2 == 0: self.pixels[i] = COLORS["jupiter_orange"]
                    else: self.pixels[i] = COLORS["jupiter_white"]
            
            # Inner Ring
            for i in range(num_leds_ring2):
                pos = (i + offset2) % num_leds_ring2
                if (pos // 3) % 2 == 0: self.pixels[num_leds_ring1 + i] = COLORS["brown"]
                else: self.pixels[num_leds_ring1 + i] = COLORS["jupiter_orange"]

            self.pixels.show()
            time.sleep(wait)

    def _saturn_effect(self, wait):
        """Override for Saturn. Inner ring is the planet (pale gold), outer ring is the rings (white/gray)."""
        # This is where the dual rings shine.
        # Inner ring: a slow rotating pale gold.
        # Outer ring: a faster rotating band of white, gray, and light brown to simulate the rings.
        num_leds_ring1 = LEDConfig.LED_COUNT_RING1
        num_leds_ring2 = LEDConfig.LED_COUNT_RING2
        
        offset = 0
        while not self._stop_event.is_set():
            offset += 1
            # Inner ring (planet) - solid gold color
            for i in range(num_leds_ring2):
                self.pixels[num_leds_ring1 + i] = COLORS["saturn_gold"]
                
            # Outer ring (rings) - rotating bands of whites and grays
            for i in range(num_leds_ring1):
                pos = (i + offset) % num_leds_ring1
                if (pos // 3) % 3 == 0:
                    self.pixels[i] = COLORS["white"]
                elif (pos // 3) % 3 == 1:
                    self.pixels[i] = COLORS["gray"]
                else:
                    self.pixels[i] = COLORS["brown"]
            
            self.pixels.show()
            time.sleep(wait)

    def _uranus_effect(self, wait):
        """Override for Uranus. Soft, hazy blue on both rings with a subtle shimmer."""
        # Both rings display a uniform pale blue, maybe with a very slow, subtle counter-pulse
        # or shimmer effect to give a sense of a cold, gaseous planet.
        num_leds_ring1 = LEDConfig.LED_COUNT_RING1
        num_leds_ring2 = LEDConfig.LED_COUNT_RING2
        
        offset = 0
        while not self._stop_event.is_set():
            offset += 0.1
            # Both rings are pale blue, with a slow shimmer
            brightness = (math.sin(offset) + 1) / 2 * 0.2 + 0.8 # Varies between 0.8 and 1.0
            color = tuple(int(c * brightness) for c in COLORS["uranus_blue"])
            
            self.pixels.fill(color) # Fill all pixels
            self.pixels.show()
            time.sleep(wait)

    def _neptune_effect(self, wait):
        """Override for Neptune. Deep blue on both rings with fast, counter-moving wind streaks."""
        # Both rings are deep blue. The outer ring can have light blue streaks moving quickly
        # in one direction, while the inner ring has them moving in the opposite direction.
        num_leds_ring1 = LEDConfig.LED_COUNT_RING1
        num_leds_ring2 = LEDConfig.LED_COUNT_RING2
        base_color = COLORS["neptune_blue"]
        streaks1 = [] # Outer ring
        streaks2 = [] # Inner ring

        while not self._stop_event.is_set():
            # Create new streaks
            if random.random() < 0.5: streaks1.append({'pos': 0, 'life': num_leds_ring1})
            if random.random() < 0.3: streaks2.append({'pos': num_leds_ring2 - 1, 'life': num_leds_ring2})
            
            self.pixels.fill(base_color)

            # Animate streaks on outer ring (forward)
            active_streaks1 = []
            for s in streaks1:
                s['pos'] += 2 # Move fast
                s['life'] -= 2
                if s['life'] > 0:
                    active_streaks1.append(s)
                    if s['pos'] < num_leds_ring1: self.pixels[s['pos']] = COLORS["white"]
            streaks1 = active_streaks1

            # Animate streaks on inner ring (backward)
            active_streaks2 = []
            for s in streaks2:
                s['pos'] -= 1 # Move slower
                s['life'] -= 1
                if s['life'] > 0:
                    active_streaks2.append(s)
                    if s['pos'] >= 0: self.pixels[num_leds_ring1 + s['pos']] = COLORS["white"]
            streaks2 = active_streaks2

            self.pixels.show()
            time.sleep(wait)