import logging
from typing import Dict, Any
import asyncio
from .service import BaseService
from ..managers.audio_manager import AudioManager, AudioConfig

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
            wav_path = event.get("wav_path")
            producer_name = event.get("producer_name", "sound_effect")
            volume = event.get("volume", 1.0)  # Default to full volume if not specified
            if wav_path and self.audio_manager:
                # Run the audio playback in the event loop's executor to avoid blocking
                loop = asyncio.get_event_loop()
                success = await loop.run_in_executor(
                    None, 
                    self.audio_manager.play_wav_file,
                    wav_path,
                    producer_name,
                    volume
                )
                if not success:
                    self.logger.error(f"Failed to play sound: {wav_path}") 