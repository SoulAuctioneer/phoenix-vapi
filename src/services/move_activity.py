"""
This service maintains a state machine for the current activity and movement energy level.

It subscribes to accelerometer data and:
1. Uses the activity classification from the accelerometer
2. Calculates a movement energy level (0-1) based on acceleration and rotation
3. Publishes events when activity or energy level changes significantly
"""

import asyncio
import math
from typing import Dict, Any, Tuple
from services.service import BaseService

class MoveActivity(BaseService):
    """
    A service that maintains activity state and movement energy level.
    
    This service processes accelerometer data to:
    1. Track the current activity state using the accelerometer's classification
    2. Calculate a movement energy level (0-1) based on acceleration and rotation
    3. Publish events when significant changes occur
    """
    
    def __init__(self, manager):
        super().__init__(manager)
        self.current_activity = "unknown"
        self.previous_activity = "unknown"
        self.current_energy = 0.0
        self.previous_energy = 0.0
        self.energy_window = []  # Keep a window of recent energy values for smoothing
        self.window_size = 10  # Size of the buffer for smoothing
        
        # Energy calculation weights
        self.ACCEL_WEIGHT = 0.7  # Weight for acceleration in energy calculation
        self.GYRO_WEIGHT = 0.3   # Weight for rotation in energy calculation
        
    async def start(self):
        """Start the move activity service"""
        await super().start()
        self.logger.info("Move activity service started")
        
    async def stop(self):
        """Stop the move activity service"""
        await super().stop()
        self.logger.info("Move activity service stopped")
        
    async def handle_event(self, event: Dict[str, Any]):
        """
        Handle events from other services, particularly accelerometer sensor data.
        
        Args:
            event: The event to handle
        """
        if event.get("type") == "sensor_data" and event.get("sensor") == "accelerometer":
            # Extract data from accelerometer event
            data = event.get("data", {})
            linear_acceleration = data.get("linear_acceleration", (0.0, 0.0, 0.0))
            gyro = data.get("gyro", (0.0, 0.0, 0.0))
            activity_data = data.get("activity", {})
            
            # Get the most likely activity from the classification
            activity = activity_data.get("most_likely", "unknown")
            
            # Calculate movement energy
            energy = self._calculate_energy(linear_acceleration, gyro)
            
            # Update energy window for smoothing
            self.energy_window.append(energy)
            if len(self.energy_window) > self.window_size:
                self.energy_window.pop(0)
            
            # Calculate smoothed energy
            smoothed_energy = sum(self.energy_window) / len(self.energy_window)
            
            # Check if we need to publish updates
            energy_changed = abs(smoothed_energy - self.previous_energy) > 0.1
            activity_changed = activity != self.current_activity
            
            if energy_changed or activity_changed:
                self.previous_energy = self.current_energy
                self.current_energy = smoothed_energy
                self.previous_activity = self.current_activity
                self.current_activity = activity
                
                # Log the changes
                self.logger.info(f"Activity: {activity}, Energy: {smoothed_energy:.2f}")
                
                # Publish state update event
                await self.publish({
                    "type": "movement_state_update",
                    "activity": activity,
                    "previous_activity": self.previous_activity,
                    "energy": smoothed_energy,
                    "previous_energy": self.previous_energy,
                    "producer_name": "move_activity"
                })
    
    def _calculate_energy(self, linear_acceleration: Tuple[float, float, float], 
                         gyro: Tuple[float, float, float]) -> float:
        """
        Calculate movement energy level (0-1) based on acceleration and rotation.
        
        Args:
            linear_acceleration: Linear acceleration values (x, y, z) in m/s^2
            gyro: Gyroscope values (x, y, z) in rad/s
            
        Returns:
            float: Movement energy level from 0 (still) to 1 (very active)
        """
        # Calculate acceleration magnitude (removing gravity)
        accel_magnitude = math.sqrt(
            linear_acceleration[0]**2 + 
            linear_acceleration[1]**2 + 
            linear_acceleration[2]**2
        )
        
        # Normalize acceleration (assuming max acceleration of 20 m/s^2)
        accel_energy = min(1.0, accel_magnitude / 20.0)
        
        # Calculate rotation magnitude
        gyro_magnitude = math.sqrt(gyro[0]**2 + gyro[1]**2 + gyro[2]**2)
        
        # Normalize rotation (assuming max rotation of 10 rad/s)
        gyro_energy = min(1.0, gyro_magnitude / 10.0)
        
        # Combine energies with weights
        return (accel_energy * self.ACCEL_WEIGHT + 
                gyro_energy * self.GYRO_WEIGHT) 