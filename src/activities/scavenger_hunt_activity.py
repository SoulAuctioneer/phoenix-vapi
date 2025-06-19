"""
Service for managing the scavenger hunt game activity.
TODO: Description. 
"""

import logging
import asyncio
import random
import time
import re
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
        self._last_spoken_time: float = time.time()
        self._speech_events: Dict[str, asyncio.Event] = {}
        self._victory_in_progress: bool = False
        if not self._remaining_steps:
            self.logger.error("Created a scavenger hunt with no steps!")
        
        # Phrases for when the beacon is first detected
        self._initial_detection_phrases: Dict[Distance, list[str]] = {
            Distance.VERY_FAR: [
                "Ooh, I've started sensing something, but it's really, really far away!",
                "Ooh, I've started feeling a faint wiggle... I think we're on the right path, but it's a long way to go!"
            ],
            Distance.FAR: [
                "Okay! I can feel it now, but it's still pretty far.",
                "Ooh I can feel it! It's far away, but it's definitely there. Let's keep looking!"
            ],
            Distance.NEAR: [
                "Ooh, I can sense it and its energy is quite strong! We must be close.",
                "Yay! I'm feeling the wiggles and it's quite strong, it must be nearby!"
            ],
            Distance.VERY_NEAR: [
                "Wow, I can feel it and it's really really close! My lights are practically dancing!",
                "Yay, I can sense it and it's super close! I'm buzzing with excitement! It's just up ahead!"
            ]
        }

        # Phrases for getting closer to the beacon
        self._getting_closer_phrases: Dict[Distance, list[str]] = {
            Distance.VERY_FAR: [
                "Ooh, we're getting closer! It's still far away, but we're getting there.",
                "Ooh, I think we're on the right path! It's a long way to go, bur we're closer! Keep going!"
            ],
            Distance.FAR: [
                "Yes, that's it! We're getting closer! The wiggles are getting stronger!",
                "We're getting warmer! Keep going this way!"
            ],
            Distance.NEAR: [
                "We're getting so warm! It must be just around the corner!",
                "Oh, this is definitely the right way. I can feel it getting stronger!"
            ],
            Distance.VERY_NEAR: [
                "Yay we're really close now, it's right here! I can almost touch it! My whole body is buzzing!",
                "Oh hurrah! We're so, so close now! Don't stop now!"
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
            ],
            Distance.UNKNOWN: [
                "Oh dear, I've lost the signal completely. Where did it go?",
                "The trail went completely cold. Let's retrace our steps and find it again."
            ]
        }
        
        # Phrases for when the signal is lost
        self._lost_signal_phrases: list[str] = [
            "Oh dear, I've lost the signal. Where did it go?",
            "Hmm, I can't feel it anymore. It must be hiding from us!",
            "The trail went cold. Let's retrace our steps."
        ]
        
        # Phrases for inactivity hints
        self._inactivity_hint_phrases: Dict[Distance, list[str]] = {
            Distance.UNKNOWN: [
                "I can't sense the {objective} at all. Let's try moving around a bit.",
                "Where could the {objective} be? I'm not picking up any signal.",
                "Hmm, I don't feel any wiggles from the {objective}. Let's try a new spot.",
                "The {objective} is hiding well! I can't feel it from here."
            ],
            Distance.VERY_FAR: [
                "We're still very far away from the {objective}. Keep looking!",
                "The {objective} is out there somewhere, but it feels like a long way off.",
                "My senses are just barely tingling. The {objective} is super far away.",
                "It's a long journey to the {objective}, but I know we can find it!"
            ],
            Distance.FAR: [
                "I can still sense the {objective}, but we're not very close. Let's keep exploring.",
                "We're on the right track for the {objective}, but it's still a ways to go.",
                "The signal from the {objective} is steady, but we have more ground to cover.",
                "Keep going! We're making progress toward the {objective}, but there's still a distance to go."
            ],
            Distance.NEAR: [
                "We're getting so close to the {objective}! It must be just around here somewhere.",
                "The feeling is stronger... the {objective} is nearby!",
                "The {objective} is calling to us! I can feel its energy buzzing nearby.",
                "I'm getting excited! The {objective} feels like it's just a hop, skip, and a jump away."
            ],
            Distance.VERY_NEAR: [
                "It's right here! The {objective} is so close I can almost feel the fizzing!",
                "My lights are tingling! We must be right on top of the {objective}!",
                "I can almost taste the sparkly energy of the {objective}! It's right here!",
                "Any second now! The {objective} is so close, my lights are going crazy!"
            ]
        }

    async def start(self):
        """Start the scavenger hunt service"""
        await super().start()
        self._game_active = True
        # Disable any LED effects
        await self.publish({
            "type": "stop_led_effect"
        })
        await self.publish({
            "type": "start_led_effect",
            "data": {
                "effect_name": "ROTATING_BEACON",
                "color": "yellow",
                "speed": ScavengerHuntConfig.BEACON_SEARCH_SPEED
            }
        })
        
        # Generate and speak the intro line
        all_objectives = [step.LOCATION.objective_name for step in ScavengerHuntConfig.SCAVENGER_HUNT_STEPS]
        if len(all_objectives) > 1:
            # Format as "the A, the B, and the C"
            objectives_list_str = ", the ".join(all_objectives[:-1])
            objectives_list_str = f"the {objectives_list_str}, and the {all_objectives[-1]}"
        elif len(all_objectives) == 1:
            objectives_list_str = f"the {all_objectives[0]}"
        else:
            objectives_list_str = "all the missing parts" # Fallback

        intro_text = (
            f"Yay! My tummy light will spin faster the closer we get to a missing part. We need to find {objectives_list_str}. ... Let's go!"
        )
        await self._speak_and_update_timer(intro_text)
        await asyncio.sleep(15) # Give a moment for the long intro to finish.
        
        # Start the first step in our hunt.
        await self._start_next_step()
        # Start hint task that periodically gives hints if there's no activity
        if ScavengerHuntConfig.PROVIDE_INTERMEDIATE_HINTS:
            self._sound_task = asyncio.create_task(self._hint_loop())
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
        
        await self.publish({
            "type": "stop_led_effect",
            "data": { "effect_name": "ROTATING_BEACON" }
        })
        
        await super().stop()
        self.logger.info("scavenger hunt service stopped")
        
    async def _speak_and_update_timer(self, text: str):
        """Helper to speak and reset the inactivity timer."""
        await self.publish({
            "type": "speak_audio",
            "text": text
        })
        self._last_spoken_time = time.time()

    async def _start_next_step(self):
        if not self._remaining_steps:
            self.logger.error("Trying to start next step when none remain!")
        self._current_step = self._remaining_steps.pop(0)
        self._current_location_detected = False
        await self._speak_and_update_timer(random.choice(self._current_step.START_VOICE_LINES))
        
    @property
    def _current_step_name(self) -> str:
        return self._current_step.NAME
        
    @property
    def _current_objective_name(self) -> str:
        """Extracts the 'pretty' name of the objective from the current step's location."""
        if self._current_step:
            return self._current_step.LOCATION.objective_name
        return ""

    async def _hint_loop(self):
        """Main loop that periodically gives hints if there's been no speech for a while."""
        while self._game_active:
            try:
                await asyncio.sleep(1.0)  # Check every second

                if self._current_step and (time.time() - self._last_spoken_time > ScavengerHuntConfig.INACTIVITY_HINT_INTERVAL):
                    self.logger.info("Inactivity detected, providing a hint.")
                    
                    # Get current distance to the beacon
                    distance = Distance.UNKNOWN
                    async with self.global_state_lock:
                        location_info = self.global_state.location_beacons.get(self._current_step.LOCATION.beacon_id, {})
                        distance = location_info.get("distance", Distance.UNKNOWN)

                    # Get and format the hint phrase
                    if distance in self._inactivity_hint_phrases:
                        phrase_template = random.choice(self._inactivity_hint_phrases[distance])
                        text_to_speak = phrase_template.format(objective=self._current_objective_name)
                        await self._speak_and_update_timer(text_to_speak)
                    
            except Exception as e:
                self.logger.error(f"Error in hint loop: {e}")
                await asyncio.sleep(1.0)  # Wait a bit before retrying
                
    async def _handle_victory(self):
        """Handle the victory sequence when the scavenger hunt is won."""
        if self._victory_in_progress:
            self.logger.debug("Victory sequence already in progress, ignoring.")
            return
        self._victory_in_progress = True
        self.logger.info("Scavenger hunt won! Starting victory sequence.")
        self._game_active = False # Stop hint loop and other background processes
        
        # Stop any ongoing hint speech
        await self.publish({
            "type": "stop_sound",
            "effect_name": "elevenlabs_tts"
        })
        # Stop the beacon
        await self.publish({
            "type": "stop_led_effect",
            "data": { "effect_name": "ROTATING_BEACON" }
        })

        # Start a celebratory LED effect
        await self.publish({
            "type": "start_led_effect",
            "data": {
                "effect_name": "MAGICAL_SPELL",
                "speed": 0.03
            }
        })
        
        # Victory speech
        victory_text = (
            "We did it! We found all the pieces! Hooray! "
            "Now we can fix the transmitter and call Grandmother Pea on the Mothership! "
            "You're the best! Thank you so much for helping us! Now I can have a nice relaxing nap!"
        )
        await self._speak_and_update_timer(victory_text)
        
        # Let the effect and speech play out
        await asyncio.sleep(18)
        
        # Formally publish the win event to be handled by the activity service
        # We create a task here to avoid a deadlock where this service awaits
        # its own destruction by the activity_service.
        asyncio.create_task(self.publish({
            "type": "scavenger_hunt_won"
        }))

    async def _transition_to_next_step(self):
        await self._speak_and_update_timer(random.choice(self._current_step.END_VOICE_LINES))
        await self.publish({
            "type": "start_led_effect",
            "data": {
                "effect_name": "ROTATING_BEACON",
                "color": "yellow",
                "speed": ScavengerHuntConfig.BEACON_SEARCH_SPEED
            }
        })
        await asyncio.sleep(ScavengerHuntConfig.INTER_STEP_SLEEP_TIME)
        await self._start_next_step()
    
    async def handle_event(self, event: Dict[str, Any]):
        """Handle events from other services"""
        event_type = event.get("type")

        if event_type == "speech_finished":
            key = event.get("key")
            if key and key in self._speech_events:
                self._speech_events[key].set()
                del self._speech_events[key]

        if event_type == "proximity_changed":
            if self._victory_in_progress:
                self.logger.debug("Ignoring proximity event during victory sequence.")
                return
            data = event.get("data", {})
            location = data.get("location")
            self.logger.info(f"LOOKING AT PROXIMITY CHANGE FOR {location} IN SCAVENGER HUNT; WANT {self._current_step.LOCATION.beacon_id}")
            
            # Only care about the current step's location
            if location == self._current_step.LOCATION.beacon_id:
                distance: Distance = data.get("distance")
                prev_distance: Distance = data.get("previous_distance")
                smoothed_rssi = data.get("smoothed_rssi")
                self.logger.info(f"GOT DISTANCE {distance} FOR CURRENT LOCATION: {self._current_step.LOCATION.objective_name}")
                self.logger.info(f"WENT FROM {prev_distance} -> {distance}!")
                
                # Mark that we've detected the next step's location at least once
                if not self._current_location_detected and distance != Distance.UNKNOWN:
                    self._current_location_detected = True
                    self.logger.info(f"Location {self._current_step.LOCATION.objective_name} detected for the first time!")
                
                # Update beacon speed on every valid signal update.
                if smoothed_rssi is not None and distance != Distance.UNKNOWN:
                    # Unpack config values for interpolation
                    min_rssi = ScavengerHuntConfig.BEACON_RSSI_SPEED_MAPPING["min_rssi"]
                    max_rssi = ScavengerHuntConfig.BEACON_RSSI_SPEED_MAPPING["max_rssi"]
                    min_speed = ScavengerHuntConfig.BEACON_RSSI_SPEED_MAPPING["min_speed"]
                    max_speed = ScavengerHuntConfig.BEACON_RSSI_SPEED_MAPPING["max_speed"]

                    # Clamp the RSSI value to the defined range
                    clamped_rssi = max(min_rssi, min(max_rssi, smoothed_rssi))

                    # Perform linear interpolation
                    rssi_range = max_rssi - min_rssi
                    speed_range = max_speed - min_speed
                    
                    if rssi_range == 0:
                        speed_to_set = min_speed
                    else:
                        # Invert the speed mapping because lower speed value means faster rotation
                        percent = (clamped_rssi - min_rssi) / rssi_range
                        speed_to_set = max_speed - (percent * speed_range)
                    
                    self.logger.debug(f"Updating beacon speed to {speed_to_set:.3f} based on smoothed RSSI {smoothed_rssi}")

                    await self.publish({
                        "type": "start_or_update_effect",
                        "data": {
                            "effect_name": "ROTATING_BEACON",
                            "color": "yellow",
                            "speed": speed_to_set
                        }
                    })

                # If we've just lost the signal, say something and stop.
                if distance == Distance.UNKNOWN:
                    if prev_distance and prev_distance != Distance.UNKNOWN:
                        self.logger.info("Signal lost for current step.")
                        await self._speak_and_update_timer(random.choice(self._lost_signal_phrases))
                        await self.publish({
                            "type": "start_or_update_effect",
                            "data": {
                                "effect_name": "ROTATING_BEACON",
                                "color": "yellow",
                                "speed": ScavengerHuntConfig.BEACON_LOST_SPEED
                            }
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
                        await self._handle_victory()
                    return # Exit after handling immediate distance

                # Handle speech cues based on discrete distance *transitions*.
                if prev_distance and distance != prev_distance:
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
                    
                    if text_to_speak:
                        await self._speak_and_update_timer(text_to_speak)