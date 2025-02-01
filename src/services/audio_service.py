import logging
from typing import Dict, Any
import asyncio
from services.service import BaseService
from managers.audio_manager import AudioManager, AudioConfig

class AudioService(BaseService):
    """Service to manage the AudioManager lifecycle"""
    def __init__(self, manager):
        super().__init__(manager)
        self.audio_manager = None
        
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
        
        if event_type == "play_sound":
            # Handle direct play_sound requests
            effect_name = event.get("effect_name")
            await self._play_sound(effect_name)
        
        elif event_type == "application_startup_completed":
            # Play rising tone when application starts up
            await self._play_sound("RISING_TONE")
                
        elif event_type == "conversation_starting":
            # Play acknowledgment sound when conversation starts
            await self._play_sound("MMHMM")
                
        elif event_type == "conversation_ended":
            # Play yawn sound when conversation ends
            await self._play_sound("YAWN") 

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
        