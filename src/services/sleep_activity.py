"""Service for managing the sleep activity state."""

import logging
from typing import Dict, Any
from services.service import BaseService
from config import SoundEffect

class SleepActivity(BaseService):
    """Service that manages the sleep activity state
    
    When active, this service:
    1. Plays the breathing sound effect on loop
    2. Sets the LED effect to rotating pink/blue
    """
    
    def __init__(self, manager):
        super().__init__(manager)
        self._is_active = False
        self._breathing_volume = 0.02  # Store breathing volume for restoration (reduced from 0.1 for quieter effect)
        self._LED_BRIGHTNESS = 0.6 # TODO: Move to config
        
    async def start(self):
        """Start the sleep activity"""
        await super().start()
        self._is_active = True
        
        # Start the breathing sound effect on loop
        # Commented out until I can figure out the volume issue
        # await self.publish({
        #     "type": "play_sound",
        #     "effect_name": SoundEffect.BREATHING,
        #     "loop": True,
        #     "volume": self._breathing_volume  # Very quiet for sleep mode
        # })
        
        # Set LED effect to rotating pink/blue
        await self.publish({
            "type": "start_led_effect",
            "data": {
                "effectName": "pink_blue_cycle",
                "speed": 0.05,  # Slow, gentle rotation
                "brightness": self._LED_BRIGHTNESS  # Dimmer for sleep mode
            }
        })
        
        self.logger.info("Sleep activity started")
        
    async def stop(self):
        """Stop the sleep activity"""
        if self._is_active:
            self._is_active = False
            
            # Stop the breathing sound
            # Commented out until I can figure out the volume issue
            # await self.publish({
            #     "type": "stop_sound",
            #     "effect_name": SoundEffect.BREATHING
            # })
            
            # Stop the LED effect
            await self.publish({
                "type": "stop_led_effect"
            })
            
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
                # Commented out until I can figure out the volume issue
                # await self.publish({
                #     "type": "play_sound",
                #     "effect_name": SoundEffect.BREATHING,
                #     "loop": True,
                #     "volume": self._breathing_volume
                # })
                
                # Restart the LED effect
                await self.publish({
                    "type": "start_led_effect",
                    "data": {
                        "effectName": "pink_blue_cycle",
                        "speed": 0.05,  # Slow, gentle rotation
                        "brightness": self._LED_BRIGHTNESS
                    }
                })
                
                self.logger.info("Resumed breathing sound and LED effect after intent detection timeout") 