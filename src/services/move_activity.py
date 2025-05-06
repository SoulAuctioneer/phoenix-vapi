"""
This activity service is for movement-based play, such as dancing, running, throwing the ball, composing music, martial arts, yoga etc.
For our first implementation, we will use the accelerometer to detect movement energy and trigger sounds and lights matching the energy level.
We also detect state changes, like entering FREE_FALL, to trigger specific sounds.
"""

import logging
from typing import Dict, Any
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
    4. Control LED brightness and speed based on movement energy.
    """
    
    def __init__(self, service_manager):
        super().__init__(service_manager)
        self.current_energy = 0.0
        self.previous_state = SimplifiedState.UNKNOWN
        # Use logger from BaseService
        self.logger = logging.getLogger(self.__class__.__name__)
        # Track the energy level for the last sent LED update
        self.last_sent_energy = -1.0 # Initialize to ensure first update
        
    async def start(self):
        """Start the move activity service and set initial LED effect."""
        await super().start()
        # Set initial LED effect to rotating rainbow, dim and slow
        initial_speed = 0.1
        initial_brightness = 0.1
        self.logger.info(f"Setting initial LED effect: rotating_rainbow, speed={initial_speed}, brightness={initial_brightness}")
        await self.publish({
            "type": "start_led_effect",
            "data": {
                "effectName": "rotating_rainbow",
                "speed": initial_speed,
                "brightness": initial_brightness
            }
        })
        self.logger.info("Move activity service started")
        
    async def stop(self):
        """Stop the move activity service"""
        # Optionally: Stop or revert the LED effect? 
        # For now, let the activity manager handle the transition.
        await super().stop()
        self.logger.info("Move activity service stopped")
        
    async def handle_event(self, event: Dict[str, Any]):
        """
        Handle events from other services, particularly accelerometer sensor data.
        Detects state transition into FREE_FALL to trigger sound.
        Updates LED effect based on movement energy.
        
        Args:
            event: The event to handle
        """
        if event.get("type") == "sensor_data" and event.get("sensor") == "accelerometer":
            # Extract data from accelerometer event
            data = event.get("data", {})
            current_state_name = data.get("current_state", SimplifiedState.UNKNOWN.name)
            energy = data.get("energy", 0.0) # Get energy level (0-1)

            # Convert state name back to enum member if needed for comparison/storage
            try:
                current_state_enum = SimplifiedState[current_state_name]
            except KeyError:
                current_state_enum = SimplifiedState.UNKNOWN

            # --- State Transition Logic (e.g., Free Fall Sound) ---
            is_entering_free_fall = (
                current_state_enum == SimplifiedState.FREE_FALL and
                self.previous_state != SimplifiedState.FREE_FALL and
                self.previous_state not in [SimplifiedState.STATIONARY, SimplifiedState.HELD_STILL, SimplifiedState.UNKNOWN]
            )

            if is_entering_free_fall:
                self.logger.info(f"Entering FREE_FALL from {self.previous_state.name}, playing WEE sound")
                await self.publish({
                    "type": "play_sound",
                    "effect_name": SoundEffect.WEE
                })

            # --- LED Update Logic based on Energy ---
            # Map energy (0-1) to speed (0.1 -> 0.01) and brightness (0.1 -> 1.0)
            # Speed: Higher energy -> faster rotation (lower delay)
            min_speed = 0.01 # Fastest speed at max energy
            max_speed = 0.1  # Slowest speed at min energy
            speed_range = max_speed - min_speed
            # Linear mapping: speed = max_speed - (energy * speed_range)
            # Apply a curve (e.g., power of 2) to make speed increase faster at higher energies
            energy_curve_factor_speed = 2.0 
            curved_energy_speed = pow(energy, energy_curve_factor_speed)
            # Rename 'speed' to 'interval' as the value represents the update delay
            interval = max_speed - (curved_energy_speed * speed_range)
            
            # Brightness: Higher energy -> brighter LEDs
            min_brightness = 0.1 # Minimum brightness at min energy
            max_brightness = 1.0 # Maximum brightness at max energy
            brightness_range = max_brightness - min_brightness
            # Linear mapping: brightness = min_brightness + (energy * brightness_range)
            # Apply a curve (e.g., power of 0.5) for faster initial brightness increase
            energy_curve_factor_brightness = 0.5
            curved_energy_brightness = pow(energy, energy_curve_factor_brightness)
            brightness = min_brightness + (curved_energy_brightness * brightness_range)

            # Ensure brightness and speed are within valid ranges
            # Ensure brightness and interval are within valid ranges
            interval = max(min_speed, min(max_speed, interval))
            brightness = max(min_brightness, min(max_brightness, brightness))

            # --- Publish LED update only if energy changed significantly ---
            if abs(energy - self.last_sent_energy) > MoveActivityConfig.ENERGY_UPDATE_THRESHOLD:
                # self.logger.debug(f"Energy changed significantly ({self.last_sent_energy:.2f} -> {energy:.2f}). Updating LEDs.") # Debug log
                # Publish LED update event
                await self.publish({
                    "type": "start_led_effect", # Use start_led_effect to update parameters
                    "data": {
                        "effectName": "rotating_rainbow",
                        "speed": interval, # Pass the calculated interval as the 'speed' parameter value
                        "brightness": brightness
                    }
                })
                # Update the energy level that triggered the last update
                self.last_sent_energy = energy
            # else: # Optional: Log skipped updates
                # self.logger.debug(f"Energy change ({self.last_sent_energy:.2f} -> {energy:.2f}) below threshold ({self.energy_update_threshold}). Skipping LED update.")

            # Update the previous state for the next cycle
            self.previous_state = current_state_enum

    