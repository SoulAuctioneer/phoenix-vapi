"""
Service for managing haptic feedback effects.
Provides high-level haptic patterns and responds to system events to create immersive feedback.
"""

import logging
import asyncio
from typing import Dict, Any, Optional
from services.service import BaseService, ServiceManager
from managers.haptic_manager import HapticManager, WaveformEffect

class HapticService(BaseService):
    """
    Service for managing haptic feedback patterns and responding to system events.
    Creates immersive haptic feedback patterns like purring in response to petting.
    """
    
    def __init__(self, manager: ServiceManager):
        super().__init__(manager)
        self.haptic_manager = HapticManager()
        self._purr_task: Optional[asyncio.Task] = None
        self._current_intensity = 0.0
        
    async def start(self):
        """Initialize and start the haptic service"""
        await super().start()
        
        # Configure for ERM motor type (typical vibration motor)
        self.haptic_manager.use_ERM_motor()
        
        self.logger.info("HapticService started successfully")
        
    async def stop(self):
        """Stop the haptic service and any ongoing effects"""
        if self._purr_task:
            self._purr_task.cancel()
            self._purr_task = None
            
        self.haptic_manager.stop()
        await super().stop()
        self.logger.info("HapticService stopped")
        
    async def _generate_purr_sequence(self, intensity: float) -> None:
        """Generate a continuous purring effect that varies with intensity
        
        The purr effect is created by combining:
        1. Smooth hums for the continuous vibration
        2. Gentle pulses for the rhythmic aspect of purring
        3. Intensity variations based on stroke intensity
        
        Args:
            intensity: Stroke intensity value (0.0 to 1.0)
        """
        try:
            while True:
                # Skip if intensity is 0
                if intensity <= 0:
                    await asyncio.sleep(0.1)
                    continue
                    
                # Base sequence on intensity level
                if intensity < 0.3:
                    # Very gentle purr
                    sequence = [
                        WaveformEffect.SMOOTH_HUM_5_10_TO_0.value,  # Light continuous hum
                        0.2,  # Short pause
                        WaveformEffect.PULSING_MEDIUM_2_60.value,  # Gentle pulse
                        0.3   # Longer pause for slower rhythm
                    ]
                elif intensity < 0.6:
                    # Medium purr
                    sequence = [
                        WaveformEffect.SMOOTH_HUM_3_30_TO_0.value,  # Medium continuous hum
                        0.15,  # Shorter pause
                        WaveformEffect.PULSING_MEDIUM_1_100.value,  # Stronger pulse
                        0.25   # Medium pause for moderate rhythm
                    ]
                else:
                    # Strong purr
                    sequence = [
                        WaveformEffect.SMOOTH_HUM_1_50_TO_0.value,  # Strong continuous hum
                        0.1,   # Quick pause
                        WaveformEffect.PULSING_STRONG_1_100.value,  # Strong pulse
                        0.2    # Short pause for faster rhythm
                    ]
                    
                # Play the sequence
                await self.haptic_manager.play_sequence(sequence)
                
                # Small delay between sequences
                await asyncio.sleep(0.1)
                
        except asyncio.CancelledError:
            self.haptic_manager.stop()
        except Exception as e:
            self.logger.error(f"Error in purr sequence generation: {str(e)}")
            self.haptic_manager.stop()
            
    def _update_purr_effect(self, intensity: float):
        """Update the purring effect based on new intensity value
        
        Args:
            intensity: New stroke intensity value (0.0 to 1.0)
        """
        if intensity == self._current_intensity:
            return
            
        self._current_intensity = intensity
        
        # Stop current purr task if intensity is 0
        if intensity == 0 and self._purr_task:
            self._purr_task.cancel()
            self._purr_task = None
            return
            
        # Start new purr task if none exists
        if not self._purr_task or self._purr_task.done():
            self._purr_task = asyncio.create_task(
                self._generate_purr_sequence(intensity)
            )
        
    async def handle_event(self, event: Dict[str, Any]):
        """Handle incoming events from other services
        
        Currently handles:
        - touch_stroke_intensity: Updates purring intensity based on stroke intensity
        """
        if event["type"] == "touch_stroke_intensity":
            intensity = event["intensity"]
            self._update_purr_effect(intensity) 