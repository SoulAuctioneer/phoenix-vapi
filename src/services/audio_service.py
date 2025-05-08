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
            # Initialize AudioManager's master volume based on GlobalState
            if self.audio_manager and self.global_state:
                self.audio_manager.set_master_volume(self.global_state.volume)
            
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

        # Play "HMM" sound when wakeword is detected
        elif event_type == "intent_detection_started":
            await self._play_sound(SoundEffect.HMM)

        # # Play a random chirp sound when wakeword is detected
        # elif event_type == "intent_detection_started":
        #     await self._play_random_chirp()

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
                        # Purring is already active, just update its relative volume
                        if self.audio_manager:
                            self.audio_manager.set_producer_volume("sound_effect", volume)
                else:
                    # When intensity drops to 0, stop the purring sound
                    if self._purring_active: # Check if it was active before stopping
                        self._purring_active = False
                        self.logger.info("Touch intensity ended, stopping purring sound")
                        if self.audio_manager:
                            self.audio_manager.stop_sound("PURRING")

        # Handle custom command for volume adjustment
        elif event_type == "intent_detected":
            intent_name = event.get("intent")
            if intent_name == "custom_command":
                slots = event.get("slots")
                if slots and "index" in slots:
                    try:
                        index_val = int(slots["index"])
                        current_volume = self.global_state.volume
                        adjustment_step = 0.1

                        if index_val == 1: # Turn volume down
                            new_volume = current_volume - adjustment_step
                            self.logger.info(f"'custom_command' intent (index 1) received. Attempting to decrease volume from {current_volume:.2f} to {new_volume:.2f}.")
                            await self.set_global_volume(new_volume)
                        elif index_val == 2: # Turn volume up
                            new_volume = current_volume + adjustment_step
                            self.logger.info(f"'custom_command' intent (index 2) received. Attempting to increase volume from {current_volume:.2f} to {new_volume:.2f}.")
                            await self.set_global_volume(new_volume)
                        else:
                            self.logger.warning(f"'custom_command' intent received with unhandled index: {index_val}")
                    except ValueError:
                        self.logger.error(f"'custom_command' intent received with non-integer index: {slots['index']}")
                    except Exception as e:
                        self.logger.error(f"Error processing 'custom_command' for volume: {e}", exc_info=True)

    async def set_global_volume(self, new_volume: float):
        clamped_volume = max(0.0, min(1.0, new_volume))
        # Access global_state via self.global_state, ensuring ServiceManager's lock handles safety
        # No need for explicit lock here as ServiceManager handles state updates sequentially for now.
        # If concurrent modification of global_state.volume becomes an issue, locking might be needed.
        if self.global_state.volume != clamped_volume:
            current_global_volume = self.global_state.volume # For logging
            self.global_state.volume = clamped_volume # Update source of truth
            if self.audio_manager:
                self.audio_manager.set_master_volume(clamped_volume) # Propagate to AudioManager
            
            await self.publish({
                "type": "volume_changed",
                "volume": clamped_volume,
                "producer_name": self.__class__.__name__ 
            })
            self.logger.info(f"Global volume changed from {current_global_volume:.2f} to {clamped_volume:.2f}")
        return clamped_volume # Return the applied volume

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
            # The 'volume' parameter now refers to the PRODUCER'S RELATIVE volume.
            # The global master volume is applied separately in AudioManager.
            if volume is not None:
                self.audio_manager.set_producer_volume("sound_effect", volume)
            elif has_active_call:
                self.logger.info(f"Active call detected, setting sound effect relative volume to {AudioBaseConfig.CONVERSATION_SFX_VOLUME}")
                self.audio_manager.set_producer_volume("sound_effect", AudioBaseConfig.CONVERSATION_SFX_VOLUME)
            else:
                # Default relative volume for sound_effect producer if no other is specified
                self.audio_manager.set_producer_volume("sound_effect", AudioBaseConfig.DEFAULT_VOLUME) # This is 1.0 by default

            return True
            
        except Exception as e:
            self.logger.error(f"Error playing sound effect {effect_name}: {e}")
            return False
        
    async def _play_random_chirp(self):
        """Play a random chirp sound"""
        chirp_sounds = [SoundEffect.CHIRP1, SoundEffect.CHIRP2, SoundEffect.CHIRP3, SoundEffect.CHIRP4, SoundEffect.CHIRP5, SoundEffect.CHIRP6, SoundEffect.CHIRP7, SoundEffect.CHIRP8]
        random_chirp = random.choice(chirp_sounds)
        await self._play_sound(random_chirp)
