import logging
import random
from typing import Dict, Any
import asyncio
from config import AudioBaseConfig, SoundEffect, AudioAmplifierConfig
from services.service import BaseService
from managers.audio_manager import AudioManager, AudioConfig
from hardware.amp_pam8302a import Amplifier

class AudioService(BaseService):
    """Service to manage the AudioManager lifecycle"""
    def __init__(self, service_manager):
        super().__init__(service_manager)
        self.audio_manager = None
        self._purring_active = False  # Track if purring sound is currently active
        self.volume_before_mute = None  # Store volume level before muting
        self.amplifier = None
        
    async def start(self):
        """Start the audio service"""
        await super().start()
        
        try:
            # Initialize the amplifier if enabled for the current platform
            if AudioAmplifierConfig.IS_AMPLIFIER_ENABLED:
                self.amplifier = Amplifier(shutdown_pin=AudioAmplifierConfig.ENABLE_PIN, initial_state='off')
                self.logger.info(f"Amplifier initialized on GPIO {AudioAmplifierConfig.ENABLE_PIN}")

            # Initialize audio manager with default config
            config = AudioConfig()
            self.audio_manager = AudioManager.get_instance(config)
            
            # Pass amplifier to audio manager for power control
            if self.amplifier:
                self.audio_manager.set_amplifier(self.amplifier)

            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self.audio_manager.start)
            self.logger.info("Audio service started successfully")
            
            # Initialize AudioManager's master volume based on GlobalState
            if self.audio_manager and self.global_state:
                self.audio_manager.set_master_volume(self.global_state.volume)
            
        except Exception as e:
            self.logger.error(f"Failed to start audio service: {e}", exc_info=True)
            raise
            
    async def stop(self):
        """Stop the audio service"""
        if self.audio_manager:
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, self.audio_manager.stop)
                self.logger.info("Audio service stopped successfully")
            except Exception as e:
                self.logger.error(f"Error stopping audio service: {e}")

        if self.amplifier:
            self.amplifier.cleanup()
                
        await super().stop()

    async def handle_event(self, event: Dict[str, Any]):
        """Handle events from other services"""
        event_type = event.get("type")
        
        # Handle sound control requests
        if event_type == "play_sound":
            effect_name = event.get("effect_name")
            loop = event.get("loop", False)  # Get loop parameter with default False
            volume = event.get("volume", None)  # Allow specifying custom volume
            on_finish_event = event.get("on_finish_event")
            await self._play_sound(effect_name, loop=loop, volume=volume, on_finish_event=on_finish_event)
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

        # Handle volume-related intents
        elif event_type == "intent_detected":
            intent_name = event.get("intent")
            
            if intent_name == "volume_down":
                await self.set_volume_down()
            elif intent_name == "volume_up":
                await self.set_volume_up()
            elif intent_name == "volume_off":
                await self.set_volume_mute()
            elif intent_name == "volume_on":
                await self.set_volume_unmute()
            elif intent_name == "volume_level":
                slots = event.get("slots")
                if slots and "level" in slots:
                    try:
                        level = int(slots["level"])
                        await self.set_volume_level(level)
                    except ValueError:
                        self.logger.error(f"'volume_level' intent received with non-integer level: {slots['level']}")
                    except Exception as e:
                        self.logger.error(f"Error processing 'volume_level' intent: {e}", exc_info=True)

    async def set_volume_down(self):
        current_volume = self.global_state.volume
        new_volume = current_volume - AudioBaseConfig.VOLUME_STEP
        volume_changed = await self.set_global_volume(new_volume)
        if volume_changed:
            await self._play_sound(SoundEffect.SQUEAK)

    async def set_volume_up(self):
        current_volume = self.global_state.volume
        new_volume = current_volume + AudioBaseConfig.VOLUME_STEP
        volume_changed = await self.set_global_volume(new_volume)
        if volume_changed:
            await self._play_sound(SoundEffect.SQUEAK)

    async def set_global_volume(self, new_volume: float) -> bool: # Returns True if volume changed
        clamped_volume = max(0.0, min(1.0, new_volume))
        volume_actually_changed = False
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
            volume_actually_changed = True
        # Optional: log if volume was not changed due to clamping or already at target
        # else:
            # if self.global_state.volume == clamped_volume: # Already at the target (e.g. trying to set to 0.5 when it's 0.5)
                # self.logger.info(f"Global volume already at {clamped_volume:.2f}. No change needed for request {new_volume:.2f}.")
            # else: # Clamped, but was already at the clamped value (e.g. trying to set to 1.1 when it's 1.0)
                # self.logger.info(f"Global volume remains at {self.global_state.volume:.2f}. Requested {new_volume:.2f} resulted in no change due to limits.")
        return volume_actually_changed

    async def set_volume_mute(self):
        """Mute the audio by setting volume to 0"""
        # Store current volume for potential unmute
        if self.volume_before_mute is None:
            self.volume_before_mute = self.global_state.volume
        
        volume_changed = await self.set_global_volume(0.0)
        if volume_changed:
            await self._play_sound(SoundEffect.SQUEAK)

    async def set_volume_unmute(self):
        """Unmute the audio by restoring previous volume"""
        if self.volume_before_mute is not None:
            previous_volume = self.volume_before_mute
            self.volume_before_mute = None  # Clear the stored volume
            volume_changed = await self.set_global_volume(previous_volume)
        else:
            # If no previous volume stored, set to a reasonable default
            volume_changed = await self.set_global_volume(0.5)
        
        if volume_changed:
            await self._play_sound(SoundEffect.SQUEAK)

    async def set_volume_level(self, level: int):
        """Set volume to a specific level (0-9, mapped to 0.0-1.0)"""
        if level < 0 or level > 9:
            self.logger.warning(f"Volume level {level} out of range (0-9), clamping")
            level = max(0, min(9, level))
        
        # Map 0-9 to 0.0-1.0
        new_volume = level / 9.0
        volume_changed = await self.set_global_volume(new_volume)
        if volume_changed:
            await self._play_sound(SoundEffect.SQUEAK)

    async def _play_sound(self, effect_name: str, loop: bool = False, volume: float = None, on_finish_event: asyncio.Event = None) -> bool:
        """Helper method to play a sound effect with error handling
        Args:
            effect_name: Name of the sound effect to play
            loop: Whether to loop the sound effect (default: False)
            volume: Optional specific volume to use (default: None, uses default volume)
            on_finish_event: An asyncio.Event to set when the sound finishes playing.
        Returns:
            bool: True if sound played successfully, False otherwise
        """
        if not self.audio_manager:
            self.logger.warning("Cannot play sound - audio manager not initialized")
            if on_finish_event:
                on_finish_event.set() # Don't block forever if audio isn't running
            return False
            
        try:
            event_loop = asyncio.get_running_loop()

            def on_finish_sync_callback(effect_name_finished):
                async def finish_actions():
                    self.logger.info(f"Sound effect '{effect_name_finished}' finished playing.")
                    # Publish the generic finish event
                    await self.publish({
                        "type": "sound_effect_finished",
                        "data": {"effect_name": effect_name_finished}
                    })
                    # Set the specific event for the caller if provided
                    if on_finish_event:
                        # This needs to be thread-safe as it's called from the audio thread
                        event_loop.call_soon_threadsafe(on_finish_event.set)

                # Schedule the async function to run on the event loop from the background thread
                event_loop.call_soon_threadsafe(asyncio.create_task, finish_actions())

            # Start playing the sound first
            success = await event_loop.run_in_executor(
                None,
                self.audio_manager.play_sound,
                effect_name,
                loop,
                on_finish_sync_callback if not loop else None # Only set callback if not looping
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
