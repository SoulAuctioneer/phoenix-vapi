"""
Service for managing haptic feedback effects.
Provides high-level haptic patterns and responds to system events to create immersive feedback.
"""

import logging
import asyncio
import math
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
        
        # Start in realtime mode
        self.haptic_manager.start_realtime_mode()
        
        self.logger.info("HapticService started successfully")
        
    async def stop(self):
        """Stop the haptic service and any ongoing effects"""
        if self._purr_task:
            self._purr_task.cancel()
            self._purr_task = None
            
        # Stop motor and exit realtime mode
        self.haptic_manager.set_realtime_value(0)
        self.haptic_manager.exit_realtime_mode()
        await super().stop()
        self.logger.info("HapticService stopped")

    async def _generate_purr_sequence(self, intensity: float) -> None:
        """Generate a continuous purring effect that varies with intensity using realtime control
        
        Creates a purring effect by modulating the motor speed in a sinusoidal pattern.
        The pattern combines:
        1. Base vibration level that increases with intensity
        2. Sinusoidal modulation for the rhythmic purring effect
        3. Secondary faster modulation for texture
        4. Variable frequency based on intensity (faster purring when more intense)
        
        Args:
            intensity: Stroke intensity value (0.0 to 1.0)
        """
        try:
            # Purring parameters that vary with intensity
            base_freq = 2.0 + (intensity * 4.0)  # Base frequency 2-6 Hz
            texture_freq = 30.0 + (intensity * 20.0)  # Texture frequency 30-50 Hz
            
            # Time tracking
            start_time = asyncio.get_event_loop().time()
            
            while True:
                # Skip if intensity is 0
                if intensity <= 0:
                    self.haptic_manager.set_realtime_value(0)
                    await asyncio.sleep(0.01)
                    continue
                
                current_time = asyncio.get_event_loop().time()
                elapsed = current_time - start_time
                
                # Calculate base vibration level (0-100)
                base_level = 20 + (intensity * 60)  # Maps 0.0-1.0 to 20-80
                
                # Primary modulation for main purring rhythm
                main_mod = math.sin(2 * math.pi * base_freq * elapsed)
                
                # Secondary faster modulation for texture
                texture_mod = 0.2 * math.sin(2 * math.pi * texture_freq * elapsed)
                
                # Combine modulations and map to appropriate range
                combined_mod = main_mod + texture_mod
                # Scale modulation to +/-0.8 range to maintain some base vibration
                combined_mod *= 0.8
                
                # Calculate final motor value
                # Map intensity and modulation to 0-127 range for positive-only drive
                motor_value = int(base_level * (1.0 + combined_mod))
                motor_value = max(0, min(127, motor_value))
                
                # Set motor value
                self.haptic_manager.set_realtime_value(motor_value)
                
                # Small delay for update rate
                await asyncio.sleep(0.005)  # 200Hz update rate
                
        except asyncio.CancelledError:
            self.haptic_manager.set_realtime_value(0)
        except Exception as e:
            self.logger.error(f"Error in purr sequence generation: {str(e)}")
            self.haptic_manager.set_realtime_value(0)
            
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

# Original waveform-based implementation (commented out for reference)
"""
    async def _generate_purr_sequence(self, intensity: float) -> None:
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
""" 