import logging
from typing import Dict, Any
import asyncio
from config import AudioBaseConfig
from services.service import BaseService
from managers.audio_manager import AudioManager, AudioConfig

class AudioService(BaseService):
    """Service to manage the AudioManager lifecycle"""
    def __init__(self, manager):
        super().__init__(manager)
        self.audio_manager = None
        self._purring_active = False  # Track if purring sound is currently active
        
    async def start(self):
        """Start the audio service"""
        await super().start()
        
        try:
            # Initialize audio manager with default config
            config = AudioConfig()
            self.audio_manager = AudioManager.get_instance(config)
            self.audio_manager.start()
            self.logger.info("Audio service started successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to start audio service: {e}")
            raise
            
    async def stop(self):
        """Stop the audio service"""
        if self.audio_manager:
            try:
                self.audio_manager.stop()
                self.logger.info("Audio service stopped successfully")
            except Exception as e:
                self.logger.error(f"Error stopping audio service: {e}")
                
        await super().stop()

    async def handle_event(self, event: Dict[str, Any]):
        """Handle events from other services"""
        event_type = event.get("type")
        
        # Handle direct play_sound requests
        if event_type == "play_sound":
            effect_name = event.get("effect_name")
            await self._play_sound(effect_name)
        
        # Play tadaaa when application starts up
        # Turned off for now, getting annoying
        # elif event_type == "application_startup_completed":
            # await self._play_sound("TADA")
                
        # Play acknowledgment sound when conversation starts
        elif event_type == "conversation_starting":
            await self._play_sound("YAWN")
                
        # Play yawn sound when conversation ends
        elif event_type == "conversation_ended":
            await self._play_sound("YAWN") 

        # Handle touch stroke intensity for purring sound
        elif event_type == "touch_stroke_intensity":
            # Only trigger purring if we're not in a conversation
            if not self.global_state.conversation_active:
                intensity = event.get('intensity', 0.0)
                if intensity > 0:
                    # Map intensity (0-1) to volume (0.0-0.3) with exponential scaling
                    # This makes it much quieter at low intensities
                    min_volume = 0.0    # Minimum volume
                    max_volume = 0.5    # Maximum volume
                    # Apply exponential scaling (x^2) to make low intensities even quieter
                    scaled_intensity = intensity * intensity  
                    volume = min_volume + (scaled_intensity * (max_volume - min_volume))
                    
                    # Start or update purring sound with new volume
                    self.logger.info(f"Starting or updating purring sound with volume {volume:.3f} based on intensity {intensity:.2f} (scaled: {scaled_intensity:.3f})")
                    
                    # Set volume before starting sound if not already purring
                    self.audio_manager.set_producer_volume("sound_effect", volume)
                    if not self._purring_active:
                        self._purring_active = True
                        # Ensure volume is set before playing
                        await asyncio.sleep(0.1)  # Small delay to ensure volume takes effect
                        await self._play_sound("PURRING")
                else:
                    # When intensity drops to 0, stop the purring sound
                    self._purring_active = False
                    self.logger.info("Touch intensity ended, stopping purring sound")
                    self.audio_manager.stop_sound()

    async def _play_sound(self, effect_name: str) -> bool:
        """Helper method to play a sound effect with error handling
        Args:
            effect_name: Name of the sound effect to play
        Returns:
            bool: True if sound played successfully, False otherwise
        """
        if not self.audio_manager:
            self.logger.warning("Cannot play sound - audio manager not initialized")
            return False
            
        try:
            # Set sound effect volume to half if there's an active call
            with self.audio_manager._producers_lock:
                has_active_call = "daily_call" in self.audio_manager._producers and self.audio_manager._producers["daily_call"].active
            if has_active_call:
                self.logger.info("Active call detected, setting sound effect volume to 0.1")
                self.audio_manager.set_producer_volume("sound_effect", 0.1)
            else:
                self.audio_manager.set_producer_volume("sound_effect", AudioBaseConfig.DEFAULT_VOLUME)
                
            loop = asyncio.get_event_loop()
            success = await loop.run_in_executor(
                None,
                self.audio_manager.play_sound,
                effect_name
            )
            if not success:
                self.logger.error(f"Failed to play sound effect: {effect_name}")
            return success
        except Exception as e:
            self.logger.error(f"Error playing sound effect {effect_name}: {e}")
            return False
        