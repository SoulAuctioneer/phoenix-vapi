"""
This activity service is for movement-based play, such as dancing, running, throwing the ball, composing music, martial arts, yoga etc.
For our first implementation, we will use the accelerometer to detect movement energy and trigger sounds and lights matching the energy level.
"""

import asyncio
import math
from typing import Dict, Any, Tuple
from services.service import BaseService
from config import MoveActivityConfig, SoundEffect
from managers.accelerometer_manager import MotionPattern

class MoveActivity(BaseService):
    """
    A service that maintains activity state and movement energy level.
    
    This service processes accelerometer data to:
    1. Track the current activity state using the accelerometer's classification
    2. Calculate a movement energy level (0-1) based on acceleration and rotation
    3. Publish events when significant changes occur
    """
    
    def __init__(self, service_manager):
        super().__init__(service_manager)
        self.current_activity = "unknown"
        self.previous_activity = "unknown"
        self.current_energy = 0.0
        self.previous_energy = 0.0
        self.energy_window = []  # Keep a window of recent energy values for smoothing
        
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
        
        Args:
            event: The event to handle
        """
        if event.get("type") == "sensor_data" and event.get("sensor") == "accelerometer":
            # Extract data from accelerometer event
            data = event.get("data", {})

            # Check for detected motion patterns
            detected_patterns = data.get("detected_patterns", [])

            # If a "THROW" pattern is detected, play the "WEE" sound effect
            if MotionPattern.THROW.name in detected_patterns:
                self.logger.info("Throw detected, playing WEE sound")
                # Emit an event to request the audio service play the sound
                await self.emit_event({
                    "type": "play_sound",
                    "effect_name": SoundEffect.WEE
                })

            # TODO: Set LED color based on energy level

    