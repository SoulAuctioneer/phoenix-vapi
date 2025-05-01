import time
import sys
import os

# Add the project root to the Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)

from src.managers.led_manager import LEDManager, LEDEffect, COLORS, LEDS_AVAILABLE
from src.config import LEDConfig # Import LEDConfig

# Conditionally import board and neopixel for direct testing
if LEDS_AVAILABLE:
    try:
        import board
        import neopixel
    except (ImportError, NotImplementedError):
        # This case should theoretically not happen if LEDS_AVAILABLE is True,
        # but handle it defensively.
        LEDS_AVAILABLE = False 
        print("Warning: LEDS_AVAILABLE was True, but failed to import board/neopixel.")


def run_led_test(led_manager):
    """Runs a sequence of tests to verify LED functionality."""
    print("Starting LED test sequence...")

    try:
        # Test 1: Solid Colors
        print("Testing solid colors...")
        for color_name, color_rgb in COLORS.items():
            if color_name == "black": continue # Skip black
            print(f"Showing {color_name}...")
            led_manager.show_color(color_rgb)
            time.sleep(1)

        # Test 2: Clear LEDs
        print("Clearing LEDs...")
        led_manager.clear()
        time.sleep(1)

        # Test 3: Breathing Effect
        print("Testing Blue Breathing effect...")
        led_manager.start_effect(LEDEffect.BLUE_BREATHING)
        time.sleep(5)
        led_manager.stop_effect()
        print("Breathing effect stopped.")
        time.sleep(1)

        # Test 4: Rotating Rainbow Effect
        print("Testing Rotating Rainbow effect...")
        led_manager.start_effect(LEDEffect.ROTATING_RAINBOW, speed=0.01)
        time.sleep(5)
        led_manager.stop_effect()
        print("Rainbow effect stopped.")
        time.sleep(1)
        
        # Test 5: Show a specific color (e.g., Pink) using show_color
        print("Showing Pink again using show_color...")
        led_manager.show_color(COLORS["pink"])
        time.sleep(2)
        led_manager.clear() # Clear after manager tests before direct test
        time.sleep(1)

        # Test 6: Direct Neopixel Interaction (if available)
        print("\nTesting direct Neopixel control (if available)...")
        if LEDS_AVAILABLE:
            try:
                print("Initializing neopixel directly...")
                pin = getattr(board, f'D{LEDConfig.LED_PIN}')
                pixels_direct = neopixel.NeoPixel(
                    pin,
                    LEDConfig.LED_COUNT,
                    brightness=LEDConfig.LED_BRIGHTNESS, # Use configured brightness
                    auto_write=False,
                    pixel_order=LEDConfig.LED_ORDER
                )
                
                print("Directly setting first pixel RED...")
                pixels_direct[0] = (255, 0, 0)
                pixels_direct.show()
                time.sleep(2)

                print("Directly filling all pixels GREEN...")
                pixels_direct.fill((0, 255, 0))
                pixels_direct.show()
                time.sleep(2)

                print("Directly clearing pixels...")
                pixels_direct.fill((0, 0, 0))
                pixels_direct.show()
                time.sleep(1)
                
                # Release the neopixel object if possible (good practice)
                if hasattr(pixels_direct, 'deinit'):
                     pixels_direct.deinit()
                print("Direct Neopixel test complete.")

            except Exception as direct_e:
                print(f"Error during direct Neopixel test: {direct_e}")
        else:
            print("Skipping direct Neopixel test (board/neopixel libraries not available).")
            
        print("\nLED test sequence complete.")

    except Exception as e:
        print(f"An error occurred during the LED test: {e}")
    finally:
        # Ensure LEDs are turned off at the end
        print("Cleaning up: Turning off LEDs.")
        led_manager.clear()

if __name__ == "__main__":
    print("Initializing LED Manager...")
    # Ensure configuration is loaded (adjust path if necessary)
    try:
        # Assuming config is implicitly loaded by LEDManager or other imports
        # If not, you might need to explicitly load config here
        pass
    except ImportError:
        print("Warning: Could not import or load config. Using default LED settings.")

    led_manager = LEDManager()
    run_led_test(led_manager)
    print("Test script finished.") 