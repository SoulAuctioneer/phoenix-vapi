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

    def _start_effect(self, effect_func, speed):
        """Helper method to start an effect"""
        if self._effect_thread is not None:
            self.stop_effect()
        self._stop_event.clear()
        self._effect_thread = Thread(target=effect_func, args=(speed,))
        self._effect_thread.daemon = True
        self._effect_thread.start()

    def start_effect(self, effect_str, speed=0.05):
        """Start an effect based on the effect string"""
        if effect_str == "blue_breathing":
            self._start_effect(self._blue_breathing_effect, speed)
        elif effect_str == "green_breathing":
            self._start_effect(self._green_breathing_effect, speed)
        elif effect_str == "rotating_rainbow":
            self._start_effect(self._rotating_rainbow_effect, speed)
        elif effect_str == "pink_blue_cycle":
            self._start_effect(self._pink_blue_rotation_effect, speed)
        elif effect_str == "random_twinkle":
            self._start_effect(self._random_twinkling_effect, speed)

    def start_idle_pattern(self, speed=0.05):
        """Start the breathing effect"""
        self._start_effect(self._pink_blue_rotation_effect, speed)

    def start_listening_pattern(self, speed=0.02):
        """Start the rainbow effect"""
        self._start_effect(self._rotating_rainbow_effect, speed)

    def start_conversation_pattern(self, speed=0.03):
        """Start the conversation effect"""
        self._start_effect(self._random_twinkling_effect, speed)

    def start_pink_blue_rotation(self, speed=0.05):
        """Start the pink to blue rotation effect"""
        self._start_effect(self._pink_blue_rotation_effect, speed)

    def start_random_twinkling(self, speed=0.02):
        """Start the random twinkling effect"""
        self._start_effect(self._random_twinkling_effect, speed)

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
        led.start_idle_pattern()
        time.sleep(5)
        print("2. Listening pattern")
        led.start_listening_pattern()
        time.sleep(5)
        print("3. Conversation pattern")
        led.start_conversation_pattern()
        time.sleep(5)
        led.stop_effect()
    except KeyboardInterrupt:
        print("\nStopping effects...")
        led.stop_effect() 