"""
LED hardware abstraction for the Phoenix AI Companion Toy.

This module provides a hardware abstraction layer for LED control,
supporting different platforms (Raspberry Pi and simulated LEDs on macOS).
"""

import asyncio
import platform
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List, Tuple, Union, Callable
from .base import BaseHardware
from phoenix.core.config import LEDConfig

# Type alias for RGB color (0-255 for each component)
RGBColor = Tuple[int, int, int]

class LEDHardware(BaseHardware, ABC):
    """
    Base class for LED hardware implementations.
    
    This class defines the interface for LED control operations,
    which may be implemented differently on different platforms.
    """
    
    def __init__(self, config: LEDConfig, name: Optional[str] = None):
        """
        Initialize the LED hardware.
        
        Args:
            config: LED configuration
            name: Optional name for this hardware instance
        """
        super().__init__(config, name or "LEDHardware")
        self.brightness = config.brightness
        self.led_count = config.count
        
    @abstractmethod
    async def set_pixel(self, index: int, color: RGBColor) -> None:
        """
        Set the color of a specific LED.
        
        Args:
            index: LED index (0 to led_count-1)
            color: RGB color tuple (0-255 for each component)
        """
        pass
    
    @abstractmethod
    async def set_all_pixels(self, color: RGBColor) -> None:
        """
        Set all LEDs to the same color.
        
        Args:
            color: RGB color tuple (0-255 for each component)
        """
        pass
    
    @abstractmethod
    async def set_pixels(self, colors: List[RGBColor]) -> None:
        """
        Set multiple LEDs to different colors.
        
        Args:
            colors: List of RGB color tuples (0-255 for each component)
                   The length must match led_count
        """
        pass
    
    @abstractmethod
    async def set_brightness(self, brightness: float) -> None:
        """
        Set the overall brightness of the LEDs.
        
        Args:
            brightness: Brightness level (0.0 to 1.0)
        """
        pass
    
    @abstractmethod
    async def show(self) -> None:
        """
        Update the physical LEDs with the current color values.
        
        Some LED libraries require an explicit show() call to update
        the physical LEDs after setting colors.
        """
        pass
    
    @abstractmethod
    async def clear(self) -> None:
        """Turn off all LEDs."""
        pass
    
    async def pulse(self, color: RGBColor, duration: float = 1.0, 
                    fade_in: float = 0.5, fade_out: float = 0.5) -> None:
        """
        Pulse the LEDs with a specific color.
        
        This is a convenience method that fades in and out.
        
        Args:
            color: RGB color tuple (0-255 for each component)
            duration: Total duration of the pulse in seconds
            fade_in: Portion of duration spent fading in (0.0 to 1.0)
            fade_out: Portion of duration spent fading out (0.0 to 1.0)
        """
        # Validate parameters
        if fade_in + fade_out > 1.0:
            raise ValueError("fade_in + fade_out cannot exceed 1.0")
            
        # Calculate hold time
        hold_time = duration * (1.0 - fade_in - fade_out)
        fade_in_time = duration * fade_in
        fade_out_time = duration * fade_out
        
        # Fade in
        if fade_in_time > 0:
            start_time = asyncio.get_event_loop().time()
            while True:
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed >= fade_in_time:
                    break
                    
                progress = elapsed / fade_in_time
                scaled_color = tuple(int(c * progress) for c in color)
                await self.set_all_pixels(scaled_color)
                await self.show()
                await asyncio.sleep(0.02)  # 50 fps
                
        # Hold
        await self.set_all_pixels(color)
        await self.show()
        if hold_time > 0:
            await asyncio.sleep(hold_time)
            
        # Fade out
        if fade_out_time > 0:
            start_time = asyncio.get_event_loop().time()
            while True:
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed >= fade_out_time:
                    break
                    
                progress = 1.0 - (elapsed / fade_out_time)
                scaled_color = tuple(int(c * progress) for c in color)
                await self.set_all_pixels(scaled_color)
                await self.show()
                await asyncio.sleep(0.02)  # 50 fps
                
        # Ensure LEDs are off at the end
        await self.clear()
        await self.show()
    
    def get_led_count(self) -> int:
        """
        Get the number of LEDs.
        
        Returns:
            Number of LEDs
        """
        return self.led_count
        
    def get_brightness(self) -> float:
        """
        Get the current brightness level.
        
        Returns:
            Current brightness level (0.0 to 1.0)
        """
        return self.brightness
    
    @classmethod
    def create(cls, config: LEDConfig) -> 'LEDHardware':
        """
        Create an appropriate LED hardware instance for the current platform.
        
        Args:
            config: LED configuration
            
        Returns:
            Platform-specific LEDHardware instance
        """
        system = platform.system().lower()
        if system == "darwin":
            from .led_simulated import SimulatedLEDHardware
            return SimulatedLEDHardware(config)
        elif system == "linux":
            machine = platform.machine().lower()
            if "arm" in machine or "aarch" in machine:
                from .led_raspberry_pi import RaspberryPiLEDHardware
                return RaspberryPiLEDHardware(config)
            else:
                from .led_simulated import SimulatedLEDHardware
                return SimulatedLEDHardware(config)
        else:
            # Fall back to simulated LEDs on unsupported platforms
            from .led_simulated import SimulatedLEDHardware
            return SimulatedLEDHardware(config) 