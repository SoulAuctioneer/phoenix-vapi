"""
This service processes accelerometer data to classify the current activity.

It subscribes to the raw accelerometer events and analyzes the data to determine
what type of movement activity is happening, like walking, running, still, etc.
"""

import asyncio
import math
from typing import Dict, Any, Tuple, List
from services.service import BaseService

class MoveActivity(BaseService):
    """
    A service that subscribes to accelerometer data and classifies the current movement activity.
    
    This service processes the raw sensor data from the accelerometer to detect and classify
    different types of movement activities like walking, running, or standing still.
    """
    
    def __init__(self, manager):
        super().__init__(manager)
        self.current_activity = "unknown"
        self.previous_activity = "unknown"
        self.activity_confidence = 0.0
        self.stability_window = []  # Keep a window of recent stability values
        self.accel_window = []  # Keep a window of recent acceleration values
        self.window_size = 10  # Size of the buffer for smoothing
        
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
            acceleration = data.get("acceleration", (0.0, 0.0, 0.0))
            linear_acceleration = data.get("linear_acceleration", (0.0, 0.0, 0.0))
            gyro = data.get("gyro", (0.0, 0.0, 0.0))
            tap_detected = data.get("tap_detected", False)
            stability = data.get("stability", "unknown")
            sensor_activity = data.get("activity", "unknown")
            
            # Keep a window of values for smoothing
            self.stability_window.append(stability)
            if len(self.stability_window) > self.window_size:
                self.stability_window.pop(0)
                
            # Calculate acceleration magnitude
            accel_magnitude = math.sqrt(
                linear_acceleration[0]**2 + 
                linear_acceleration[1]**2 + 
                linear_acceleration[2]**2
            )
            
            # Keep a window of acceleration values
            self.accel_window.append(accel_magnitude)
            if len(self.accel_window) > self.window_size:
                self.accel_window.pop(0)
            
            # Classify activity based on sensor data
            activity = self._classify_activity(
                acceleration, 
                linear_acceleration, 
                gyro, 
                tap_detected, 
                stability, 
                sensor_activity
            )
            
            # Only publish and print if activity changed
            if activity != self.current_activity or self.activity_confidence > 0.8:
                self.previous_activity = self.current_activity
                self.current_activity = activity
                
                # Log and print the detected activity
                self.logger.info(f"Activity detected: {activity} (confidence: {self.activity_confidence:.2f})")
                self._print_activity_info(activity, acceleration, linear_acceleration, gyro)
                
                # Publish activity detected event
                await self.publish({
                    "type": "activity_detected",
                    "activity": activity,
                    "previous_activity": self.previous_activity,
                    "confidence": self.activity_confidence,
                    "producer_name": "move_activity"
                })
    
    def _classify_activity(self, 
                          acceleration: Tuple[float, float, float],
                          linear_acceleration: Tuple[float, float, float],
                          gyro: Tuple[float, float, float],
                          tap_detected: bool,
                          stability: str,
                          sensor_activity: str) -> str:
        """
        Classify the activity based on the sensor data.
        
        This method uses a combination of the accelerometer, gyroscope, and the BNO085's
        built-in activity classifier to determine the current activity.
        
        Args:
            acceleration: Raw acceleration values (x, y, z) in m/s^2
            linear_acceleration: Linear acceleration with gravity removed (x, y, z) in m/s^2
            gyro: Gyroscope values (x, y, z) in rad/s
            tap_detected: Whether a tap was detected
            stability: Stability classifier value from the BNO085
            sensor_activity: Activity classifier value from the BNO085
            
        Returns:
            str: The classified activity
        """
        # Check if the sensor provides its own activity classification
        if sensor_activity != "unknown":
            self.activity_confidence = 0.9
            return sensor_activity
            
        # Calculate acceleration magnitude (removing gravity)
        accel_magnitude = math.sqrt(
            linear_acceleration[0]**2 + 
            linear_acceleration[1]**2 + 
            linear_acceleration[2]**2
        )
        
        # Calculate average acceleration over the window
        avg_accel = sum(self.accel_window) / len(self.accel_window) if self.accel_window else accel_magnitude
        
        # Calculate gyro magnitude
        gyro_magnitude = math.sqrt(gyro[0]**2 + gyro[1]**2 + gyro[2]**2)
        
        # Get the most common stability in the window
        stability_counter = {}
        for s in self.stability_window:
            if s in stability_counter:
                stability_counter[s] += 1
            else:
                stability_counter[s] = 1
                
        most_common_stability = max(stability_counter.items(), key=lambda x: x[1])[0] if stability_counter else "unknown"
        
        # Classification logic
        if most_common_stability == "on-table" or most_common_stability == "stationary":
            self.activity_confidence = 0.9
            return "still"
        elif tap_detected:
            self.activity_confidence = 0.7
            return "tapped"
        elif avg_accel > 10.0:  # High acceleration threshold for running
            self.activity_confidence = min(0.6 + (avg_accel - 10.0) / 10.0, 0.95)
            return "running"
        elif avg_accel > 3.0:  # Medium acceleration threshold for walking
            self.activity_confidence = min(0.6 + (avg_accel - 3.0) / 10.0, 0.85)
            return "walking"
        elif gyro_magnitude > 1.0:  # Significant rotation
            self.activity_confidence = min(0.6 + (gyro_magnitude - 1.0) / 3.0, 0.85)
            return "rotating"
        elif avg_accel > 1.0:  # Slight movement
            self.activity_confidence = 0.6
            return "moving"
        else:
            # Default to still if no significant motion detected
            self.activity_confidence = 0.7
            return "still"
            
    def _print_activity_info(self, activity: str, 
                           acceleration: Tuple[float, float, float],
                           linear_acceleration: Tuple[float, float, float],
                           gyro: Tuple[float, float, float]):
        """
        Print information about the detected activity.
        
        Args:
            activity: The detected activity
            acceleration: Raw acceleration values (x, y, z) in m/s^2
            linear_acceleration: Linear acceleration with gravity removed (x, y, z) in m/s^2
            gyro: Gyroscope values (x, y, z) in rad/s
        """
        accel_magnitude = math.sqrt(
            linear_acceleration[0]**2 + 
            linear_acceleration[1]**2 + 
            linear_acceleration[2]**2
        )
        
        gyro_magnitude = math.sqrt(gyro[0]**2 + gyro[1]**2 + gyro[2]**2)
        
        print("\n=======================================")
        print(f"DETECTED ACTIVITY: {activity.upper()}")
        print(f"Confidence: {self.activity_confidence:.2f}")
        print("---------------------------------------")
        print(f"Acceleration magnitude: {accel_magnitude:.2f} m/s^2")
        print(f"Gyro magnitude: {gyro_magnitude:.2f} rad/s")
        print(f"Recent stability values: {', '.join(self.stability_window[-3:])}")
        print("=======================================\n") 