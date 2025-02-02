import time
import colorsys
import math
from threading import Thread, Event
from config import LED_PIN, LED_COUNT, LED_BRIGHTNESS, LED_ORDER, PLATFORM
import logging
import random

# Try to import board and neopixel, but don't fail if they're not available, e.g. not on Raspberry Pi
try:
    import board
    import neopixel
    LEDS_AVAILABLE = True
    logging.info("LED libraries available. Will use LEDs")
except (ImportError, NotImplementedError):
    LEDS_AVAILABLE = False
    logging.info("LED libraries not available. Won't use LEDs")

class LEDManager:
    def __init__(self):
        self._effect_thread = None
        self._stop_event = Event()
        
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

                def fill(self, color):
                    self._pixels = [color] * self.n
                    #logging.info(f"Mock: All LEDs set to color {color}")

                def show(self):
                    #logging.info("Mock: LED state updated")
                    pass

            self.pixels = MockPixels(LED_COUNT)
            logging.info(f"Mock NeoPixel initialized with {LED_COUNT} LEDs")
        
        self.clear()

    def clear(self):
        """Turn off all LEDs"""
        self.pixels.fill((0, 0, 0))
        self.pixels.show()

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
                    
                    # Create a blue-white color for the raindrop
                    blue = int(255 * intensity)
                    white = int(100 * intensity)
                    color = (white, white, blue)
                    
                    # Draw main drop pixel
                    self.pixels[led_position] = color
                    
                    # Draw fade trail on neighboring pixels
                    trail_length = 2
                    for i in range(1, trail_length + 1):
                        # Calculate trail positions (both clockwise and counter-clockwise)
                        trail_pos_cw = (led_position + i) % LED_COUNT
                        trail_pos_ccw = (led_position - i) % LED_COUNT
                        
                        # Calculate trail intensity
                        trail_intensity = intensity * (1 - (i / (trail_length + 1))) * 0.7
                        trail_blue = int(255 * trail_intensity)
                        trail_white = int(100 * trail_intensity)
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

    def _blend_colors(self, color1, color2):
        """Blend two colors by taking the maximum of each component"""
        return (
            max(color1[0], color2[0]),
            max(color1[1], color2[1]),
            max(color1[2], color2[2])
        )

    def _start_effect(self, effect_func, speed):
        """Helper method to start an effect"""
        if self._effect_thread is not None:
            self.stop_effect()
        self._stop_event.clear()
        self._effect_thread = Thread(target=effect_func, args=(speed,))
        self._effect_thread.daemon = True
        self._effect_thread.start()

    def start_blue_breathing_effect(self, speed=0.05):
        """Start the blue breathing effect"""
        self._start_effect(self._blue_breathing_effect, speed)

    def start_green_breathing_effect(self, speed=0.05):
        """Start the green breathing effect"""
        self._start_effect(self._green_breathing_effect, speed)

    def start_rotating_pink_blue_effect(self, speed=0.05):
        """Start the breathing effect"""
        self._start_effect(self._pink_blue_rotation_effect, speed)

    def start_rotating_rainbow_effect(self, speed=0.02):
        """Start the rainbow effect"""
        self._start_effect(self._rotating_rainbow_effect, speed)

    def start_random_twinkling_effect(self, speed=0.03):
        """Start the conversation effect"""
        self._start_effect(self._random_twinkling_effect, speed)

    def start_rain_effect(self, speed=0.05):
        """Start the rain effect"""
        self._start_effect(self._rain_effect, speed)

    def _lightning_effect(self, wait):
        """Create a dramatic lightning flash effect with afterglow"""
        while not self._stop_event.is_set():
            # Initial bright white flash
            self.pixels.fill((255, 255, 255))
            self.pixels.show()
            time.sleep(0.05)  # Short bright flash
            
            # First afterglow - bluish white
            self.pixels.fill((100, 100, 150))
            self.pixels.show()
            time.sleep(0.05)
            
            # Second afterglow - dimmer blue
            self.pixels.fill((50, 50, 100))
            self.pixels.show()
            time.sleep(0.1)
            
            # Final dim glow
            self.pixels.fill((20, 20, 40))
            self.pixels.show()
            
            # Dark period
            self.pixels.fill((0, 0, 0))
            self.pixels.show()
            
            # Random wait between lightning flashes
            time.sleep(random.uniform(0.5, 3.0))

    def start_lightning_effect(self, speed=0.05):
        """Start the lightning effect"""
        self._start_effect(self._lightning_effect, speed)

    def stop_effect(self):
        """Stop any running effect"""
        self._stop_event.set()
        if self._effect_thread:
            self._effect_thread.join()
            self._effect_thread = None
        self.clear()

# Example usage:
if __name__ == "__main__":
    led = LEDManager()
    try:
        print("Testing LED effects...")
        print("1. Idle pattern")
        led.start_rotating_pink_blue_effect()
        time.sleep(5)
        print("2. Listening pattern")
        led.start_rotating_rainbow_effect()
        time.sleep(5)
        print("3. Conversation pattern")
        led.start_random_twinkling_effect()
        time.sleep(5)
        led.stop_effect()
    except KeyboardInterrupt:
        print("\nStopping effects...")
        led.stop_effect() 