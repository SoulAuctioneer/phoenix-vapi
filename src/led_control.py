import time
import colorsys
import math
from threading import Thread, Event
from config import LED_PIN, LED_COUNT, LED_BRIGHTNESS, LED_ORDER, PLATFORM
import logging

class LEDController:

    # Only import board and neopixel on Raspberry Pi
    if PLATFORM == "raspberry-pi":
        import board
        import neopixel
        logging.info("Initializing LED controller for Raspberry Pi")
    else:
        logging.info("Initializing LED controller in simulation mode")

    def __init__(self):
        self._effect_thread = None
        self._stop_event = Event()
        
        # Initialize the NeoPixel object only on Raspberry Pi
        if PLATFORM == "raspberry-pi":
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

    def _breathing_effect(self, wait):
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

    def _rainbow_cycle(self, wait):
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

    def _active_conversation_effect(self, wait):
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

    def _start_effect(self, effect_func, speed):
        """Helper method to start an effect"""
        if self._effect_thread is not None:
            self.stop_effect()
        self._stop_event.clear()
        self._effect_thread = Thread(target=effect_func, args=(speed,))
        self._effect_thread.daemon = True
        self._effect_thread.start()

    def start_breathing(self, speed=0.05):
        """Start the breathing effect"""
        self._start_effect(self._breathing_effect, speed)

    def start_rainbow(self, speed=0.02):
        """Start the rainbow effect"""
        self._start_effect(self._rainbow_cycle, speed)

    def start_conversation(self, speed=0.03):
        """Start the conversation effect"""
        self._start_effect(self._active_conversation_effect, speed)

    def stop_effect(self):
        """Stop any running effect"""
        self._stop_event.set()
        if self._effect_thread:
            self._effect_thread.join()
            self._effect_thread = None
        self.clear()

# Example usage:
if __name__ == "__main__":
    led = LEDController()
    try:
        print("Testing LED effects...")
        print("1. Breathing effect")
        led.start_breathing()
        time.sleep(5)
        print("2. Rainbow effect")
        led.start_rainbow()
        time.sleep(5)
        print("3. Conversation effect")
        led.start_conversation()
        time.sleep(5)
        led.stop_effect()
    except KeyboardInterrupt:
        print("\nStopping effects...")
        led.stop_effect() 