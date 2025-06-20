"""Service for managing the sleep activity state."""

import logging
from typing import Dict, Any
from services.service import BaseService
from config import SoundEffect, PLATFORM

if PLATFORM == "raspberry-pi":
    from utils import system as system_utils

class SleepActivity(BaseService):
    """Service that manages the sleep activity state
    
    When active, this service:
    1. Plays the breathing sound effect on loop
    2. Sets the LED effect to rotating pink/blue
    """
    
    def __init__(self, service_manager):
        super().__init__(service_manager)
        self._is_active = False
        self._breathing_volume = 0.02  # Store breathing volume for restoration (reduced from 0.1 for quieter effect)
        self._LED_BRIGHTNESS = 0.6
        
    async def start(self):
        """Start the sleep activity"""
        await super().start()
        self._is_active = True

        # Disabled for now -- worried it's screwing up the wakeword detection        
        # if PLATFORM == "raspberry-pi":
        #     self.logger.info("Entering power-saving sleep mode...")
        #     await system_utils.set_cpu_governor("powersave")
        #     await system_utils.set_bluetooth_enabled(False)

        # Start the breathing sound effect on loop
        # Commented out until I can figure out the volume issue
        # await self.publish({
        #     "type": "play_sound",
        #     "effect_name": SoundEffect.BREATHING,
        #     "loop": True,
        #     "volume": self._breathing_volume  # Very quiet for sleep mode
        # })
        
        # Stop any LED effect
        await self.publish({
            "type": "stop_led_effect"
        })
        
        # # Start the LED effect
        # await self.publish({
        #     "type": "start_led_effect",
        #     "data": {
        #         "effect_name": "rotating_green_yellow",
        #         "speed": 0.03,  # Slow, gentle rotation
        #         "brightness": self._LED_BRIGHTNESS  # Dimmer for sleep mode
        #     }
        # })
        
        self.logger.info("Sleep activity started")
        
    async def stop(self):
        """Stop the sleep activity"""
        if self._is_active:
            self._is_active = False
            
            # Disabled for now -- worried it's screwing up the wakeword detection        
            # if PLATFORM == "raspberry-pi":
            #     self.logger.info("Exiting power-saving sleep mode...")
            #     await system_utils.set_cpu_governor("ondemand")
            #     await system_utils.set_bluetooth_enabled(True)
            
            # Stop the breathing sound
            # Commented out until I can figure out the volume issue
            # await self.publish({
            #     "type": "stop_sound",
            #     "effect_name": SoundEffect.BREATHING
            # })
            
            # Stop the LED effect
            # NOTE: Disabled so we don't have a pause in effects while other activities start
            # await self.publish({
            #     "type": "stop_led_effect"
            # })
            
        await super().stop()
        self.logger.info("Sleep activity stopped")
        
    async def handle_event(self, event: Dict[str, Any]):
        """Handle events from other services"""
        event_type = event.get("type")
        
        if self._is_active:
            if event_type == "intent_detection_started":
                # Stop breathing sound during intent detection
                # await self.publish({
                #     "type": "stop_sound",
                #     "effect_name": SoundEffect.BREATHING
                # })
                # self.logger.info("Paused breathing sound for intent detection")
                pass
                
            elif event_type == "intent_detection_timeout":
                # Resume breathing sound after intent detection timeout
                # NOTE: Commented out until I can figure out the volume issue
                # await self.publish({
                #     "type": "play_sound",
                #     "effect_name": SoundEffect.BREATHING,
                #     "loop": True,
                #     "volume": self._breathing_volume
                # })
                
                # Restart the LED effect
                # NOTE: Don't do this anymore as we want the effect to be global, so handled by intent_service or led_service
                # await self.publish({
                #     "type": "start_led_effect",
                #     "data": {
                #         "effect_name": "rotating_pink_blue",
                #         "speed": 0.1,  # Slow, gentle rotation
                #         "brightness": self._LED_BRIGHTNESS
                #     }
                # })
                pass
                
                # self.logger.info("Resumed breathing sound and LED effect after intent detection timeout") 