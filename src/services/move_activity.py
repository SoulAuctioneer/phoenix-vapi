"""
This activity service is for movement-based play, such as dancing, running, throwing the ball, composing music, martial arts, yoga etc.
For our first implementation, we will use the accelerometer to detect movement energy and trigger sounds and lights matching the energy level.
We also detect state changes, like entering FREE_FALL, to trigger specific sounds.
"""

import asyncio
import math
from typing import Dict, Any, Tuple
from services.service import BaseService
from config import MoveActivityConfig, SoundEffect
from managers.accelerometer_manager import SimplifiedState

class MoveActivity(BaseService):
    """
    A service that maintains activity state and movement energy level.
    
    This service processes accelerometer data to:
    1. Calculate a movement energy level (0-1) based on acceleration and rotation
    2. Detect state transitions (e.g., entering FREE_FALL)
    3. Publish events when significant changes occur (like playing a sound on free fall start)
    """
    
    def __init__(self, service_manager):
        super().__init__(service_manager)
        self.current_energy = 0.0
        self.previous_state = SimplifiedState.UNKNOWN
        
    async def start(self):
        """Start the move activity service"""
        await super().start()
        self.logger.info("Move activity service started")
        
    async def stop(self):
        """Stop the move activity service"""
        await super().stop()
        self.logger.info("Move activity service stopped")
        
    async def handle_event(self, event: Dict[str, Any]):
        """
        Handle events from other services, particularly accelerometer sensor data.
        Detects state transition into FREE_FALL to trigger sound.
        
        Args:
            event: The event to handle
        """
        if event.get("type") == "sensor_data" and event.get("sensor") == "accelerometer":
            # Extract data from accelerometer event
            data = event.get("data", {})
            current_state_name = data.get("current_state", SimplifiedState.UNKNOWN.name)

            # Convert state name back to enum member if needed for comparison/storage
            try:
                current_state_enum = SimplifiedState[current_state_name]
            except KeyError:
                current_state_enum = SimplifiedState.UNKNOWN

            # Check for transition *into* FREE_FALL from a moving state
            # This approximates detecting the start of a throw/drop.
            is_entering_free_fall = (
                current_state_enum == SimplifiedState.FREE_FALL and
                self.previous_state != SimplifiedState.FREE_FALL and
                # Optionally, ensure it wasn't stationary just before
                self.previous_state not in [SimplifiedState.STATIONARY, SimplifiedState.HELD_STILL, SimplifiedState.UNKNOWN]
            )

            if is_entering_free_fall:
                self.logger.info(f"Entering FREE_FALL from {self.previous_state.name}, playing WEE sound")
                # Emit an event to request the audio service play the sound
                await self.publish({
                    "type": "play_sound",
                    "effect_name": SoundEffect.WEE
                })

            # TODO: Set LED color based on energy level (using data.get('energy', 0.0))

            # Update the previous state for the next cycle
            self.previous_state = current_state_enum

    