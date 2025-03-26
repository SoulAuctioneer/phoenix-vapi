"""
Audio hardware abstraction for the Phoenix AI Companion Toy.

This module provides a hardware abstraction layer for audio input and output,
supporting different platforms (Raspberry Pi and macOS).
"""

import asyncio
import numpy as np
import platform
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, AsyncGenerator, List, Callable
from .base import BaseHardware
from phoenix.core.config import AudioConfig

class AudioHardware(BaseHardware, ABC):
    """
    Base class for audio hardware implementations.
    
    This class defines the interface for audio input and output operations,
    which may be implemented differently on different platforms.
    """
    
    def __init__(self, config: AudioConfig, name: Optional[str] = None):
        """
        Initialize the audio hardware.
        
        Args:
            config: Audio configuration
            name: Optional name for this hardware instance
        """
        super().__init__(config, name or "AudioHardware")
        self.volume = config.default_volume
        
    @abstractmethod
    async def get_audio_chunk(self) -> np.ndarray:
        """
        Get a chunk of audio from the microphone.
        
        Returns:
            NumPy array containing audio data
        """
        pass
    
    @abstractmethod
    async def get_audio_stream(self) -> AsyncGenerator[np.ndarray, None]:
        """
        Get a stream of audio chunks from the microphone.
        
        Yields:
            NumPy arrays containing audio data
        """
        pass
    
    @abstractmethod
    async def play_audio(self, audio_data: np.ndarray) -> None:
        """
        Play audio through the speaker.
        
        Args:
            audio_data: NumPy array containing audio data to play
        """
        pass
    
    @abstractmethod
    async def play_file(self, file_path: str, volume: Optional[float] = None) -> None:
        """
        Play an audio file through the speaker.
        
        Args:
            file_path: Path to the audio file
            volume: Optional volume override (0.0 to 1.0)
        """
        pass
    
    async def set_volume(self, volume: float) -> None:
        """
        Set the audio output volume.
        
        Args:
            volume: Volume level (0.0 to 1.0)
        """
        if volume < 0.0 or volume > 1.0:
            raise ValueError("Volume must be between 0.0 and 1.0")
        self.volume = volume
        
    def get_volume(self) -> float:
        """
        Get the current audio output volume.
        
        Returns:
            Current volume level (0.0 to 1.0)
        """
        return self.volume
    
    @abstractmethod
    async def mute(self) -> None:
        """Mute the microphone."""
        pass
    
    @abstractmethod
    async def unmute(self) -> None:
        """Unmute the microphone."""
        pass
    
    @abstractmethod
    def is_muted(self) -> bool:
        """
        Check if the microphone is muted.
        
        Returns:
            True if muted, False otherwise
        """
        pass
    
    @classmethod
    def create(cls, config: AudioConfig) -> 'AudioHardware':
        """
        Create an appropriate audio hardware instance for the current platform.
        
        Args:
            config: Audio configuration
            
        Returns:
            Platform-specific AudioHardware instance
        """
        system = platform.system().lower()
        if system == "darwin":
            from .audio_macos import MacOSAudioHardware
            return MacOSAudioHardware(config)
        elif system == "linux":
            from .audio_raspberry_pi import RaspberryPiAudioHardware
            return RaspberryPiAudioHardware(config)
        else:
            raise RuntimeError(f"Unsupported platform: {system}")
            
    def get_format_bytes_per_sample(self) -> int:
        """
        Get the number of bytes per sample for the current audio format.
        
        Returns:
            Bytes per sample
        """
        format_str = self.config.format
        if format_str == "int16":
            return 2
        elif format_str == "int32" or format_str == "float32":
            return 4
        else:
            raise ValueError(f"Unsupported audio format: {format_str}")
            
    def get_sample_rate(self) -> int:
        """
        Get the sample rate for the current audio configuration.
        
        Returns:
            Sample rate in Hz
        """
        return self.config.sample_rate
        
    def get_channels(self) -> int:
        """
        Get the number of channels for the current audio configuration.
        
        Returns:
            Number of channels
        """
        return self.config.channels 