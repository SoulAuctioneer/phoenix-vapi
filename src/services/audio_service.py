import logging
import random
from typing import Dict, Any
import asyncio
from config import AudioBaseConfig, SoundEffect
from services.service import BaseService
from managers.audio_manager import AudioManager, AudioConfig

class AudioService(BaseService):
    """Service to manage the AudioManager lifecycle, with improved CPU efficiency"""
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
            
            # Preload commonly used sound effects in the background
            # This reduces latency when playing sounds during operation
            self.audio_manager.preload_sound_effects()
            
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
            
            if not self.audio_manager:
                self.logger.error(f"Cannot play sound '{effect_name}': audio manager not initialized")
                return
                
            if effect_name.lower() == "purr" and loop:
                self._purring_active = True
                
            if volume is not None:
                # Set volume for this sound effect
                self.audio_manager.set_producer_volume("sound_effect", volume)
                
            self.logger.info(f"Playing sound effect: {effect_name}, loop={loop}")
            success = self.audio_manager.play_sound(effect_name, loop=loop)
            
            if not success:
                self.logger.warning(f"Failed to play sound effect: {effect_name}")
                
        elif event_type == "stop_sound":
            effect_name = event.get("effect_name")
            
            if not self.audio_manager:
                self.logger.error(f"Cannot stop sound '{effect_name}': audio manager not initialized")
                return
                
            self.logger.info(f"Stopping sound effect: {effect_name}")
            
            if effect_name.lower() == "purr":
                self._purring_active = False
                
            self.audio_manager.stop_sound(effect_name)
            
        elif event_type == "set_sound_volume":
            producer_name = event.get("producer_name", "sound_effect")
            volume = event.get("volume", 0.5)
            
            if not self.audio_manager:
                self.logger.error(f"Cannot set volume for '{producer_name}': audio manager not initialized")
                return
                
            self.logger.info(f"Setting volume for {producer_name} to {volume}")
            self.audio_manager.set_producer_volume(producer_name, volume)
            
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
            if intent != "wake_up":
                await self._play_random_chirp()
                
        elif event_type == "touch_stroke_intensity":
            # Handle purring sound based on touch intensity
            # Only handle if we're not in a conversation
            if self.global_state.conversation_active:
                return
                
            intensity = event.get("intensity", 0.0)
            if intensity > 0:
                # Start or adjust purring based on intensity
                if not self._purring_active:
                    # Start purring with looping
                    await self.publish({
                        "type": "play_sound",
                        "effect_name": "purr",
                        "loop": True,
                        "volume": min(0.1 + intensity * 0.9, 1.0)  # Scale volume with intensity
                    })
                else:
                    # Just adjust volume
                    await self.publish({
                        "type": "set_sound_volume",
                        "producer_name": "sound_effect", 
                        "volume": min(0.1 + intensity * 0.9, 1.0)
                    })
            elif self._purring_active:
                # Stop purring if intensity dropped to 0
                await self.publish({
                    "type": "stop_sound",
                    "effect_name": "purr"
                })

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
            # Start playing the sound using the dedicated audio thread pool
            # This avoids creating new threads for each sound effect
            event_loop = asyncio.get_event_loop()
            success = await event_loop.run_in_executor(
                self.audio_manager._audio_thread_pool,  # Use dedicated thread pool
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
