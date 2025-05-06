"""
This activity service is for movement-based play, such as dancing, running, throwing the ball, composing music, martial arts, yoga etc.
For our first implementation, we will use the accelerometer to detect movement energy and trigger sounds and lights matching the energy level.
We also detect state changes, like entering FREE_FALL, to trigger specific sounds and LED effects.
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
    2. Detect state transitions (e.g., entering/exiting FREE_FALL)
    3. Publish events when significant changes occur (like playing sounds or changing LEDs)
    4. Control LED effect (RANDOM_TWINKLING normally, RAINBOW during free fall) based on movement energy and state.
    """
    
    def __init__(self, service_manager):
        super().__init__(service_manager)
        self.current_energy = 0.0
        self.previous_state = SimplifiedState.UNKNOWN
        # Use logger from BaseService
        self.logger = logging.getLogger(self.__class__.__name__)
        # Track the energy level for the last sent LED update
        self.last_sent_energy = -1.0 # Initialize to ensure first update
        # --- Free Fall LED Handling ---
        self.in_free_fall = False
        # Store the default effect name used by this activity
        self.default_effect_name = "RANDOM_TWINKLING" 
        # Store the current parameters for the default effect
        self.twinkling_speed: float = 0.1 # Slower sparkle/update rate initially
        self.twinkling_brightness: float = 0.1 # Dim initial brightness
        
    async def start(self):
        """Start the move activity service and set initial LED effect."""
        await super().start()
        # Set initial LED effect to twinkling, using initial parameter values
        self.logger.info(f"Setting initial LED effect: {self.default_effect_name}, speed={self.twinkling_speed}, brightness={self.twinkling_brightness}")
        await self.publish({
            "type": "start_led_effect",
            "data": {
                "effectName": self.default_effect_name,
                "speed": self.twinkling_speed,
                "brightness": self.twinkling_brightness
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
        Detects FREE_FALL transitions to trigger sound and switch LED effects (RAINBOW).
        Updates the default LED effect (RANDOM_TWINKLING) based on movement energy when not in FREE_FALL.
        
        Args:
            event: The event to handle
        """
        if event.get("type") == "sensor_data" and event.get("sensor") == "accelerometer":
            # Extract data from accelerometer event
            data = event.get("data", {})
            current_state_name = data.get("current_state", SimplifiedState.UNKNOWN.name)
            energy = data.get("energy", 0.0) # Get energy level (0-1)

            # Convert state name back to enum member
            try:
                current_state_enum = SimplifiedState[current_state_name]
            except KeyError:
                self.logger.warning(f"Received unknown state name: {current_state_name}")
                current_state_enum = SimplifiedState.UNKNOWN

            # --- Free Fall State Transition Logic ---
            was_in_free_fall = self.in_free_fall
            is_currently_free_fall = (current_state_enum == SimplifiedState.FREE_FALL)

            # Entering Free Fall
            if is_currently_free_fall and not was_in_free_fall:
                # Only trigger if previous state was not something stationary/unknown
                if self.previous_state not in [SimplifiedState.UNKNOWN, SimplifiedState.STATIONARY, SimplifiedState.HELD_STILL]:
                    self.logger.info(f"Entering FREE_FALL from {self.previous_state.name}. Switching to RAINBOW effect.")
                    self.in_free_fall = True
                    
                    # Play sound
                    await self.publish({"type": "play_sound", "effect_name": SoundEffect.WEE})
                    
                    # Start RAINBOW effect 
                    await self.publish({
                        "type": "start_led_effect",
                        "data": { "effectName": "RAINBOW", "speed": 0.05, "brightness": 0.8 } # Example values
                    })
                else:
                    self.logger.debug(f"Detected FREE_FALL but previous state ({self.previous_state.name}) prevents triggering effects.")


            # Exiting Free Fall
            elif not is_currently_free_fall and was_in_free_fall:
                self.logger.info(f"Exiting FREE_FALL. Reverting to {self.default_effect_name} effect.")
                self.in_free_fall = False
                # Revert to twinkling using the last known parameters
                await self.publish({
                    "type": "start_led_effect",
                    "data": { 
                        "effectName": self.default_effect_name, 
                        "speed": self.twinkling_speed, 
                        "brightness": self.twinkling_brightness 
                    }
                })

            # --- LED Update Logic based on Energy (Only when NOT in Free Fall) ---
            if not self.in_free_fall:
                # Map energy (0-1) to speed (0.1 -> 0.01) and brightness (0.1 -> 1.0)
                # Speed: Higher energy -> faster sparkle/update rate (lower delay/interval)
                min_speed = 0.01 # Fastest
                max_speed = 0.1  # Slowest
                speed_range = max_speed - min_speed
                energy_curve_factor_speed = 0.5
                curved_energy_speed = pow(energy, energy_curve_factor_speed)
                interval = max_speed - (curved_energy_speed * speed_range)
                
                # Brightness: Higher energy -> brighter
                min_brightness = 0.1 # Min brightness
                max_brightness = 1.0 # Max brightness
                brightness_range = max_brightness - min_brightness
                energy_curve_factor_brightness = 0.5
                curved_energy_brightness = pow(energy, energy_curve_factor_brightness)
                brightness = min_brightness + (curved_energy_brightness * brightness_range)

                # Ensure brightness and interval are within valid ranges
                interval = max(min_speed, min(max_speed, interval))
                brightness = max(min_brightness, min(max_brightness, brightness))

                # --- Publish LED update only if energy changed significantly ---
                if abs(energy - self.last_sent_energy) > MoveActivityConfig.ENERGY_UPDATE_THRESHOLD:
                    # self.logger.debug(f"Energy changed ({self.last_sent_energy:.2f} -> {energy:.2f}). Updating {self.default_effect_name} LEDs.")
                    await self.publish({
                        "type": "start_led_effect", 
                        "data": {
                            "effectName": self.default_effect_name,
                            "speed": interval, 
                            "brightness": brightness
                        }
                    })
                    # Update the stored parameters for the default effect
                    self.twinkling_speed = interval
                    self.twinkling_brightness = brightness
                    self.last_sent_energy = energy
                # else: 
                    # self.logger.debug(f"Energy change below threshold. Skipping {self.default_effect_name} LED update.")

            # Update the previous state for the next cycle's comparison
            self.previous_state = current_state_enum
