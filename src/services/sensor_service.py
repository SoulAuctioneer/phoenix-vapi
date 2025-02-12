"""
Service for managing and coordinating various sensors including touch input.
Provides a high-level interface for sensor data and events to other services.
"""

import logging
from typing import Dict, Any
from services.service import BaseService, ServiceManager
from managers.touch_manager import TouchManager

class SensorService(BaseService):
    """
    Service for managing hardware sensors and providing sensor data to other services.
    Currently manages touch input, with architecture to support additional sensors.
    """
    
    def __init__(self, manager: ServiceManager):
        super().__init__(manager)
        self.touch_manager = TouchManager()
        
    async def start(self):
        """Initialize and start all sensor systems"""
        await super().start()
        
        # Set up touch manager callbacks
        self.touch_manager.on_position(self._handle_touch_position)
        self.touch_manager.on_stroke(self._handle_touch_stroke)
        self.touch_manager.on_touch(self._handle_touch_state)
        self.touch_manager.on_intensity(self._handle_touch_intensity)
        
        # Start the touch manager
        await self.touch_manager.start()
        self.logger.info("SensorService started successfully")
        
    async def stop(self):
        """Stop all sensor systems"""
        self.touch_manager.stop()
        await super().stop()
        self.logger.info("SensorService stopped")
        
    def _handle_touch_position(self, position: float):
        """Handle touch position updates from TouchManager"""
        self.publish({
            "type": "touch_position",
            "producer_name": "sensor_service",
            "position": position
        })
        
    def _handle_touch_stroke(self, direction: str):
        """Handle stroke detection events from TouchManager"""
        self.publish({
            "type": "touch_stroke",
            "producer_name": "sensor_service",
            "direction": direction
        })
        
    def _handle_touch_state(self, is_touching: bool):
        """Handle touch state changes from TouchManager"""
        self.publish({
            "type": "touch_state",
            "producer_name": "sensor_service",
            "is_touching": is_touching
        })
        
    def _handle_touch_intensity(self, intensity: float):
        """Handle touch intensity updates from TouchManager"""
        self.publish({
            "type": "touch_intensity",
            "producer_name": "sensor_service",
            "intensity": intensity
        })
        
    async def handle_event(self, event: Dict[str, Any]):
        """Handle incoming events from other services"""
        # Currently no events to handle, but architecture is in place for future needs
        pass 