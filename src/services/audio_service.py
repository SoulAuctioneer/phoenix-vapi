import logging
from typing import Dict, Any
from .base import BaseService
from .audio_manager import AudioManager, AudioConfig

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
            logging.info("Audio service started successfully")
            
        except Exception as e:
            logging.error(f"Failed to start audio service: {e}")
            raise
            
    async def stop(self):
        """Stop the audio service"""
        if self.audio_manager:
            try:
                self.audio_manager.stop()
                logging.info("Audio service stopped successfully")
            except Exception as e:
                logging.error(f"Error stopping audio service: {e}")
                
        await super().stop()
        
    async def handle_event(self, event: Dict[str, Any]):
        """Handle events from other services"""
        # Currently no events to handle, but we could add volume control events etc.
        pass 