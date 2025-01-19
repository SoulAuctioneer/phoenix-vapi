from vapi_python import Vapi
import RPi.GPIO as GPIO
import time
from config import VAPI_API_KEY, ASSISTANT_CONFIG

class KidsCompanion:
    def __init__(self):
        self.vapi = Vapi(api_key=VAPI_API_KEY)
        self.setup_gpio()
        self.is_active = False

    def setup_gpio(self):
        GPIO.setmode(GPIO.BCM)
        # Setup for a button on GPIO 18
        GPIO.setup(18, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        # Setup for an LED on GPIO 24
        GPIO.setup(24, GPIO.OUT)
        self.led = GPIO.PWM(24, 100)
        self.led.start(0)

    def start_interaction(self):
        """Start an interaction session with the AI companion"""
        if not self.is_active:
            self.is_active = True
            self.led.ChangeDutyCycle(100)  # Turn on LED
            try:
                self.vapi.start(assistant=ASSISTANT_CONFIG)
            except Exception as e:
                print(f"Error starting companion: {e}")
                self.stop_interaction()

    def stop_interaction(self):
        """Stop the current interaction session"""
        if self.is_active:
            self.is_active = False
            self.led.ChangeDutyCycle(0)  # Turn off LED
            try:
                self.vapi.stop()
            except Exception as e:
                print(f"Error stopping companion: {e}")

    def cleanup(self):
        """Clean up GPIO resources"""
        self.led.stop()
        GPIO.cleanup() 