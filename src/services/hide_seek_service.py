"""
Service for managing the hide and seek game activity.
The Red Phoenix device is the object to be found, and the pendant beacon is worn by the player.
"""

import logging
import asyncio
import random
from typing import Dict, Any, Optional
from services.service import BaseService
from config import HideSeekConfig, Distance, SoundEffect

class HideSeekService(BaseService):
    """Service that manages the hide and seek game activity"""
    
    def __init__(self, manager):
        super().__init__(manager)
        self._sound_task: Optional[asyncio.Task] = None
        self._game_active = False
        self._pendant_found = False
        self._pendant_detected = False  # Track if we've ever seen the pendant
        
    async def start(self):
        """Start the hide and seek service"""
        await super().start()
        self._game_active = True
        # Start sound task that periodically emits chirps
        self._sound_task = asyncio.create_task(self._sound_loop())
        self.logger.info("Hide and seek service started")
        
    async def stop(self):
        """Stop the hide and seek service"""
        self._game_active = False
        if self._sound_task:
            self._sound_task.cancel()
            try:
                await self._sound_task
            except asyncio.CancelledError:
                pass
            self._sound_task = None
        await super().stop()
        self.logger.info("Hide and seek service stopped")
        
    def _calculate_volume(self, distance: Distance) -> float:
        """Calculate volume based on distance category
        
        Args:
            distance: The distance category from the pendant
            
        Returns:
            float: Volume level between 0.1 and 1.0
        """
        # Map distances to volume levels
        # Further = louder to help guide the player
        if distance == Distance.UNKNOWN:
            return 1.0  # Max volume when unknown/lost
        elif distance == Distance.VERY_FAR:
            return 0.9 * HideSeekConfig.AUDIO_CUE_DISTANCE_SCALING
        elif distance == Distance.FAR:
            return 0.7 * HideSeekConfig.AUDIO_CUE_DISTANCE_SCALING
        elif distance == Distance.NEAR:
            return 0.5 * HideSeekConfig.AUDIO_CUE_DISTANCE_SCALING
        elif distance == Distance.VERY_NEAR:
            return 0.3 * HideSeekConfig.AUDIO_CUE_DISTANCE_SCALING
        elif distance == Distance.IMMEDIATE:
            return 0.1  # Minimum volume when very close
        else:
            return 1.0  # Fallback to max volume
        
    async def _sound_loop(self):
        """Main loop that periodically emits chirp sounds based on pendant distance"""
        while self._game_active:
            try:
                # Only emit sounds if we've detected the pendant at least once
                if not self._pendant_detected:
                    await asyncio.sleep(1.0)  # Check less frequently when waiting for pendant
                    continue
                    
                # Get current pendant beacon info from global state
                pendant_info = self.global_state.location_beacons.get("pendant", {})
                if not pendant_info:
                    # No pendant detected, use max volume
                    volume = 1.0
                else:
                    # Calculate volume based on distance category
                    distance = pendant_info.get("distance", Distance.UNKNOWN)
                    volume = self._calculate_volume(distance)
                    self.logger.debug(f"Pendant distance: {distance}, calculated volume: {volume:.2f}")
                
                # Emit a random chirp sound
                await self.publish({
                    "type": "play_sound",
                    "effect_name": random.choice([
                        SoundEffect.CHIRP1,
                        SoundEffect.CHIRP2,
                        SoundEffect.CHIRP3,
                        SoundEffect.CHIRP4,
                        SoundEffect.CHIRP5
                    ]),
                    "volume": volume
                })
                
                # Wait for next interval
                await asyncio.sleep(HideSeekConfig.AUDIO_CUE_INTERVAL)
                
            except Exception as e:
                self.logger.error(f"Error in sound loop: {e}")
                await asyncio.sleep(1.0)  # Wait a bit before retrying
                
    async def handle_event(self, event: Dict[str, Any]):
        """Handle events from other services"""
        event_type = event.get("type")
        
        if event_type == "proximity_changed":
            data = event.get("data", {})
            location = data.get("location")
            
            # Only care about the pendant beacon
            if location == "pendant":
                distance = data.get("distance")
                
                # Mark that we've detected the pendant at least once
                if not self._pendant_detected and distance != Distance.UNKNOWN:
                    self._pendant_detected = True
                    self.logger.info("Pendant detected for the first time - starting hide and seek game!")
                
                # Check if pendant is found based on distance being IMMEDIATE
                is_found = distance == Distance.IMMEDIATE
                
                # If newly found, play tada sound
                if is_found and not self._pendant_found:
                    self._pendant_found = True
                    await self.publish({
                        "type": "play_sound",
                        "effect_name": SoundEffect.TADA
                    })
                    self.logger.info("Pendant found! Playing tada sound")
                elif not is_found:
                    self._pendant_found = False
