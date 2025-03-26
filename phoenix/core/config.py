"""
Configuration management system for the Phoenix AI Companion Toy.

This module provides Pydantic models for type-safe configuration with validation
and environment variable integration. It replaces the previous monolithic config.py.
"""

import os
import platform
from typing import Dict, Any, Optional, List, Union
from enum import Enum
from pydantic import BaseSettings, Field, validator

# Determine platform
system = platform.system().lower()
machine = platform.machine().lower()
if system == "darwin":
    PLATFORM = "macos"
elif system == "linux" and ("arm" in machine or "aarch" in machine):
    PLATFORM = "raspberry-pi"
else:
    raise ValueError(f"Unsupported platform: {system} {machine}")

class LogLevel(str, Enum):
    """Log levels for the application."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

class BaseConfig(BaseSettings):
    """
    Base configuration class with common settings for all components.
    
    All other configuration classes should inherit from this class.
    """
    debug: bool = False
    log_level: LogLevel = LogLevel.INFO
    metrics_enabled: bool = True
    platform: str = PLATFORM
    
    class Config:
        """Pydantic configuration"""
        env_file = ".env"
        # Allow environment variable override
        env_prefix = "PHOENIX_"

class EventConfig(BaseConfig):
    """Configuration for the event system."""
    max_trace_events: int = 1000
    tracing_enabled: bool = True
    
    class Config:
        """Pydantic configuration"""
        env_prefix = "PHOENIX_EVENT_"

class ServiceConfig(BaseConfig):
    """Configuration for service management."""
    service_startup_timeout: float = 10.0  # seconds
    service_shutdown_timeout: float = 5.0  # seconds
    
    class Config:
        """Pydantic configuration"""
        env_prefix = "PHOENIX_SERVICE_"

class WakeWordConfig(BaseConfig):
    """Configuration for wake word detection."""
    access_key: str = Field(default="", env="PICOVOICE_ACCESS_KEY")
    model_path: Optional[str] = Field(default=None, env="PORCUPINE_MODEL_PATH")
    sensitivity: float = 0.5
    
    class Config:
        """Pydantic configuration"""
        env_prefix = "PHOENIX_WAKE_WORD_"

class IntentConfig(BaseConfig):
    """Configuration for intent detection."""
    access_key: str = Field(default="", env="PICOVOICE_ACCESS_KEY")
    model_path: Optional[str] = Field(default=None, env="RHINO_MODEL_PATH")
    detection_timeout: float = 7.0  # seconds
    
    class Config:
        """Pydantic configuration"""
        env_prefix = "PHOENIX_INTENT_"

class AudioConfig(BaseConfig):
    """Configuration for audio processing."""
    format: str = "int16"
    channels: int = 1
    sample_rate: int = 16000
    chunk_size: int = 640
    buffer_size: int = 5
    default_volume: float = 1.0
    
    @validator("format")
    def validate_format(cls, v):
        """Validate audio format is supported."""
        valid_formats = ["int16", "int32", "float32"]
        if v not in valid_formats:
            raise ValueError(f"Audio format must be one of {valid_formats}")
        return v
    
    class Config:
        """Pydantic configuration"""
        env_prefix = "PHOENIX_AUDIO_"

class LEDConfig(BaseConfig):
    """Configuration for LED control."""
    pin: int = 21
    count: int = 160
    brightness: float = 0.1
    order: str = "GRB"
    
    @validator("brightness")
    def validate_brightness(cls, v):
        """Validate brightness is within range."""
        if not 0.0 <= v <= 1.0:
            raise ValueError("Brightness must be between 0.0 and 1.0")
        return v
    
    class Config:
        """Pydantic configuration"""
        env_prefix = "PHOENIX_LED_"

class VAPIConfig(BaseConfig):
    """Configuration for VAPI integration."""
    api_key: str = Field(default="", env="VAPI_API_KEY")
    client_key: str = Field(default="", env="VAPI_CLIENT_KEY")
    assistant_id: str = Field(default="")
    api_url: str = "https://api.vapi.ai"
    speaker_username: str = "Phoenix"
    
    class Config:
        """Pydantic configuration"""
        env_prefix = "PHOENIX_VAPI_"

class Distance(str, Enum):
    """Distance categories for proximity detection."""
    IMMEDIATE = "immediate"
    VERY_NEAR = "very_near"
    NEAR = "near"
    FAR = "far"
    VERY_FAR = "very_far"
    UNKNOWN = "unknown"

class BLEConfig(BaseConfig):
    """Configuration for BLE and location tracking."""
    bluetooth_interface: str = "hci0"
    beacon_uuid: str = "426C7565-4368-6172-6D42-6561636F6E73"
    beacon_locations: Dict[str, str] = {
        "1-1": "magical_sun_pendant",
        "1-2": "blue_phoenix"
    }
    rssi_immediate: int = -55
    rssi_very_near: int = -65
    rssi_near: int = -75
    rssi_far: int = -85
    rssi_very_far: int = -100
    min_rssi_threshold: int = -105
    rssi_hysteresis: int = 12
    scan_duration: float = 1.0
    scan_interval: float = 2.0
    beacon_timeout_sec: float = 12.0
    
    class Config:
        """Pydantic configuration"""
        env_prefix = "PHOENIX_BLE_"

class OpenAIConfig(BaseConfig):
    """Configuration for OpenAI integration."""
    api_key: str = Field(default="", env="OPENAI_API_KEY")
    model: str = "gpt-4o"
    temperature: float = 0.7
    
    @validator("temperature")
    def validate_temperature(cls, v):
        """Validate temperature is within range."""
        if not 0.0 <= v <= 2.0:
            raise ValueError("Temperature must be between 0.0 and 2.0")
        return v
    
    class Config:
        """Pydantic configuration"""
        env_prefix = "PHOENIX_OPENAI_"

class ApplicationConfig(BaseConfig):
    """
    Main application configuration that combines all component configurations.
    
    This is the top-level configuration class that should be used by the application.
    """
    event: EventConfig = Field(default_factory=EventConfig)
    service: ServiceConfig = Field(default_factory=ServiceConfig)
    wake_word: WakeWordConfig = Field(default_factory=WakeWordConfig)
    intent: IntentConfig = Field(default_factory=IntentConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    led: LEDConfig = Field(default_factory=LEDConfig)
    vapi: VAPIConfig = Field(default_factory=VAPIConfig)
    ble: BLEConfig = Field(default_factory=BLEConfig)
    openai: OpenAIConfig = Field(default_factory=OpenAIConfig)
    
    class Config:
        """Pydantic configuration"""
        env_file = ".env"
        env_nested_delimiter = "__"

def get_config() -> ApplicationConfig:
    """
    Get the application configuration.
    
    Returns:
        The validated ApplicationConfig instance
    """
    return ApplicationConfig() 