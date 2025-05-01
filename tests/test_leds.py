import time
import sys
import os

# Add the project root to the Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)

# Attempt to import necessary components
try:
    from src.config import LEDConfig
    # Check availability directly based on library imports
    import board
    import neopixel
    LEDS_AVAILABLE = True
    print("LED libraries (board, neopixel) imported successfully.")
except (ImportError, NotImplementedError):
    LEDS_AVAILABLE = False
    print("Warning: LED libraries (board, neopixel) not available. Direct test cannot run.")
    # Define dummy config if needed for script structure, though not used if unavailable
    class LEDConfig:
        LED_PIN = 21
        LED_COUNT = 24
        LED_BRIGHTNESS = 1.0
        LED_ORDER = "GRB"

if __name__ == "__main__":
    print("Starting direct LED hardware test...")

    if LEDS_AVAILABLE:
        pixels_direct = None # Initialize to None
        try:
            print("Initializing neopixel directly...")
            pin = getattr(board, f'D{LEDConfig.LED_PIN}')
            pixels_direct = neopixel.NeoPixel(
                pin,
                LEDConfig.LED_COUNT,
                brightness=LEDConfig.LED_BRIGHTNESS,
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

            print("Directly cycling through rainbow colors...")
            # Simple rainbow cycle example
            for j in range(256):
                for i in range(LEDConfig.LED_COUNT):
                    pixel_index = (i * 256 // LEDConfig.LED_COUNT) + j
                    hue = pixel_index & 255
                    # Simple wheel function (replace with colorsys if preferred)
                    if hue < 85:
                        color = (hue * 3, 255 - hue * 3, 0)
                    elif hue < 170:
                        hue -= 85
                        color = (255 - hue * 3, 0, hue * 3)
                    else:
                        hue -= 170
                        color = (0, hue * 3, 255 - hue * 3)
                    pixels_direct[i] = color
                pixels_direct.show()
                time.sleep(0.01) # Adjust speed as needed

            print("Direct Neopixel test complete.")

        except Exception as direct_e:
            print(f"An error occurred during the direct LED test: {direct_e}")
        finally:
            # Ensure LEDs are turned off at the end
            if pixels_direct is not None:
                print("Cleaning up: Turning off LEDs.")
                try:
                    pixels_direct.fill((0, 0, 0))
                    pixels_direct.show()
                    # Release the neopixel object if possible (good practice)
                    if hasattr(pixels_direct, 'deinit'):
                         pixels_direct.deinit()
                except Exception as cleanup_e:
                    print(f"Error during cleanup: {cleanup_e}")
            else:
                print("Skipping cleanup as pixels were not initialized.")
    else:
        print("Skipping direct Neopixel test (board/neopixel libraries not available).")
        
    print("\nDirect LED test script finished.") 