"""Service for managing the squealing activity state."""

import logging
from typing import Dict, Any
from services.service import BaseService
from config import SoundEffect
from managers.accelerometer_manager import SimplifiedState

moving_states = [
    SimplifiedState.FREE_FALL,
    SimplifiedState.IMPACT,
    SimplifiedState.SHAKE,
    SimplifiedState.MOVING,
]

class SquealingActivity(BaseService):
    """Service that manages the squealing activity state
    
    When active, this service:
    1. Plays a bunch of squealing / "where are we" noises / voice lines
    2. On detecting being picked up, stops the activity.
    """
    
    def __init__(self, service_manager):
        super().__init__(service_manager)
        self._is_active = False
        # TODO: get from config.
        self._squealing_volume = 0.5 
        self._LED_BRIGHTNESS = 0.6
        
    async def start(self):
        """Start the squealing activity"""
        await super().start()
        self._is_active = True
        
        # Start the breathing sound effect on loop
        # Commented out until I can figure out the volume issue
        await self.publish({
            "type": "play_sound",
            "effect_name": SoundEffect.WEE1,
            "loop": True,
            "volume": self._squealing_volume
        })
        
        # Stop any previous LED effect
        await self.publish({
            "type": "stop_led_effect"
        })
        
        # # Start the LED effect
        await self.publish({
            "type": "start_led_effect",
            "data": {
                "effect_name": "GREEN_BREATHING",
                "speed": 0.03,  # Slow, gentle rotation
                "brightness": self._LED_BRIGHTNESS 
            }
        })
        
        self.logger.info("squealing activity started")
        
    async def stop(self):
        """Stop the squealing activity"""
        if self._is_active:
            self._is_active = False
            
        # Stop the breathing sound
        await self.publish({
            "type": "stop_sound",
            "effect_name": SoundEffect.WEE1
        })
        
        # Stop the LED effect
        await self.publish({
            "type": "stop_led_effect"
        })
            
        await super().stop()
        self.logger.info("squealing activity stopped")
        
    async def handle_event(self, event: Dict[str, Any]):
        """Handle events from other services"""
        event_type = event.get("type")
        
        if self._is_active:
            if event_type == "sensor_data" and event.get("sensor") == "accelerometer":
                # Extract data from accelerometer event
                data = event.get("data", {})
                current_state_name = data.get("current_state", SimplifiedState.UNKNOWN.name)
                self.logger.debug(f"Current state: {current_state_name}")
                # energy = data.get("energy", 0.0) # Get energy level (0-1)
                current_state_name = data.get("current_state", SimplifiedState.UNKNOWN.name)
                
                # Convert state name back to enum member
                try:
                    current_state_enum = SimplifiedState[current_state_name]
                except KeyError:
                    self.logger.warning(f"Received unknown state name: {current_state_name}")
                    current_state_enum = SimplifiedState.UNKNOWN
                    return
                
                if current_state_enum in moving_states:
                    self._is_active = False
                    await self.publish({
                        "type": "speak_audio",
                        "text": "This will be much longer eventually but we've been picked up by the Earthlings!"
                    })
                    await self.publish({
                        "type": "squealing_ended"
                    })
                    self.logger.info("Squealing ended!")

                    
                


    