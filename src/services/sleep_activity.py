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
        
    async def start(self):
        """Start the sleep activity"""
        await super().start()
        self._is_active = True
        
        # Start the breathing sound effect on loop
        await self.publish({
            "type": "play_sound",
            "effect_name": SoundEffect.BREATHING,
            "loop": True,
            "volume": 0.2  # Lower volume for sleep mode
        })
        
        # Set LED effect to rotating pink/blue
        await self.publish({
            "type": "start_led_effect",
            "data": {
                "effectName": "pink_blue_cycle",
                "speed": 0.05,  # Slow, gentle rotation
                "brightness": 0.3  # Dimmer for sleep mode
            }
        })
        
        self.logger.info("Sleep activity started")
        
    async def stop(self):
        """Stop the sleep activity"""
        if self._is_active:
            self._is_active = False
            
            # Stop the breathing sound
            await self.publish({
                "type": "play_sound",
                "effect_name": "stop"
            })
            
            # Stop the LED effect (will be handled by the next activity)
            await self.publish({
                "type": "start_led_effect",
                "data": {
                    "effectName": "stop"
                }
            })
            
        await super().stop()
        self.logger.info("Sleep activity stopped")
        
    async def handle_event(self, event: Dict[str, Any]):
        """Handle events from other services"""
        # Sleep activity mainly just maintains its state
        # It doesn't need to handle many events since it's a passive state
        pass 