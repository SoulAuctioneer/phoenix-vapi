"""
Core haptic feedback functionality using the DRV2605L haptic controller.

This module provides a high-level interface for controlling haptic feedback effects
using the DRV2605L controller. It supports playing individual effects, sequences
of effects with pauses, and managing the haptic motor type.

The DRV2605L supports 123 different haptic effects and can chain up to 8 effects
in a sequence. Effects can be combined with pauses for complex haptic patterns.
"""

import time
import logging
import asyncio
from config import PLATFORM
from typing import List, Union, Optional, Tuple

# Only import hardware-specific libraries on Raspberry Pi
if PLATFORM == "raspberry-pi":
    import board
    import busio
    import adafruit_drv2605

# Type alias for effect sequences
HapticSequence = List[Union[int, float]]  # int for effect ID, float for pause duration

from enum import Enum

class WaveformEffect(Enum):
    STRONG_CLICK_100 = 1
    STRONG_CLICK_60 = 2
    STRONG_CLICK_30 = 3
    SHARP_CLICK_100 = 4
    SHARP_CLICK_60 = 5
    SHARP_CLICK_30 = 6
    SOFT_BUMP_100 = 7
    SOFT_BUMP_60 = 8
    SOFT_BUMP_30 = 9
    DOUBLE_CLICK_100 = 10
    DOUBLE_CLICK_60 = 11
    TRIPLE_CLICK_100 = 12
    SOFT_FUZZ_60 = 13
    STRONG_BUZZ_100 = 14
    ALERT_750_MS_100 = 15
    ALERT_1000_MS_100 = 16
    STRONG_CLICK_1_100 = 17
    STRONG_CLICK_2_80 = 18
    STRONG_CLICK_3_60 = 19
    STRONG_CLICK_4_30 = 20
    MEDIUM_CLICK_1_100 = 21
    MEDIUM_CLICK_2_80 = 22
    MEDIUM_CLICK_3_60 = 23
    SHARP_TICK_1_100 = 24
    SHARP_TICK_2_80 = 25
    SHARP_TICK_3_60 = 26
    SHORT_DOUBLE_CLICK_STRONG_1_100 = 27
    SHORT_DOUBLE_CLICK_STRONG_2_80 = 28
    SHORT_DOUBLE_CLICK_STRONG_3_60 = 29
    SHORT_DOUBLE_CLICK_STRONG_4_30 = 30
    SHORT_DOUBLE_CLICK_MEDIUM_1_100 = 31
    SHORT_DOUBLE_CLICK_MEDIUM_2_80 = 32
    SHORT_DOUBLE_CLICK_MEDIUM_3_60 = 33
    SHORT_DOUBLE_SHARP_TICK_1_100 = 34
    SHORT_DOUBLE_SHARP_TICK_2_80 = 35
    SHORT_DOUBLE_SHARP_TICK_3_60 = 36
    LONG_DOUBLE_SHARP_CLICK_STRONG_1_100 = 37
    LONG_DOUBLE_SHARP_CLICK_STRONG_2_100 = 38
    LONG_DOUBLE_SHARP_CLICK_STRONG_3_100 = 39
    LONG_DOUBLE_SHARP_CLICK_STRONG_4_100 = 40
    LONG_DOUBLE_SHARP_CLICK_MEDIUM_1_80 = 41
    LONG_DOUBLE_SHARP_CLICK_MEDIUM_2_80 = 42
    LONG_DOUBLE_SHARP_CLICK_MEDIUM_3_60 = 43
    LONG_DOUBLE_SHARP_TICK_1_100 = 44
    LONG_DOUBLE_SHARP_TICK_2_80 = 45
    LONG_DOUBLE_SHARP_TICK_3_60 = 46
    BUZZ_1_100 = 47
    BUZZ_2_80 = 48
    BUZZ_3_60 = 49
    BUZZ_4_40 = 50
    BUZZ_5_20 = 51
    PULSING_STRONG_1_100 = 52
    PULSING_STRONG_2_60 = 53
    PULSING_MEDIUM_1_100 = 54
    PULSING_MEDIUM_2_60 = 55
    PULSING_SHARP_1_100 = 56
    PULSING_SHARP_2_60 = 57
    TRANSITION_CLICK_1_100 = 58
    TRANSITION_CLICK_2_80 = 59
    TRANSITION_CLICK_3_60 = 60
    TRANSITION_CLICK_4_40 = 61
    TRANSITION_CLICK_5_20 = 62
    TRANSITION_CLICK_6_10 = 63
    TRANSITION_HUM_1_100 = 64
    TRANSITION_HUM_2_80 = 65
    TRANSITION_HUM_3_60 = 66
    TRANSITION_HUM_4_40 = 67
    TRANSITION_HUM_5_20 = 68
    TRANSITION_HUM_6_10 = 69
    TRANSITION_RAMP_DOWN_LONG_SMOOTH_1_100_TO_0 = 70
    TRANSITION_RAMP_DOWN_LONG_SMOOTH_2_100_TO_0 = 71
    TRANSITION_RAMP_DOWN_MEDIUM_SMOOTH_1_100_TO_0 = 72
    TRANSITION_RAMP_DOWN_MEDIUM_SMOOTH_2_100_TO_0 = 73
    TRANSITION_RAMP_DOWN_SHORT_SMOOTH_1_100_TO_0 = 74
    TRANSITION_RAMP_DOWN_SHORT_SMOOTH_2_100_TO_0 = 75
    TRANSITION_RAMP_DOWN_LONG_SHARP_1_100_TO_0 = 76
    TRANSITION_RAMP_DOWN_LONG_SHARP_2_100_TO_0 = 77
    TRANSITION_RAMP_DOWN_MEDIUM_SHARP_1_100_TO_0 = 78
    TRANSITION_RAMP_DOWN_MEDIUM_SHARP_2_100_TO_0 = 79
    TRANSITION_RAMP_DOWN_SHORT_SHARP_1_100_TO_0 = 80
    TRANSITION_RAMP_DOWN_SHORT_SHARP_2_100_TO_0 = 81
    TRANSITION_RAMP_UP_LONG_SMOOTH_1_0_TO_100 = 82
    TRANSITION_RAMP_UP_LONG_SMOOTH_2_0_TO_100 = 83
    TRANSITION_RAMP_UP_MEDIUM_SMOOTH_1_0_TO_100 = 84
    TRANSITION_RAMP_UP_MEDIUM_SMOOTH_2_0_TO_100 = 85
    TRANSITION_RAMP_UP_SHORT_SMOOTH_1_0_TO_100 = 86
    TRANSITION_RAMP_UP_SHORT_SMOOTH_2_0_TO_100 = 87
    TRANSITION_RAMP_UP_LONG_SHARP_1_0_TO_100 = 88
    TRANSITION_RAMP_UP_LONG_SHARP_2_0_TO_100 = 89
    TRANSITION_RAMP_UP_MEDIUM_SHARP_1_0_TO_100 = 90
    TRANSITION_RAMP_UP_MEDIUM_SHARP_2_0_TO_100 = 91
    TRANSITION_RAMP_UP_SHORT_SHARP_1_0_TO_100 = 92
    TRANSITION_RAMP_UP_SHORT_SHARP_2_0_TO_100 = 93
    TRANSITION_RAMP_DOWN_LONG_SMOOTH_1_50_TO_0 = 94
    TRANSITION_RAMP_DOWN_LONG_SMOOTH_2_50_TO_0 = 95
    TRANSITION_RAMP_DOWN_MEDIUM_SMOOTH_1_50_TO_0 = 96
    TRANSITION_RAMP_DOWN_MEDIUM_SMOOTH_2_50_TO_0 = 97
    TRANSITION_RAMP_DOWN_SHORT_SMOOTH_1_50_TO_0 = 98
    TRANSITION_RAMP_DOWN_SHORT_SMOOTH_2_50_TO_0 = 99
    TRANSITION_RAMP_DOWN_LONG_SHARP_1_50_TO_0 = 100
    TRANSITION_RAMP_DOWN_LONG_SHARP_2_50_TO_0 = 101
    TRANSITION_RAMP_DOWN_MEDIUM_SHARP_1_50_TO_0 = 102
    TRANSITION_RAMP_DOWN_MEDIUM_SHARP_2_50_TO_0 = 103
    TRANSITION_RAMP_DOWN_SHORT_SHARP_1_50_TO_0 = 104
    TRANSITION_RAMP_DOWN_SHORT_SHARP_2_50_TO_0 = 105
    TRANSITION_RAMP_UP_LONG_SMOOTH_1_0_TO_50 = 106
    TRANSITION_RAMP_UP_LONG_SMOOTH_2_0_TO_50 = 107
    TRANSITION_RAMP_UP_MEDIUM_SMOOTH_1_0_TO_50 = 108
    TRANSITION_RAMP_UP_MEDIUM_SMOOTH_2_0_TO_50 = 109
    TRANSITION_RAMP_UP_SHORT_SMOOTH_1_0_TO_50 = 110
    TRANSITION_RAMP_UP_SHORT_SMOOTH_2_0_TO_50 = 111
    TRANSITION_RAMP_UP_LONG_SHARP_1_0_TO_50 = 112
    TRANSITION_RAMP_UP_LONG_SHARP_2_0_TO_50 = 113
    TRANSITION_RAMP_UP_MEDIUM_SHARP_1_0_TO_50 = 114
    TRANSITION_RAMP_UP_MEDIUM_SHARP_2_0_TO_50 = 115
    TRANSITION_RAMP_UP_SHORT_SHARP_1_0_TO_50 = 116
    TRANSITION_RAMP_UP_SHORT_SHARP_2_0_TO_50 = 117
    LONG_BUZZ_PROGRAMMATIC_STOP_100_TO_0 = 118
    SMOOTH_HUM_1_50_TO_0 = 119
    SMOOTH_HUM_2_40_TO_0 = 120
    SMOOTH_HUM_3_30_TO_0 = 121
    SMOOTH_HUM_4_20_TO_0 = 122
    SMOOTH_HUM_5_10_TO_0 = 123


