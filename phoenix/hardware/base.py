"""
Base hardware abstraction implementation for the Phoenix AI Companion Toy.

This module provides the BaseHardware class that all hardware abstractions should
inherit from, defining the core hardware lifecycle and interface.
"""

import asyncio
import structlog
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

class BaseHardware(ABC):
    """
    Base class for all hardware abstractions.
    
    This class provides a common interface for all hardware components,
    including lifecycle management and error handling.
    """
    
    def __init__(self, config: Optional[Any] = None, name: Optional[str] = None):
        """
        Initialize the hardware component.
        
        Args:
            config: Optional hardware-specific configuration
            name: Optional name for this hardware instance
        """
        self.config = config
        self.name = name or self.__class__.__name__
        self.logger = structlog.get_logger(hardware=self.name)
        self._initialized = False
        self._lock = asyncio.Lock()
        
    async def initialize(self) -> None:
        """
        Initialize the hardware component.
        
        This method should be called before using the hardware and will
        perform any necessary setup and initialization.
        """
        async with self._lock:
            if self._initialized:
                self.logger.warning("Hardware already initialized")
                return
                
            try:
                await self._initialize_impl()
                self._initialized = True
                self.logger.info("Hardware initialized")
                
            except Exception as e:
                self.logger.error(f"Error initializing hardware: {e}")
                raise
                
    async def shutdown(self) -> None:
        """
        Shut down the hardware component.
        
        This method should be called when the hardware is no longer needed
        and will perform any necessary cleanup.
        """
        async with self._lock:
            if not self._initialized:
                self.logger.warning("Hardware not initialized")
                return
                
            try:
                await self._shutdown_impl()
                self._initialized = False
                self.logger.info("Hardware shut down")
                
            except Exception as e:
                self.logger.error(f"Error shutting down hardware: {e}")
                raise
                
    def is_initialized(self) -> bool:
        """
        Check if the hardware is initialized.
        
        Returns:
            True if the hardware is initialized, False otherwise
        """
        return self._initialized
        
    @abstractmethod
    async def _initialize_impl(self) -> None:
        """
        Implementation-specific initialization.
        
        This method should be overridden by subclasses to perform
        hardware-specific initialization.
        """
        pass
        
    @abstractmethod
    async def _shutdown_impl(self) -> None:
        """
        Implementation-specific shutdown.
        
        This method should be overridden by subclasses to perform
        hardware-specific cleanup.
        """
        pass
        
    async def check_health(self) -> Dict[str, Any]:
        """
        Check the health of the hardware component.
        
        This method can be overridden by subclasses to provide
        hardware-specific health information.
        
        Returns:
            Dictionary with health information
        """
        return {
            "name": self.name,
            "initialized": self._initialized,
            "status": "ok"
        } 