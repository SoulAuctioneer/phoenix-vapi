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
from config import ScavengerHuntConfig, ScavengerHuntLocation, Distance, SoundEffect
from dataclasses import dataclass

@dataclass
class ScavengerHuntStep:
    location: ScavengerHuntLocation

class ScavengerHuntActivity(BaseService):
    """Service that manages the scavenger hunt game activity"""
    
    def __init__(self, service_manager):
        super().__init__(service_manager)
        self._sound_task: Optional[asyncio.Task] = None
        self._game_active: bool = False
        self._current_step: ScavengerHuntStep | None = None
        self._current_location_detected: bool = False  # Track if we've ever seen the next desired location.
        self._current_distance: Distance = Distance.UNKNOWN
        self._remaining_steps: list[ScavengerHuntStep] = []
        self._all_hunt_steps: list[ScavengerHuntStep] = []
        self._last_spoken_time: float = time.time()
        self._speech_events: Dict[str, asyncio.Event] = {}
        self._victory_in_progress: bool = False
        self._step_transition_in_progress: bool = False
        if not self._remaining_steps:
            self.logger.error("Created a scavenger hunt with no steps!")
        
    async def start(self, hunt_variant: str = "HUNT_ALPHA"):
        """Start the scavenger hunt service"""
        await super().start()
        hunt_locations = getattr(ScavengerHuntConfig, hunt_variant, ScavengerHuntConfig.HUNT_ALPHA)
        self._game_active = True
        self._all_hunt_steps = [ScavengerHuntStep(location=loc) for loc in hunt_locations]
        self._remaining_steps = list(self._all_hunt_steps)

        if not self._all_hunt_steps:
            self.logger.error("Scavenger hunt started with no locations!")
            asyncio.create_task(self.publish({"type": "scavenger_hunt_won"})) # End silently
            return

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
        all_objectives = [step.location.objective_name for step in self._all_hunt_steps]
        if len(all_objectives) > 2:
            # Format as "the A, the B, and the C"
            objectives_list_str = ", the ".join(all_objectives[:-1])
            objectives_list_str = f"the {objectives_list_str}, and the {all_objectives[-1]}"
        elif len(all_objectives) == 2:
            objectives_list_str = f"the {all_objectives[0]} and the {all_objectives[1]}"
        elif len(all_objectives) == 1:
            objectives_list_str = f"the {all_objectives[0]}"
        else:
            objectives_list_str = ScavengerHuntConfig.INTRO_FALLBACK_OBJECTIVES # Fallback

        intro_text = ScavengerHuntConfig.INTRO_TEXT_TEMPLATE.format(objectives_list_str=objectives_list_str)
        await self._speak_and_update_timer(intro_text, wait_for_completion=True)

        await asyncio.sleep(2.0)  # Check every second
        
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
        
        await super().stop()
        self.logger.info("scavenger hunt service stopped")
        
    async def _speak_and_update_timer(self, text: str, wait_for_completion: bool = False):
        """Helper to speak and reset the inactivity timer."""
        finish_event = None
        if wait_for_completion:
            finish_event = asyncio.Event()
            
        await self.publish({
            "type": "speak_audio",
            "text": text,
            "on_finish_event": finish_event
        })
        self._last_spoken_time = time.time()
        
        if finish_event:
            try:
                await finish_event.wait()
            except asyncio.CancelledError:
                self.logger.info("Wait for speech completion cancelled.")

    async def _start_next_step(self):
        if not self._remaining_steps:
            self.logger.error("Trying to start next step when none remain!")
        self._current_step = self._remaining_steps.pop(0)
        self._current_location_detected = False
        self._current_distance = Distance.UNKNOWN
        
        step_data = ScavengerHuntConfig.LOCATION_DATA.get(self._current_step.location)
        if step_data:
            await self._speak_and_update_timer(random.choice(step_data.start_voice_lines))
        else:
            self.logger.warning(f"No start voice line found for location: {self._current_step.location.name}")

        self._step_transition_in_progress = False  # Reset for the new step

    @property
    def _current_step_name(self) -> str:
        return self._current_step.location.name if self._current_step else ""
        
    @property
    def _current_objective_name(self) -> str:
        """Extracts the 'pretty' name of the objective from the current step's location."""
        if self._current_step:
            return self._current_step.location.objective_name
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
                        location_info = self.global_state.location_beacons.get(self._current_step.location.beacon_id, {})
                        distance = location_info.get("distance", Distance.UNKNOWN)

                    # Get and format the hint phrase
                    if distance in ScavengerHuntConfig.INACTIVITY_HINT_PHRASES:
                        phrase_template = random.choice(ScavengerHuntConfig.INACTIVITY_HINT_PHRASES[distance])
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
        
        # Start a celebratory LED effect
        await self.publish({
            "type": "start_led_effect",
            "data": {
                "effect_name": "MAGICAL_SPELL",
                "speed": 0.03
            }
        })
        
        # Victory speech
        victory_text = ScavengerHuntConfig.VICTORY_TEXT
        await self._speak_and_update_timer(victory_text, wait_for_completion=True)
        
        # Let the effect and speech play out
        await asyncio.sleep(2) # Give a moment for the effect to be seen after speech
        
        # Formally publish the win event to be handled by the activity service
        # We create a task here to avoid a deadlock where this service awaits
        # its own destruction by the activity_service.
        asyncio.create_task(self.publish({
            "type": "scavenger_hunt_won"
        }))

    async def _transition_to_next_step(self):
        step_data = ScavengerHuntConfig.LOCATION_DATA.get(self._current_step.location)
        if step_data:
            await self._speak_and_update_timer(random.choice(step_data.end_voice_lines), wait_for_completion=True)
        else:
            self.logger.warning(f"No end voice line found for location: {self._current_step.location.name}")
            
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
    
    async def _complete_current_step(self):
        """Helper to manage the logic for completing a step to avoid race conditions."""
        if self._step_transition_in_progress:
            self.logger.debug("Step transition already in progress, ignoring.")
            return
        self._step_transition_in_progress = True

        self.logger.info(f"Scavenger hunt step {self._current_step_name} completed!")
        await self.publish({"type": "scavenger_hunt_step_completed"})

        if self._remaining_steps:
            await self._transition_to_next_step()
        else:
            await self._handle_victory()

    async def _handle_beacon_update(self, beacon_id: str, distance: Distance, smoothed_rssi: Optional[float], prev_distance: Distance):
        """Unified handler for processing updates for the current target beacon."""
        self.logger.info(f"GOT DISTANCE {distance} FOR CURRENT LOCATION: {self._current_objective_name}")
        self.logger.info(f"WENT FROM {prev_distance} -> {distance}!")
        
        # Mark that we've detected the next step's location at least once
        if not self._current_location_detected and distance != Distance.UNKNOWN:
            self._current_location_detected = True
            self.logger.info(f"Location {self._current_objective_name} detected for the first time!")
        
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
                await self._speak_and_update_timer(random.choice(ScavengerHuntConfig.LOST_SIGNAL_PHRASES))
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
            await self._complete_current_step()
            return # Exit after handling immediate distance

        # Handle speech cues based on discrete distance *transitions*.
        if prev_distance and distance != prev_distance:
            text_to_speak = None
            # Case 1: First detection (transition from UNKNOWN)
            if prev_distance == Distance.UNKNOWN:
                self.logger.info(f"First detection for current step. Distance: {distance}")
                if distance in ScavengerHuntConfig.INITIAL_DETECTION_PHRASES:
                    text_to_speak = random.choice(ScavengerHuntConfig.INITIAL_DETECTION_PHRASES[distance])
            # Case 2: Getting closer
            elif distance < prev_distance:
                self.logger.info(f"Getting closer to current step: {prev_distance} -> {distance}")
                if distance in ScavengerHuntConfig.GETTING_CLOSER_PHRASES:
                    text_to_speak = random.choice(ScavengerHuntConfig.GETTING_CLOSER_PHRASES[distance])
            # Case 3: Getting farther
            elif distance > prev_distance:
                self.logger.info(f"Getting farther from current step: {prev_distance} -> {distance}")
                if distance in ScavengerHuntConfig.GETTING_FARTHER_PHRASES:
                    text_to_speak = random.choice(ScavengerHuntConfig.GETTING_FARTHER_PHRASES[distance])
            
            if text_to_speak:
                await self._speak_and_update_timer(text_to_speak)

    async def handle_event(self, event: Dict[str, Any]):
        """Handle events from other services"""
        event_type = event.get("type")

        if event_type == "all_beacons_update" or event_type == "proximity_changed":
            if self._victory_in_progress or not self._current_step or self._step_transition_in_progress:
                return

            current_beacon_id = self._current_step.location.beacon_id
            beacon_data_to_process = None
            provided_prev_distance = None

            if event_type == "proximity_changed":
                data = event.get("data", {})
                if data.get("location") == current_beacon_id:
                    self.logger.info(f"Processing proximity_changed for {current_beacon_id}")
                    beacon_data_to_process = data
                    provided_prev_distance = data.get("previous_distance")

            elif event_type == "all_beacons_update":
                beacons = event.get("data", {}).get("beacons", {})
                if current_beacon_id in beacons:
                    self.logger.info(f"Processing all_beacons_update for {current_beacon_id}")
                    beacon_data_to_process = beacons[current_beacon_id]

            if beacon_data_to_process:
                distance = beacon_data_to_process.get("distance", Distance.UNKNOWN)
                smoothed_rssi = beacon_data_to_process.get("smoothed_rssi")
                
                # If the event provides a previous_distance, use it. Otherwise, use our internally tracked one.
                prev_distance_to_use = provided_prev_distance if provided_prev_distance is not None else self._current_distance

                await self._handle_beacon_update(
                    beacon_id=current_beacon_id,
                    distance=distance,
                    smoothed_rssi=smoothed_rssi,
                    prev_distance=prev_distance_to_use
                )
                
                # Update our internally tracked distance
                if distance != Distance.UNKNOWN:
                    self._current_distance = distance