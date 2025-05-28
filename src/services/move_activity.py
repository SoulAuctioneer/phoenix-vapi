"""
This activity service is for movement-based play, such as dancing, running, throwing the ball, composing music, martial arts, yoga etc.
For our first implementation, we will use the accelerometer to detect movement energy and trigger sounds and lights matching the energy level.
We also detect state changes, like entering FREE_FALL, to trigger specific sounds and LED effects.
"""

import logging
import random
import time # Import time module
from typing import Dict, Any, Optional
from services.service import BaseService
from config import MoveActivityConfig, SoundEffect
from managers.accelerometer_manager import SimplifiedState

# Store giggle sounds for easy cycling
_giggle_sounds = (SoundEffect.GIGGLE1, SoundEffect.GIGGLE2, SoundEffect.GIGGLE3)
_wee_sounds = (SoundEffect.WEE1, SoundEffect.WEE2, SoundEffect.WEE3, SoundEffect.WEE4)
_ouch_sounds = (SoundEffect.OUCH1, SoundEffect.OUCH2)

# Cooldown period before a giggle sound can play after ANY sound effect (in seconds)
GIGGLE_COOLDOWN_SECONDS = 2.0

class MoveActivity(BaseService):
    """
    A service that maintains activity state and movement energy level.
    
    This service processes accelerometer data to:
    1. Calculate a movement energy level (0-1) based on acceleration and rotation
    2. Detect state transitions (e.g., entering/exiting FREE_FALL)
    3. Publish events when significant changes occur (like playing sounds or changing LEDs)
    4. Control LED effect based on state:
        - FREE_FALL: RAINBOW
        - HELD_STILL: ROTATING_PINK_BLUE (starts after 2s, gets faster and brighter over 10s)
        - MOVING: BLUE_BREATHING (static)
        - STATIONARY: No LED effect
        - Other states: BLUE_BREATHING (static)
    """
    
    def __init__(self, service_manager):
        super().__init__(service_manager)
        self.current_energy = 0.0
        self.previous_state = SimplifiedState.UNKNOWN
        # Use logger from BaseService
        self.logger = logging.getLogger(self.__class__.__name__)
        # Track the energy level for the last sent LED update for the default effect
        self.last_sent_energy = -1.0 # Initialize to ensure first update
        # --- State Flags ---
        self.in_free_fall = False
        self.is_held_still = False # Added for HELD_STILL state
        self.is_moving = False # Added for MOVING state
        self.is_stationary = False # Added for STATIONARY state
        # --- LED Effect Tracking ---
        self.current_led_effect: Dict[str, Any] = {"name": None, "params": {}} # Track current effect sent
        # Store the default effect name used by this activity (no longer used for energy patterns)
        self.default_effect_name = "BLUE_BREATHING"
        # Store the current parameters for the default effect (updated dynamically)
        self.twinkling_speed: float = 0.3 # Slower sparkle/update rate initially
        self.twinkling_brightness: float = 0.05 # Dim initial brightness
        # --- HELD_STILL ROTATING_PINK_BLUE Effect Tracking ---
        self.held_still_start_time: Optional[float] = None  # When HELD_STILL state started
        self.held_still_effect_active = False  # Whether ROTATING_PINK_BLUE effect is currently active
        # --- Shake Handling ---
        self._giggle_index = 0 # Index for cycling through giggle sounds
        self._wee_index = 0 # Index for cycling through WEE sounds
        self._ouch_index = 0 # Index for cycling through OUCH sounds
        self._last_sound_play_time: float = 0.0 # Timestamp of the last sound played by this service
        
    async def start(self):
        """Start the move activity service and set initial LED effect."""
        await super().start()
        # Set initial LED effect to a gentle breathing effect since we don't know the state yet
        initial_effect = "BLUE_BREATHING"
        initial_params = {
            "speed": 0.2,
            "brightness": 0.2
        }
        self.logger.info(f"Setting initial LED effect: {initial_effect}, params={initial_params}")
        await self.publish({
            "type": "start_led_effect",
            "data": { "effect_name": initial_effect, **initial_params }
        })
        # Track the initial effect
        self.current_led_effect = {"name": initial_effect, "params": initial_params}
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
        Detects state transitions to trigger sounds (SHAKE, IMPACT, FREE_FALL).
        Determines the appropriate LED effect based on the current state:
        - FREE_FALL: RAINBOW effect
        - HELD_STILL: ROTATING_PINK_BLUE effect (starts after 2s delay, gets faster and brighter over time)
        - MOVING: BLUE_BREATHING effect (static)
        - STATIONARY: No LED effect
        - Other states: Static BLUE_BREATHING effect
        Publishes LED changes when the target effect or its parameters change significantly.
        
        Args:
            event: The event to handle
        """
        if event.get("type") == "sensor_data" and event.get("sensor") == "accelerometer":
            # Extract data from accelerometer event
            data = event.get("data", {})
            current_state_name = data.get("current_state", SimplifiedState.UNKNOWN.name)
            self.logger.debug(f"Current state: {current_state_name}")
            energy = data.get("energy", 0.0) # Get energy level (0-1)

            # Convert state name back to enum member
            try:
                current_state_enum = SimplifiedState[current_state_name]
            except KeyError:
                self.logger.warning(f"Received unknown state name: {current_state_name}")
                current_state_enum = SimplifiedState.UNKNOWN

            # --- State Transition Logic (Primarily for Sounds) ---
            state_changed = (current_state_enum != self.previous_state)

            # Entering SHAKE
            if state_changed and current_state_enum == SimplifiedState.SHAKE:
                self.logger.info("Detected SHAKE entry. Playing giggle sound.")
                # Check cooldown against the last time *any* sound was played
                current_time = time.monotonic()
                if current_time - self._last_sound_play_time >= GIGGLE_COOLDOWN_SECONDS:
                    # Choose sound effect based on current index
                    effect_to_play = _giggle_sounds[self._giggle_index]
                    # Play sound at half volume
                    await self.publish({"type": "play_sound", "effect_name": effect_to_play, "volume": 0.4})
                    # Update last sound play time
                    self._last_sound_play_time = current_time
                    # Increment index for next time, cycling through 0, 1, 2
                    self._giggle_index = (self._giggle_index + 1) % len(_giggle_sounds)
                else:
                    self.logger.debug("Giggle cooldown active, skipping sound.")

            # Entering IMPACT
            elif state_changed and current_state_enum == SimplifiedState.IMPACT:
                self.logger.info("Detected IMPACT entry. Stopping WEE and playing OOF sound.")
                current_time = time.monotonic()
                # Stop WEE
                await self.publish({"type": "stop_sound", "effect_name": _wee_sounds[self._wee_index]})
                # Play sound (using default volume)
                await self.publish({"type": "play_sound", "effect_name": _ouch_sounds[self._ouch_index]})
                # Update last sound play time
                self._last_sound_play_time = current_time
                # Increment index for next time, cycling through 0, 1
                self._ouch_index = (self._ouch_index + 1) % len(_ouch_sounds)

            # Entering FREE_FALL
            elif state_changed and current_state_enum == SimplifiedState.FREE_FALL:
                self.logger.info(f"Detected FREE_FALL entry from {self.previous_state.name}.")
                current_time = time.monotonic()
                # Play sound
                # Choose a random WEE sound
                effect_to_play = _wee_sounds[self._wee_index]
                await self.publish({"type": "play_sound", "effect_name": effect_to_play, "volume": 0.4})
                # Update last sound play time
                self._last_sound_play_time = current_time
                # Increment index for next time, cycling through 0, 1, 2, 3
                self._wee_index = (self._wee_index + 1) % len(_wee_sounds)
                # LED change handled below based on current state

            # Update internal state flags based on current state
            self.in_free_fall = (current_state_enum == SimplifiedState.FREE_FALL)
            previous_held_still = self.is_held_still
            self.is_held_still = (current_state_enum == SimplifiedState.HELD_STILL)
            self.is_moving = (current_state_enum == SimplifiedState.MOVING)
            self.is_stationary = (current_state_enum == SimplifiedState.STATIONARY)
            
            # Track HELD_STILL timing for ROTATING_PINK_BLUE effect
            current_time = time.monotonic()
            if self.is_held_still and not previous_held_still:
                # Just entered HELD_STILL state
                self.held_still_start_time = current_time
                self.held_still_effect_active = False
                self.logger.info("Entered HELD_STILL state, starting timer for ROTATING_PINK_BLUE effect")
            elif not self.is_held_still and previous_held_still:
                # Just exited HELD_STILL state
                self.held_still_start_time = None
                if self.held_still_effect_active:
                    self.held_still_effect_active = False
                    self.logger.info("Exited HELD_STILL state, canceling ROTATING_PINK_BLUE effect")


            # --- Determine Target LED Effect based on Current State ---
            target_effect_name: Optional[str] = None
            target_params: Dict[str, Any] = {}

            if self.in_free_fall:
                target_effect_name = "RAINBOW"
                # Define consistent parameters for this effect
                target_params = {"speed": 0.05, "brightness": 0.8}
            elif self.is_held_still:
                # Check if we should start or update ROTATING_PINK_BLUE effect
                if self.held_still_start_time is not None:
                    time_held_still = current_time - self.held_still_start_time
                    
                    if time_held_still >= MoveActivityConfig.HELD_STILL_EFFECT_DELAY:
                        # Start or update ROTATING_PINK_BLUE effect
                        target_effect_name = "ROTATING_PINK_BLUE"
                        
                        # Calculate progress based on how long we've been held still
                        progress = min(1.0, (time_held_still - MoveActivityConfig.HELD_STILL_EFFECT_DELAY) / 
                                      (MoveActivityConfig.HELD_STILL_MAX_SPEED_TIME - MoveActivityConfig.HELD_STILL_EFFECT_DELAY))
                        
                        # Interpolate speed between min and max (lower = faster)
                        speed = MoveActivityConfig.HELD_STILL_MIN_SPEED - (progress * 
                               (MoveActivityConfig.HELD_STILL_MIN_SPEED - MoveActivityConfig.HELD_STILL_MAX_SPEED))
                        
                        # Interpolate brightness between min and max (higher = brighter)
                        brightness = MoveActivityConfig.HELD_STILL_MIN_BRIGHTNESS + (progress * 
                                   (MoveActivityConfig.HELD_STILL_MAX_BRIGHTNESS - MoveActivityConfig.HELD_STILL_MIN_BRIGHTNESS))
                        
                        target_params = {"speed": speed, "brightness": brightness}
                        
                        if not self.held_still_effect_active:
                            self.held_still_effect_active = True
                            self.logger.info(f"Starting ROTATING_PINK_BLUE effect after {time_held_still:.1f}s held still")
                    else:
                        # Still waiting for delay, use default stationary effect
                        target_effect_name = "BLUE_BREATHING"
                        target_params = {"speed": 0.1, "brightness": 0.3}
                else:
                    # Fallback if timing is somehow broken
                    target_effect_name = "BLUE_BREATHING"
                    target_params = {"speed": 0.1, "brightness": 0.3}
            elif self.is_stationary:
                # No LED effect when stationary
                target_effect_name = None
                target_params = {}
            elif self.is_moving:
                # Use blue breathing effect when moving
                target_effect_name = "BLUE_BREATHING"
                target_params = {"speed": 0.15, "brightness": 0.6}
            else:
                # For other states (IMPACT, SHAKE, UNKNOWN), use a simple static effect
                target_effect_name = "BLUE_BREATHING"
                target_params = {"speed": 0.2, "brightness": 0.2}


            # --- Publish LED Update if Needed ---
            needs_update = False
            current_effect_name = self.current_led_effect.get("name")
            current_params = self.current_led_effect.get("params", {})

            if target_effect_name != current_effect_name:
                # Effect name changed, definitely update
                needs_update = True
                self.logger.info(f"Target LED Effect changed from {current_effect_name} to {target_effect_name} due to state {current_state_enum.name}")
            elif target_effect_name == "ROTATING_PINK_BLUE" and self.held_still_effect_active:
                # For ROTATING_PINK_BLUE effect, check if speed or brightness changed significantly
                current_speed = current_params.get("speed", 0)
                current_brightness = current_params.get("brightness", 0)
                target_speed = target_params.get("speed", 0)
                target_brightness = target_params.get("brightness", 0)
                if (abs(current_speed - target_speed) > 0.01 or  # Update if speed changed by more than 0.01
                    abs(current_brightness - target_brightness) > 0.05):  # Update if brightness changed by more than 0.05
                    needs_update = True

            if needs_update:
                if target_effect_name is not None:
                    # Start or update LED effect
                    self.logger.debug(f"Publishing LED update: {target_effect_name}, {target_params}")
                    await self.publish({
                        "type": "start_led_effect",
                        "data": { "effect_name": target_effect_name, **target_params }
                    })
                    # Update tracked state
                    self.current_led_effect = {"name": target_effect_name, "params": target_params}
                else:
                    # Stop LED effect (for STATIONARY state)
                    self.logger.debug("Stopping LED effect for STATIONARY state")
                    await self.publish({
                        "type": "stop_led_effect"
                    })
                    # Update tracked state
                    self.current_led_effect = {"name": None, "params": {}}
                
                # Reset last_sent_energy since we're no longer using energy-based effects
                self.last_sent_energy = -1.0

            self.logger.debug(f"Current state: {current_state_enum.name}, Energy: {energy:.2f}")

            # Log state change if it occurred
            if state_changed:
                self.logger.info(f"State changed from {self.previous_state.name} to {current_state_enum.name}")

            # Update the previous state for the next cycle's comparison
            self.previous_state = current_state_enum
