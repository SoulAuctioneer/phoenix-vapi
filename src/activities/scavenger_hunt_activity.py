"""
Service for managing the scavenger hunt game activity.
TODO: Description. 
"""

import logging
import asyncio
import random
from typing import Dict, Any, Optional
from services.service import BaseService
from config import ScavengerHuntConfig, ScavengerHuntStep, ScavengerHuntLocation, Distance, SoundEffect

class ScavengerHuntActivity(BaseService):
    """Service that manages the scavenger hunt game activity"""
    
    def __init__(self, service_manager):
        super().__init__(service_manager)
        self._sound_task: Optional[asyncio.Task] = None
        self._game_active: bool = False
        self._current_step: ScavengerHuntStep | None = None
        self._current_location_detected: bool = False  # Track if we've ever seen the next desired location.
        self._remaining_steps: list[ScavengerHuntStep] = ScavengerHuntConfig.SCAVENGER_HUNT_STEPS
        if not self._remaining_steps:
            self.logger.error("Created a scavenger hunt with no steps!")
        
        # Phrases for when the beacon is first detected
        self._initial_detection_phrases: Dict[Distance, list[str]] = {
            Distance.VERY_FAR: [
                "Ooh, I think I sense something, but it's really, really far away.",
                "I can feel a faint wiggle... I think we're on the right path, but it's a long way to go."
            ],
            Distance.FAR: [
                "We're heading in the right direction! I can feel it, but it's still pretty far.",
                "Yes! A signal! It's not strong, but it's there. Let's keep going!"
            ],
            Distance.NEAR: [
                "Ooh, we're getting warmer! I can feel its energy now!",
                "The wiggles are getting stronger! We must be getting close."
            ],
            Distance.VERY_NEAR: [
                "Wow, it's so close now! My lights are practically dancing!",
                "I'm buzzing with excitement! It's just up ahead!"
            ]
        }

        # Phrases for getting closer to the beacon
        self._getting_closer_phrases: Dict[Distance, list[str]] = {
            Distance.FAR: [
                "Yes, that's it! We're getting closer. The wiggles are getting stronger!",
                "We're getting warmer! Keep going this way."
            ],
            Distance.NEAR: [
                "We're getting so warm! It must be just around the corner!",
                "Oh, this is definitely the right way. I can feel it getting stronger!"
            ],
            Distance.VERY_NEAR: [
                "It's right here! I can almost touch it! My whole body is buzzing!",
                "We're so, so close! Don't stop now!"
            ]
        }

        # Phrases for getting farther from the beacon
        self._getting_farther_phrases: Dict[Distance, list[str]] = {
            Distance.NEAR: [
                "Oh no, the feeling is getting weaker. I think we're going the wrong way.",
                "Hmm, I think we're getting colder. Let's try turning around."
            ],
            Distance.FAR: [
                "We're getting colder... Let's turn back and try a different path.",
                "Whoopsie! The signal is getting faint. We must have taken a wrong turn."
            ],
            Distance.VERY_FAR: [
                "Whoopsie! The signal is almost gone. We've gone way off track!",
                "Oh no, we're going the wrong way! The wiggles are almost gone."
            ]
        }
        
        # Phrases for when the signal is lost
        self._lost_signal_phrases: list[str] = [
            "Oh dear, I've lost the signal. Where did it go?",
            "Hmm, I can't feel it anymore. It must be hiding from us!",
            "The trail went cold. Let's retrace our steps."
        ]
        
    async def start(self):
        """Start the scavenger hunt service"""
        await super().start()
        self._game_active = True
        # Disable any LED effects
        await self.publish({
            "type": "stop_led_effect"
        })
        
        # Start the first step in our hunt.
        await self._start_next_step()
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
        
    async def _start_next_step(self):
        if not self._remaining_steps:
            self.logger.error("Trying to start next step when none remain!")
        self._current_step = self._remaining_steps.pop(0)
        self._current_location_detected = False
        await self.publish({
            "type": "speak_audio",
            "text": random.choice(self._current_step.START_VOICE_LINES)
        })
        
    @property
    def _current_step_name(self) -> str:
        return self._current_step.NAME
        
    def _calculate_chirp_interval(self, distance: Distance) -> float:
        """Calculate interval based on distance category.
        The closer the scavenger is, the more often P will chirp.
        
        Args:
            distance: The distance category from the current step location.
            
        Returns:
            float: Chirp interval in seconds between 0.1 and 1.0
        """
        if not isinstance(distance, Distance):
            self.logger.error(f"Invalid distance type: {type(distance)}, value: {distance}")
            return 1.0
        
        distances_to_intervals: dict[Distance, float] = {
            Distance.UNKNOWN: 1.0,
            Distance.VERY_FAR: 0.8,
            Distance.FAR: 0.6,
            Distance.NEAR: 0.4,
            Distance.VERY_NEAR: 0.2,
            Distance.IMMEDIATE: 0.1,
        }
        interval = ScavengerHuntConfig.CHIRP_INTERVAL_SCALING_FACTOR * distances_to_intervals[distance] if distance in distances_to_intervals else 1.0
        self.logger.info(f"Distance is {distance}, using chirp interval ({interval})")
        
    async def _sound_loop(self):
        """Main loop that periodically emits chirp sounds based on current step location distance"""
        while self._game_active:
            try:
                # Only emit sounds if we've detected the next step's at least once
                if not self._current_location_detected:
                    # Check less frequently when waiting to find the distance to current step location.
                    self.logger.info(f"Can't find next location: {self._current_step.LOCATION}")
                    await asyncio.sleep(1.0)
                    continue
                    
                # Get current step location info from global state
                async with self.global_state_lock:
                    self.logger.info("Acquired global state lock")
                    current_step_location_info = self.global_state.location_beacons.get(self._current_step.LOCATION, {})
                    self.logger.info(f"Current step info: {current_step_location_info}")
                    self.logger.info(f"All beacons in global state: {self.global_state.location_beacons}")
                
                if not current_step_location_info:
                    # No step detected, use max interval.
                    chirp_interval = 1.0
                    self.logger.info("No step info, using max chirp interval")
                else:
                    # Calculate chirp interval based on distance category
                    distance = current_step_location_info.get("distance", Distance.UNKNOWN)
                    self.logger.info(f"Raw distance value from state: {distance}, type: {type(distance)}")
                    chirp_interval = self._calculate_chirp_interval(distance)
                    self.logger.info(f"Final calculated chirp interval: {chirp_interval:.2f}")
                
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
                self.logger.info(f"Playing chirp {chirp} with chirp_interval {chirp_interval:.2f}")
                await self.publish({
                    "type": "play_sound",
                    "effect_name": chirp,
                    "volume": ScavengerHuntConfig.CHIRP_VOLUME
                })
                
                # Wait for next interval
                await asyncio.sleep(chirp_interval)
                
            except Exception as e:
                self.logger.error(f"Error in sound loop: {e}")
                await asyncio.sleep(1.0)  # Wait a bit before retrying
                
    async def _transition_to_next_step(self):
        await self.publish({
            "type": "speak_audio",
            "text": random.choice(self._current_step.END_VOICE_LINES)
        })
        await asyncio.sleep(ScavengerHuntConfig.INTER_STEP_SLEEP_TIME)
        await self._start_next_step()
    
    async def handle_event(self, event: Dict[str, Any]):
        """Handle events from other services"""
        event_type = event.get("type")
        if event_type == "proximity_changed":
            data = event.get("data", {})
            location = data.get("location")
            self.logger.info(f"LOOKING AT PROXIMITY CHANGE FOR {location} IN SCAVENGER HUNT; WANT {self._current_step.LOCATION.value}")
            
            # Only care about the current step's location
            # TODO: This doesn't work in python 3.7; update later.
            # if location in ScavengerHuntLocation and ScavengerHuntLocation(location) == self._current_step.LOCATION:
            if location == self._current_step.LOCATION.value:
                distance: Distance = data.get("distance")
                prev_distance: Distance = data.get("previous_distance")
                self.logger.info(f"GOT DISTANCE {distance} FOR CURRENT LOCATION: {self._current_step.LOCATION.value}")
                self.logger.info(f"WENT FROM {prev_distance} -> {distance}!")
                
                # Mark that we've detected the next step's location at least once
                if not self._current_location_detected and distance != Distance.UNKNOWN:
                    self._current_location_detected = True
                    self.logger.info(f"Location {self._current_step.LOCATION.value} detected for the first time!")
                
                # If we've just lost the signal, say something and stop.
                if distance == Distance.UNKNOWN:
                    if prev_distance and prev_distance != Distance.UNKNOWN:
                        self.logger.info("Signal lost for current step.")
                        await self.publish({
                            "type": "speak_audio",
                            "text": random.choice(self._lost_signal_phrases)
                        })
                    return

                # If we've found current location, either transition to next step or declare victory.
                if distance == Distance.IMMEDIATE:
                    await self.publish({
                        "type": "scavenger_hunt_step_completed"
                    })
                    self.logger.info("Scavenger hunt step {self._current_step_name} completed!")

                    if self._remaining_steps:
                        await self._transition_to_next_step()
                    else:
                        await self.publish({
                            "type": "scavenger_hunt_won"
                        })
                        self.logger.info("Scavenger hunt won!")
                        self._game_active = False

                # Handle transitions between distances
                elif prev_distance:
                    text_to_speak = None
                    # Case 1: First detection (transition from UNKNOWN)
                    if prev_distance == Distance.UNKNOWN:
                        self.logger.info(f"First detection for current step. Distance: {distance}")
                        if distance in self._initial_detection_phrases:
                            text_to_speak = random.choice(self._initial_detection_phrases[distance])
                    # Case 2: Getting closer
                    elif distance < prev_distance:
                        self.logger.info(f"Getting closer to current step: {prev_distance} -> {distance}")
                        if distance in self._getting_closer_phrases:
                            text_to_speak = random.choice(self._getting_closer_phrases[distance])
                    # Case 3: Getting farther
                    elif distance > prev_distance:
                        self.logger.info(f"Getting farther from current step: {prev_distance} -> {distance}")
                        if distance in self._getting_farther_phrases:
                            text_to_speak = random.choice(self._getting_farther_phrases[distance])
                    # Case 4: Distance is the same (standing still)
                    else:
                        self.logger.info(f"Distance unchanged for current step: {distance}")
                        pass  # TODO: Perhaps increment some tracker to say we're standing still?

                    if text_to_speak:
                        await self.publish({
                            "type": "speak_audio",
                            "text": text_to_speak
                        })