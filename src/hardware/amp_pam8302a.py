"""
Low-level driver for the PAM8302A Class-D audio amplifier.

This module provides a simple interface to enable and disable the amplifier
by controlling its shutdown (SD) pin. The PAM8302A is enabled by default
due to an internal pull-up resistor. To disable it and save power, the SD
pin must be pulled to ground.
"""

import platform

# Mock GPIO for non-Raspberry Pi platforms
IS_RASPBERRY_PI = (platform.system().lower() == "linux" and 
                   ("arm" in platform.machine().lower() or 
                    "aarch" in platform.machine().lower()))

if IS_RASPBERRY_PI:
    import RPi.GPIO as GPIO
else:
    # Mock GPIO library for development on non-Pi platforms
    class MockGPIO:
        BCM = "BCM"
        OUT = "OUT"
        HIGH = 1
        LOW = 0

        def setmode(self, mode):
            print(f"MockGPIO: setmode({mode})")

        def setup(self, pin, mode, initial=LOW):
            print(f"MockGPIO: setup({pin}, {mode}, initial={initial})")

        def output(self, pin, state):
            state_str = "HIGH" if state == self.HIGH else "LOW"
            print(f"MockGPIO: output({pin}, {state_str})")

        def cleanup(self, pin=None):
            if pin:
                print(f"MockGPIO: cleanup({pin})")
            else:
                print("MockGPIO: cleanup()")

    GPIO = MockGPIO()


class Amplifier:
    """A simple driver for the PAM8302A amplifier."""

    def __init__(self, shutdown_pin: int, initial_state: str = 'on'):
        """
        Initializes the amplifier driver.

        Args:
            shutdown_pin (int): The BCM GPIO pin number connected to the amplifier's SD pin.
            initial_state (str): The initial state of the amplifier ('on' or 'off').
                                 Defaults to 'on'.
        """
        self.shutdown_pin = shutdown_pin
        self.is_enabled = False

        GPIO.setmode(GPIO.BCM)
        
        initial_level = GPIO.HIGH if initial_state == 'on' else GPIO.LOW
        GPIO.setup(self.shutdown_pin, GPIO.OUT, initial=initial_level)

        self.is_enabled = (initial_state == 'on')
        print(f"Amplifier initialized on pin {shutdown_pin}, initial state: {'enabled' if self.is_enabled else 'disabled'}")

    def enable(self):
        """Enables the amplifier."""
        if not self.is_enabled:
            GPIO.output(self.shutdown_pin, GPIO.LOW) # Swapping just to test
            self.is_enabled = True
            print("Amplifier enabled.")

    def disable(self):
        """Disables the amplifier to save power."""
        if self.is_enabled:
            GPIO.output(self.shutdown_pin, GPIO.HIGH) # Swapping just to test
            self.is_enabled = False
            print("Amplifier disabled.")

    def cleanup(self):
        """Cleans up GPIO resources."""
        print(f"Cleaning up amplifier GPIO on pin {self.shutdown_pin}.")
        GPIO.cleanup(self.shutdown_pin)

    def __del__(self):
        """Ensures GPIO cleanup when the object is deleted."""
        self.cleanup()


if __name__ == '__main__':
    import time
    # This is an example of how to use the driver.
    # A real application would get the pin from a config file.
    AMP_SHUTDOWN_PIN = 22 
    
    print(f"Initializing amplifier on GPIO pin {AMP_SHUTDOWN_PIN}")
    amp = Amplifier(shutdown_pin=AMP_SHUTDOWN_PIN, initial_state='off')

    try:
        while True:
            print("Enabling amp for 5 seconds...")
            amp.enable()
            time.sleep(5)

            print("Disabling amp for 5 seconds...")
            amp.disable()
            time.sleep(5)

    except KeyboardInterrupt:
        print("\nExiting.")
    finally:
        amp.cleanup() 