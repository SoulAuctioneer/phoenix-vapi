import time
import colorsys
import math
from threading import Thread, Event
from config import LED_PIN, LED_COUNT, LED_BRIGHTNESS, LED_ORDER, PLATFORM
import logging
import random
from enum import Enum, auto

# Try to import board and neopixel, but don't fail if they're not available, e.g. not on Raspberry Pi
try:
    import board
    import neopixel
    LEDS_AVAILABLE = True
    logging.info("LED libraries available. Will use LEDs")
except (ImportError, NotImplementedError):
    LEDS_AVAILABLE = False
    logging.info("LED libraries not available. Won't use LEDs")

class LEDEffect(Enum):
    """Enumeration of available LED effects"""
    BLUE_BREATHING = auto()
    GREEN_BREATHING = auto()
    ROTATING_PINK_BLUE = auto()
    ROTATING_RAINBOW = auto()
    RANDOM_TWINKLING = auto()
    RAIN = auto()
    LIGHTNING = auto()
    PURRING = auto()
    ROTATING_COLOR = auto()

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
}

class LEDManager:
    # Map of effects to their corresponding private methods and default speeds
    _EFFECT_MAP = {
        LEDEffect.BLUE_BREATHING: {'method': '_blue_breathing_effect', 'default_speed': 0.05},
        LEDEffect.GREEN_BREATHING: {'method': '_green_breathing_effect', 'default_speed': 0.05},
        LEDEffect.ROTATING_PINK_BLUE: {'method': '_pink_blue_rotation_effect', 'default_speed': 0.05},
        LEDEffect.ROTATING_RAINBOW: {'method': '_rotating_rainbow_effect', 'default_speed': 0.02},
        LEDEffect.RANDOM_TWINKLING: {'method': '_random_twinkling_effect', 'default_speed': 0.03},
        LEDEffect.RAIN: {'method': '_rain_effect', 'default_speed': 0.05},
        LEDEffect.LIGHTNING: {'method': '_lightning_effect', 'default_speed': 0.05},
        LEDEffect.PURRING: {'method': '_purring_effect', 'default_speed': 0.01},
        LEDEffect.ROTATING_COLOR: {'method': '_rotating_color_effect', 'default_speed': 0.05},
    }

    def __init__(self):
        self._effect_thread = None
        self._stop_event = Event()
        self._current_speed = None
        # Track current effect state
        self._current_effect = None
        self._current_brightness = LED_BRIGHTNESS
        
        # Initialize the NeoPixel object only on Raspberry Pi
        if LEDS_AVAILABLE:
            # Get the correct board pin based on LED_PIN configuration
            pin = getattr(board, f'D{LED_PIN}') if hasattr(board, f'D{LED_PIN}') else LED_PIN
            self.pixels = neopixel.NeoPixel(
                pin,
                LED_COUNT,
                brightness=LED_BRIGHTNESS,
                auto_write=False,
                pixel_order=LED_ORDER
            )
            logging.info(f"NeoPixel initialized on pin {LED_PIN} with {LED_COUNT} LEDs")
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

            self.pixels = MockPixels(LED_COUNT)
            logging.info(f"Mock NeoPixel initialized with {LED_COUNT} LEDs")
        
        self.clear()

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
                self.start_effect(
                    previous_effect['effect'],
                    previous_effect['speed'],
                    previous_effect['brightness']
                )
                
        revert_thread = Thread(target=revert_after_duration)
        revert_thread.daemon = True
        revert_thread.start()

    def start_or_update_effect(self, effect: LEDEffect, speed=None, brightness=LED_BRIGHTNESS, duration=None):
        """Start an LED effect if it's not already running, or update its parameters if it is.
        
        This function allows for smooth transitions in effect parameters without restarting the effect
        pattern from the beginning. If the requested effect is already running, it will only update
        the speed and brightness. If it's a different effect, it will start the new effect.
        
        Args:
            effect: The LEDEffect to start or update
            speed: Speed of the effect (if None, uses effect's default speed)
            brightness: Brightness level from 0.0 to 1.0 (default: LED_BRIGHTNESS from config)
            duration: Optional duration in milliseconds before reverting to previous effect
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
                'brightness': self._current_brightness
            }

        # If the same effect is already running, just update parameters
        if effect == self._current_effect and self._effect_thread and self._effect_thread.is_alive():
            self._current_speed = effect_speed
            self._current_brightness = brightness
            self.pixels.brightness = brightness
            logging.info(f"Updated {effect.name} parameters: speed={effect_speed}, brightness={brightness}")
            
            # Handle duration-based revert for parameter updates
            if duration is not None:
                self._setup_revert_thread(previous_effect, duration)
        else:
            # Different effect or no effect running, start new effect
            self.start_effect(effect, speed, brightness, duration)

    def start_effect(self, effect: LEDEffect, speed=None, brightness=LED_BRIGHTNESS, duration=None):
        """Start an LED effect
        
        Args:
            effect: The LEDEffect to start
            speed: Speed of the effect (if None, uses effect's default speed)
            brightness: Brightness level from 0.0 to 1.0 (default: LED_BRIGHTNESS from config)
            duration: Optional duration in milliseconds before reverting to previous effect
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
                'brightness': self._current_brightness
            }
            self.stop_effect()
            
        self._stop_event.clear()
        self._current_speed = effect_speed
        self._current_effect = effect
        self._current_brightness = brightness
        self.pixels.brightness = brightness
        self._effect_thread = Thread(target=effect_method, args=(effect_speed,))
        self._effect_thread.daemon = True
        self._effect_thread.start()
        
        if duration is not None:
            self._setup_revert_thread(previous_effect, duration)

    def show_color(self, color):
        """Show a specific color on the LEDs"""
        self.pixels.fill(color)
        self.pixels.show()

    def clear(self):
        """Turn off all LEDs"""
        self.pixels.fill((0, 0, 0))
        self.pixels.show()

    def stop_effect(self):
        """Stop any running effect"""
        self._stop_event.set()
        if self._effect_thread:
            self._effect_thread.join()
            self._effect_thread = None
        self._current_effect = None
        self._current_speed = None
        self.clear()


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

    def _rotating_rainbow_effect(self, wait):
        """Generate rainbow colors across all pixels"""
        while not self._stop_event.is_set():
            for j in range(255):
                if self._stop_event.is_set():
                    break
                for i in range(LED_COUNT):
                    hue = (i / LED_COUNT) + (j / 255.0)
                    hue = hue % 1.0
                    r, g, b = [int(x * 255) for x in colorsys.hsv_to_rgb(hue, 1.0, 1.0)]
                    self.pixels[i] = (r, g, b)
                self.pixels.show()
                time.sleep(wait)

    def _pink_blue_rotation_effect(self, wait):
        """Generate a slow rotating gradient between pink and blue colors"""
        # Pink and blue hues in HSV (pink ≈ 0.85, blue ≈ 0.6)
        pink_hue = 0.85
        blue_hue = 0.6
        while not self._stop_event.is_set():
            for j in range(100):  # Slower cycle with 100 steps
                if self._stop_event.is_set():
                    break
                # Create a moving gradient across all pixels
                for i in range(LED_COUNT):
                    # Calculate position in the gradient cycle
                    position = (i / LED_COUNT + j / 100.0) % 1.0
                    # Interpolate between pink and blue
                    if position < 0.5:
                        # Transition from pink to blue
                        hue = pink_hue + (blue_hue - pink_hue) * (position * 2)
                    else:
                        # Transition from blue back to pink
                        hue = blue_hue + (pink_hue - blue_hue) * ((position - 0.5) * 2)
                    # Use high saturation and medium value for vibrant but not too bright colors
                    r, g, b = [int(x * 255) for x in colorsys.hsv_to_rgb(hue, 0.8, 0.7)]
                    self.pixels[i] = (r, g, b)
                self.pixels.show()
                time.sleep(wait)

    def _random_twinkling_effect(self, wait):
        """Create random twinkling pixels with dynamic fade speeds"""
        # Track the state of each pixel
        pixel_states = []
        for _ in range(LED_COUNT):
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
                    led_position = int(drop['position'] * LED_COUNT) % LED_COUNT
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
                            trail_pos_cw = (led_position + i) % LED_COUNT
                            trail_pos_ccw = (led_position - i) % LED_COUNT
                            
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
            start_led = random.randint(0, LED_COUNT - 1)
            
            # Main lightning strike
            for intensity in [1.0, 0.8]:  # Two quick flashes
                # Clear all pixels first
                self.pixels.fill((0, 0, 0))
                
                # Calculate arc length (between 1/3 and 2/3 of the ring)
                arc_length = random.randint(LED_COUNT // 3, (LED_COUNT * 2) // 3)
                
                # Create the main lightning arc
                for i in range(arc_length):
                    if self._stop_event.is_set():
                        return
                        
                    current_pos = (start_led + (i if clockwise else -i)) % LED_COUNT
                    
                    # Add some randomness to the arc path
                    if random.random() < 0.3:  # 30% chance to create a branch
                        branch_length = random.randint(2, 5)
                        branch_direction = random.choice([1, -1])
                        for j in range(branch_length):
                            branch_pos = (current_pos + (j * branch_direction)) % LED_COUNT
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
                    current_pos = (start_led + (i if clockwise else -i)) % LED_COUNT
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
                brightness = self._current_brightness  # Use the current brightness level
                r = int(r * rgb_base_color[0] * brightness)
                g = int(g * rgb_base_color[1] * brightness)
                b = int(b * rgb_base_color[2] * brightness)

                self.pixels[i] = (r, g, b)
            
            self.pixels.show()
            time.sleep(wait)