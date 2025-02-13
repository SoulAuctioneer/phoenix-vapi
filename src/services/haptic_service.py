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
        
        Creates a purring effect by combining:
        1. Slow amplitude modulation (~0.5 Hz) for the breathing-like pattern
        2. Power level that scales with intensity
        
        Args:
            intensity: Stroke intensity value (0.0 to 1.0)
        """
        try:
            # Slow modulation frequency (breaths per second)
            # Slightly faster at higher intensities: 0.4-0.6 Hz (2.5-1.67s per cycle)
            mod_freq = 0.4 + (intensity * 0.2)
            
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
                
                # Generate slow modulation wave
                wave = math.sin(2 * math.pi * mod_freq * elapsed)
                
                # Transform wave to create longer peaks and shorter troughs
                # This makes the purr feel more natural with longer "on" periods
                wave = math.copysign(abs(wave) ** 0.7, wave)
                
                # Map wave from [-1, 1] to [min_power, max_power]
                # Higher intensity = higher power range and higher minimum power
                min_power = int(30 + (intensity * 50))   # 30-80 range
                max_power = int(70 + (intensity * 57))   # 70-127 range
                
                # Linear interpolation between min and max power
                normalized = (wave + 1) / 2  # Map [-1,1] to [0,1]
                motor_value = int(min_power + (normalized * (max_power - min_power)))
                
                # Ensure we stay within valid range
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