"""
Service for managing the scavenger hunt game activity.
TODO: Description. 
"""

import logging
import asyncio
import random
from typing import Dict, Any, Optional
from services.service import BaseService
from config import ScavengerHuntConfig, ScavengerHuntStep, Distance, SoundEffect

class ScavengerHuntActivity(BaseService):
    """Service that manages the scavenger hunt game activity"""
    
    def __init__(self, service_manager):
        super().__init__(service_manager)
        self._sound_task: Optional[asyncio.Task] = None
        self._game_active: bool = False
        self._current_step: ScavengerHuntStep | None = None
        self._current_location_detected: bool = False  # Track if we've ever seen the next desired location.
        self._remaining_steps: list[ScavengerHuntStep] = ScavengerHuntConfig.SCAVENGER_HUNT_STEPS
        
    async def start(self):
        """Start the scavenger hunt service"""
        await super().start()
        self._game_active = True
        # Disable any LED effects
        await self.publish({
            "type": "stop_led_effect"
        })
        
        # Announce game start
        if ScavengerHuntConfig.START_AUDIO:
            await self.publish({
                "type": "speak_audio",
                "text": ScavengerHuntConfig.START_AUDIO
            })
        # Start the first task (maybe abstract this?)
        self._current_step = self._remaining_steps.pop(0)
        await self.publish({
            "type": "speak_audio",
            "text": self._current_step.START_VOICE_LINE
        })
        # Start sound task that periodically emits chirps
        self._sound_task = asyncio.create_task(self._sound_loop())
        self.logger.info(f"scavenger hunt service started; on step: {self._current_step_name}")
        
    async def stop(self):
        """Stop the scavenger hunt service"""
        self._game_active = False
        if self._sound_task:
            self._sound_task.cancel()
            try:
                await self._sound_task
            except asyncio.CancelledError:
                pass
            self._sound_task = None
        await super().stop()
        self.logger.info("scavenger hunt service stopped")
        
    @property
    def _current_step_name(self):
        return self._current_step.NAME
        
    def _calculate_volume(self, distance: Distance) -> float:
        """Calculate volume based on distance category
        
        Args:
            distance: The distance category from the pendant
            
        Returns:
            float: Volume level between 0.1 and 1.0
        """
        # Add type checking and logging
        if not isinstance(distance, Distance):
            self.logger.error(f"Invalid distance type: {type(distance)}, value: {distance}")
            return 1.0

        self.logger.info(f"Calculating volume for distance: {distance}, type: {type(distance)}")
            
        # Map distances to volume levels
        # Further = louder to help guide the player
        if distance == Distance.UNKNOWN:
            self.logger.info("Distance is UNKNOWN, using max volume")
            return 1.0  # Max volume when unknown/lost
        elif distance == Distance.VERY_FAR:
            vol = 0.8
            self.logger.info(f"Distance is VERY_FAR, volume: {vol:.2f}")
            return vol
        elif distance == Distance.FAR:
            vol = 0.5
            self.logger.info(f"Distance is FAR, volume: {vol:.2f}")
            return vol
        elif distance == Distance.NEAR:
            vol = 0.25
            self.logger.info(f"Distance is NEAR, volume: {vol:.2f}")
            return vol
        elif distance == Distance.VERY_NEAR:
            vol = 0.05
            self.logger.info(f"Distance is VERY_NEAR, volume: {vol:.2f}")
            return vol
        elif distance == Distance.IMMEDIATE:
            self.logger.info("Distance is IMMEDIATE, using min volume")
            return 0.01  # Minimum volume when very close
        else:
            self.logger.error(f"Unhandled distance value: {distance}")
            return 1.0  # Fallback to max volume
        
    async def _sound_loop(self):
        """Main loop that periodically emits chirp sounds based on pendant distance"""
        while self._game_active:
            try:
                # Only emit sounds if we've detected the next step's at least once
                if not self._current_location_detected:
                    await asyncio.sleep(1.0)  # Check less frequently when waiting for pendant
                    continue
                    
                # Get current step location info from global state
                async with self.global_state_lock:
                    self.logger.info("Acquired global state lock")
                    current_step_location_info = self.global_state.location_beacons.get(self._current_step.LOCATION, {})
                    self.logger.info(f"Current step info: {current_step_location_info}")
                    self.logger.info(f"All beacons in global state: {self.global_state.location_beacons}")
                
                if not current_step_location_info:
                    # No step detected, use max volume
                    volume = 1.0
                    self.logger.info("No step info, using max volume")
                else:
                    # Calculate volume based on distance category
                    distance = current_step_location_info.get("distance", Distance.UNKNOWN)
                    self.logger.info(f"Raw distance value from state: {distance}, type: {type(distance)}")
                    volume = self._calculate_volume(distance)
                    self.logger.info(f"Final calculated volume: {volume:.2f}")
                
                # Emit a random chirp sound
                chirp = random.choice([
                    SoundEffect.CHIRP1,
                    SoundEffect.CHIRP2,
                    SoundEffect.CHIRP3,
                    SoundEffect.CHIRP4,
                    SoundEffect.CHIRP5,
                    SoundEffect.CHIRP6,
                    SoundEffect.CHIRP7,
                    SoundEffect.CHIRP8,
                ])
                self.logger.info(f"Playing chirp {chirp} with volume {volume:.2f}")
                await self.publish({
                    "type": "play_sound",
                    "effect_name": chirp,
                    "volume": volume
                })
                
                # Wait for next interval
                await asyncio.sleep(ScavengerHuntConfig.AUDIO_CUE_INTERVAL)
                
            except Exception as e:
                self.logger.error(f"Error in sound loop: {e}")
                await asyncio.sleep(1.0)  # Wait a bit before retrying
                
    async def _transition_to_next_step(self):
        assert len(self._remaining_steps > 0), "Tried to go to next scavenger hunt step but none remaining!"
        # Play current step end noise.
        await self.publish({
            "type": "speak_audio",
            "text": self._current_step.END_VOICE_LINE
        })
        # Transition to next step.
        await asyncio.sleep(ScavengerHuntConfig.INTER_STEP_SLEEP_TIME)
        self._current_location_detected = False
        self._current_step = self._remaining_steps.pop(0)
        await self.publish({
            "type": "speak_audio",
            "text": self._current_step.START_VOICE_LINE
        })
    
    async def handle_event(self, event: Dict[str, Any]):
        """Handle events from other services"""
        event_type = event.get("type")
        
        if event_type == "proximity_changed":
            data = event.get("data", {})
            location = data.get("location")
            
            # Only care about the current step's location
            if location == self._current_step.LOCATION:
                distance = data.get("distance")
                
                # Mark that we've detected the next step's location at least once
                if not self._current_location_detected and distance != Distance.UNKNOWN:
                    self._current_location_detected = True
                    self.logger.info(f"Location {self._current_step.LOCATION} detected for the first time!")
                
                # If found current location, either transition to next step or declare victory.
                if distance == Distance.IMMEDIATE:
                    await self.publish({
                        "type": "scavenger_hunt_step_completed"
                    })
                    self.logger.info("Scavenger hunt step {self._current_step_name} completed!")

                    if self._remaining_steps:
                        self.transition_to_next_step()
                    else:
                        await self.publish({
                            "type": "scavenger_hunt_won"
                        })
                        self.logger.info("Scavenger hunt won!")
                        self._game_active = False