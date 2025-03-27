import logging
import random
from typing import Dict, Any
import asyncio
from config import AudioBaseConfig, SoundEffect
from services.service import BaseService
from managers.audio_manager import AudioManager, AudioConfig

class AudioService(BaseService):
    """Service to manage the AudioManager lifecycle"""
    def __init__(self, service_manager):
        super().__init__(service_manager)
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
        
        # Handle sound control requests
        if event_type == "play_sound":
            effect_name = event.get("effect_name")
            loop = event.get("loop", False)  # Get loop parameter with default False
            volume = event.get("volume", None)  # Allow specifying custom volume
            await self._play_sound(effect_name, loop=loop, volume=volume)
        elif event_type == "stop_sound":
            effect_name = event.get("effect_name")  # For logging purposes
            self.audio_manager.stop_sound(effect_name)
            self.logger.info(f"Stopped sound effect: {effect_name}")
        
        # Play acknowledgment sound when conversation starts
        elif event_type == "conversation_starting":
            await self._play_sound("YAWN2")
                
        # Play yawn sound when conversation ends
        elif event_type == "conversation_ended":
            await self._play_sound("YAWN")

        # Play a random chirp sound when wakeword is detected
        elif event_type == "intent_detection_started":
            await self._play_random_chirp()

        elif event_type == "intent_detected":
            intent = event.get("intent")
            # TODO: Have a different chirp for each intent
            if intent != "conversation":
                await self._play_random_chirp()

        # Handle touch stroke intensity for purring sound
        elif event_type == "touch_stroke_intensity":
            # Only trigger purring if we're not in a conversation
            if not self.global_state.conversation_active:
                intensity = event.get('intensity', 0.0)
                if intensity > 0:
                    # Linear mapping from intensity to volume (0.001-0.5)
                    # Start very quiet and increase linearly to max volume
                    min_volume = 0.001   # Start nearly silent (0.1%)
                    max_volume = 0.5     # Maximum volume (50%)
                    volume = min_volume + (intensity * (max_volume - min_volume))
                    
                    # Start or update purring sound with new volume
                    self.logger.info(f"Starting or updating purring sound with volume {volume:.3f} based on intensity {intensity:.2f}")
                    
                    # Set volume and play/update sound
                    if not self._purring_active:
                        self._purring_active = True
                        await self._play_sound("PURRING", loop=True, volume=volume)
                    else:
                        self.audio_manager.set_producer_volume("sound_effect", volume)
                else:
                    # When intensity drops to 0, stop the purring sound
                    self._purring_active = False
                    self.logger.info("Touch intensity ended, stopping purring sound")
                    self.audio_manager.stop_sound("PURRING")

    async def _play_sound(self, effect_name: str, loop: bool = False, volume: float = None) -> bool:
        """Helper method to play a sound effect with error handling
        Args:
            effect_name: Name of the sound effect to play
            loop: Whether to loop the sound effect (default: False)
            volume: Optional specific volume to use (default: None, uses default volume)
        Returns:
            bool: True if sound played successfully, False otherwise
        """
        if not self.audio_manager:
            self.logger.warning("Cannot play sound - audio manager not initialized")
            return False
            
        try:
            # Start playing the sound first
            event_loop = asyncio.get_event_loop()
            success = await event_loop.run_in_executor(
                None,
                self.audio_manager.play_sound,
                effect_name,
                loop
            )
            
            if not success:
                self.logger.error(f"Failed to play sound effect: {effect_name}")
                return False

            # Now set the volume after the producer has been created
            with self.audio_manager._producers_lock:
                has_active_call = "daily_call" in self.audio_manager._producers and self.audio_manager._producers["daily_call"].active
            
            # Use provided volume if specified, otherwise use default logic
            if volume is not None:
                self.audio_manager.set_producer_volume("sound_effect", volume)
            elif has_active_call:
                self.logger.info("Active call detected, setting sound effect volume to 0.1")
                self.audio_manager.set_producer_volume("sound_effect", 0.1)
            else:
                self.audio_manager.set_producer_volume("sound_effect", AudioBaseConfig.DEFAULT_VOLUME)

            return True
            
        except Exception as e:
            self.logger.error(f"Error playing sound effect {effect_name}: {e}")
            return False
        
    async def _play_random_chirp(self):
        """Play a random chirp sound"""
        chirp_sounds = [SoundEffect.CHIRP1, SoundEffect.CHIRP2, SoundEffect.CHIRP3, SoundEffect.CHIRP4, SoundEffect.CHIRP5, SoundEffect.CHIRP6, SoundEffect.CHIRP7, SoundEffect.CHIRP8]
        random_chirp = random.choice(chirp_sounds)
        await self._play_sound(random_chirp)