class HapticManager:
    """Main class for controlling haptic feedback effects"""
    
    def __init__(self):
        """Initialize the haptic manager and DRV2605L controller"""
        self.running = False
        self._current_sequence: Optional[List[Tuple[Union[int, float], bool]]] = None  # (value, is_pause)
        self._sequence_task = None
        
        if PLATFORM == "raspberry-pi":
            try:
                # Initialize I2C and DRV2605L
                i2c = busio.I2C(board.SCL, board.SDA)
                self.drv = adafruit_drv2605.DRV2605(i2c)
                logging.info("Initialized DRV2605L haptic controller")
            except Exception as e:
                logging.error(f"Failed to initialize DRV2605L: {str(e)}")
                self.drv = None
        else:
            # Mock driver for non-Raspberry Pi platforms
            self.drv = None
            logging.info("Initialized mock haptic controller for non-Raspberry Pi platform")

    def play_effect(self, effect_id: int) -> bool:
        """Play a single haptic effect
        
        Args:
            effect_id: ID of the effect to play (1-123)
            
        Returns:
            bool: True if effect was played successfully
        """
        if not self.drv:
            logging.warning("No haptic controller available")
            return False
            
        try:
            if not 1 <= effect_id <= 123:
                logging.error(f"Invalid effect ID: {effect_id}")
                return False
                
            self.drv.sequence[0] = adafruit_drv2605.Effect(effect_id)
            self.drv.play()
            return True
        except Exception as e:
            logging.error(f"Error playing haptic effect {effect_id}: {str(e)}")
            return False

    def stop(self) -> None:
        """Stop any currently playing haptic effects"""
        if self.drv:
            try:
                self.drv.stop()
                if self._sequence_task:
                    self._sequence_task.cancel()
                    self._sequence_task = None
                self._current_sequence = None
            except Exception as e:
                logging.error(f"Error stopping haptic effects: {str(e)}")

    async def play_sequence(self, sequence: HapticSequence) -> bool:
        """Play a sequence of effects and pauses
        
        Args:
            sequence: List of effect IDs (int) and pause durations (float).
                     Integers are treated as effect IDs, floats as pause durations in seconds.
                     Maximum 8 effects can be played in a sequence.
                     
        Returns:
            bool: True if sequence started playing successfully
            
        Example:
            # Play effect 1, pause 0.5s, play effect 47
            await haptic_manager.play_sequence([1, 0.5, 47])
        """
        if not self.drv:
            logging.warning("No haptic controller available")
            return False
            
        # Validate sequence
        effect_count = sum(1 for x in sequence if isinstance(x, int))
        if effect_count > 8:
            logging.error(f"Sequence contains {effect_count} effects, maximum is 8")
            return False
            
        try:
            # Cancel any current sequence
            if self._sequence_task:
                self._sequence_task.cancel()
                
            # Process sequence into (value, is_pause) tuples
            self._current_sequence = [(x, isinstance(x, float)) for x in sequence]
            
            # Start sequence playback task
            self._sequence_task = asyncio.create_task(self._play_sequence_task())
            return True
            
        except Exception as e:
            logging.error(f"Error starting haptic sequence: {str(e)}")
            self._current_sequence = None
            return False

    async def _play_sequence_task(self) -> None:
        """Internal task to play through the current sequence"""
        if not self._current_sequence:
            return
            
        try:
            slot = 0
            for value, is_pause in self._current_sequence:
                if is_pause:
                    # Handle pause
                    await asyncio.sleep(value)
                else:
                    # Handle effect
                    if not 1 <= value <= 123:
                        logging.error(f"Invalid effect ID in sequence: {value}")
                        continue
                        
                    self.drv.sequence[slot] = adafruit_drv2605.Effect(value)
                    slot += 1
                    
                    if slot >= 8:
                        # Play accumulated effects if we hit the slot limit
                        self.drv.play()
                        await asyncio.sleep(0.5)  # Wait for effects to complete
                        slot = 0
                        
            # Play any remaining effects
            if slot > 0:
                self.drv.play()
                
        except asyncio.CancelledError:
            # Sequence was cancelled
            self.stop()
        except Exception as e:
            logging.error(f"Error playing haptic sequence: {str(e)}")
            self.stop()
        finally:
            self._current_sequence = None
            self._sequence_task = None

    def use_LRA_motor(self) -> bool:
        """Configure for Linear Resonance Actuator (LRA) motor type
        
        Returns:
            bool: True if configuration was successful
        """
        if not self.drv:
            return False
            
        try:
            self.drv.use_LRM()
            return True
        except Exception as e:
            logging.error(f"Error configuring LRA motor: {str(e)}")
            return False

    def use_ERM_motor(self) -> bool:
        """Configure for Eccentric Rotating Mass (ERM) motor type
        
        Returns:
            bool: True if configuration was successful
        """
        if not self.drv:
            return False
            
        try:
            self.drv.use_ERM()
            return True
        except Exception as e:
            logging.error(f"Error configuring ERM motor: {str(e)}")
            return False

    def set_realtime_value(self, value: int) -> bool:
        """Set a raw realtime value to directly control the motor amplitude.
        
        Args:
            value: Signed 8-bit integer (-127 to 255) controlling motor amplitude/direction.
                  Positive values drive the motor forward, negative values drive in reverse.
                  The magnitude determines the strength of vibration.
                  
        Returns:
            bool: True if value was set successfully
            
        Note:
            Automatically switches to realtime mode if needed.
            The exact effect depends on motor type (ERM/LRA) and open/closed loop mode.
        """
        if not self.drv:
            logging.warning("No haptic controller available")
            return False
            
        try:
            if not -127 <= value <= 255:
                logging.error(f"Invalid realtime value {value}. Must be between -127 and 255")
                return False
            
            # Switch to realtime mode if not already in it
            if self.drv.mode != adafruit_drv2605.MODE_REALTIME:
                if not self.start_realtime_mode():
                    return False
                
            self.drv.realtime_value = value
            logging.info(f"Set realtime value to {value}")
            return True
        except Exception as e:
            logging.error(f"Error setting realtime value: {str(e)}")
            return False

    def start_realtime_mode(self) -> bool:
        """Switch to realtime playback mode for direct motor control.
        
        Returns:
            bool: True if mode was set successfully
        """
        if not self.drv:
            logging.warning("No haptic controller available") 
            return False
            
        try:
            self.drv.mode = adafruit_drv2605.MODE_REALTIME
            return True
        except Exception as e:
            logging.error(f"Error setting realtime mode: {str(e)}")
            return False

    def exit_realtime_mode(self) -> bool:
        """Exit realtime mode and return to internal trigger mode.
        
        Returns:
            bool: True if mode was set successfully
        """
        if not self.drv:
            logging.warning("No haptic controller available")
            return False
            
        try:
            self.drv.mode = adafruit_drv2605.MODE_INTTRIG
            return True
        except Exception as e:
            logging.error(f"Error exiting realtime mode: {str(e)}")
            return False 