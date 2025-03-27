"""
Accelerometer Manager

This manager provides access to accelerometer data and motion detection functionality.
It abstracts the hardware details by using the BNO085Interface hardware module.

The manager is responsible for:
1. Initializing and managing the hardware connection
2. Providing access to raw sensor data
3. Managing calibration
4. Computing derived metrics (energy, heading, etc.)
5. Detecting motion patterns (throws, arcs, shakes, rolls, etc.)
"""

import logging
from typing import Dict, Any, Tuple, List, Optional, Literal
from hardware.acc_bno085 import BNO085Interface
from math import atan2, sqrt, pi, acos
from config import MoveActivityConfig
from collections import deque
from enum import Enum, auto
import time

class MotionState(Enum):
    """States for motion pattern detection"""
    IDLE = auto()
    ACCELERATION = auto()
    FREE_FALL = auto()
    IMPACT = auto()
    ROLLING = auto()

class MotionPattern(Enum):
    """Types of detectable motion patterns"""
    THROW = auto()
    CATCH = auto()
    ARC_SWING = auto()
    SHAKE = auto()
    DROP = auto()
    ROLLING = auto()

class AccelerometerManager:
    """
    Manager for accelerometer data access and processing.
    
    This class serves as a bridge between hardware and application layers,
    providing access to accelerometer data and motion detection.
    """
    
    def __init__(self):
        """Initialize the AccelerometerManager"""
        self.interface = BNO085Interface()
        self.logger = logging.getLogger(__name__)
        
        # Motion detection state
        self.motion_state = MotionState.IDLE
        self.motion_history = deque(maxlen=20)  # Store recent measurements for pattern detection
        self.detected_patterns = []
        
        # Thresholds for pattern detection
        self.throw_acceleration_threshold = 10.0  # m/s^2
        self.free_fall_threshold = 2.0  # m/s^2
        self.impact_threshold = 12.0  # m/s^2
        self.arc_rotation_threshold = 1.0  # rad/s
        self.shake_threshold = 8.0  # m/s^2
        self.rolling_accel_min = 0.5  # m/s^2
        self.rolling_accel_max = 3.0  # m/s^2
        self.rolling_gyro_min = 1.0  # rad/s
        self.rolling_duration = 0.5  # seconds
        
        # Timing parameters
        self.min_free_fall_time = 0.15  # seconds
        self.max_free_fall_time = 2.0  # seconds
        self.free_fall_start_time = 0
        self.rolling_start_time = 0
        
    def initialize(self) -> bool:
        """
        Initialize the accelerometer hardware.
        
        Returns:
            bool: True if initialization was successful, False otherwise
        """
        return self.interface.initialize()
        
    def deinitialize(self):
        """
        Deinitialize the accelerometer hardware.
        """
        self.interface.deinitialize()
        
    def read_sensor_data(self) -> Dict[str, Any]:
        """
        Read raw sensor data from the accelerometer and detect motion patterns.
        
        Returns:
            Dict[str, Any]: Dictionary containing sensor readings and detected motion patterns
        """
        data = self.interface.read_sensor_data()
        
        # If data contains rotation vector, calculate heading
        if "rotation_vector" in data and len(data["rotation_vector"]) == 4:
            quat_i, quat_j, quat_k, quat_real = data["rotation_vector"]
            data["heading"] = self.find_heading(quat_real, quat_i, quat_j, quat_k)
        
        # Calculate energy level if we have the required data
        if "linear_acceleration" in data and "gyro" in data:
            data["energy"] = self.calculate_energy(
                data["linear_acceleration"], 
                data["gyro"],
                MoveActivityConfig.ACCEL_WEIGHT,
                MoveActivityConfig.GYRO_WEIGHT
            )
            
            # Update motion history and detect patterns
            self._update_motion_history(data)
            detected_patterns = self._detect_motion_patterns(data)
            if detected_patterns:
                data["detected_patterns"] = detected_patterns
                self.detected_patterns = detected_patterns
            
        return data
        
    def _update_motion_history(self, data: Dict[str, Any]):
        """
        Update the history of recent motion data.
        
        Args:
            data: Current sensor data
        """
        # Add timestamp to the data
        data['timestamp'] = time.time()
        
        # Store in history
        self.motion_history.append(data)
        
    def _detect_motion_patterns(self, current_data: Dict[str, Any]) -> List[str]:
        """
        Detect motion patterns based on current data and motion history.
        
        Args:
            current_data: Current sensor readings
            
        Returns:
            List of detected patterns
        """
        detected_patterns = []
        
        # Skip if we don't have enough history yet
        if len(self.motion_history) < 3:
            return detected_patterns
            
        # Extract relevant data
        linear_accel = current_data.get("linear_acceleration", (0, 0, 0))
        gyro = current_data.get("gyro", (0, 0, 0))  # Use gyro data directly
        game_rotation = current_data.get("game_rotation", (0, 0, 0, 1))  # Get game rotation quaternion
        stability = current_data.get("stability", "Unknown")
        
        # Calculate magnitudes
        accel_magnitude = sqrt(sum(x*x for x in linear_accel))
        gyro_magnitude = sqrt(sum(x*x for x in gyro))
        
        # Update motion state based on current data
        self._update_motion_state(accel_magnitude, gyro_magnitude, current_data['timestamp'])
        
        # Check for specific patterns
        if self._check_throw_pattern():
            detected_patterns.append(MotionPattern.THROW.name)
            
        if self._check_catch_pattern(accel_magnitude):
            detected_patterns.append(MotionPattern.CATCH.name)
            
        if self._check_arc_swing_pattern():
            detected_patterns.append(MotionPattern.ARC_SWING.name)
            
        if self._check_shake_pattern():
            detected_patterns.append(MotionPattern.SHAKE.name)
            
        if self._check_rolling_pattern():
            detected_patterns.append(MotionPattern.ROLLING.name)
            
        return detected_patterns
        
    def _update_motion_state(self, accel_magnitude: float, gyro_magnitude: float, timestamp: float):
        """
        Update the motion state machine based on current acceleration and rotation.
        
        Args:
            accel_magnitude: Magnitude of linear acceleration
            gyro_magnitude: Magnitude of angular velocity
            timestamp: Current timestamp
        """
        # State transitions
        if self.motion_state == MotionState.IDLE:
            if accel_magnitude > self.throw_acceleration_threshold:
                self.motion_state = MotionState.ACCELERATION
            elif (self.rolling_accel_min < accel_magnitude < self.rolling_accel_max and 
                  gyro_magnitude > self.rolling_gyro_min):
                self.motion_state = MotionState.ROLLING
                self.rolling_start_time = timestamp
                
        elif self.motion_state == MotionState.ACCELERATION:
            if accel_magnitude < self.free_fall_threshold:
                self.motion_state = MotionState.FREE_FALL
                self.free_fall_start_time = timestamp
            elif (self.rolling_accel_min < accel_magnitude < self.rolling_accel_max and 
                  gyro_magnitude > self.rolling_gyro_min):
                self.motion_state = MotionState.ROLLING
                self.rolling_start_time = timestamp
                
        elif self.motion_state == MotionState.FREE_FALL:
            free_fall_duration = timestamp - self.free_fall_start_time
            
            if accel_magnitude > self.impact_threshold:
                self.motion_state = MotionState.IMPACT
            elif free_fall_duration > self.max_free_fall_time:
                # Too long in free fall, reset to idle
                self.motion_state = MotionState.IDLE
                
        elif self.motion_state == MotionState.IMPACT:
            # Reset to idle after impact
            self.motion_state = MotionState.IDLE
            
        elif self.motion_state == MotionState.ROLLING:
            # Check if still rolling
            if not (self.rolling_accel_min < accel_magnitude < self.rolling_accel_max and 
                   gyro_magnitude > self.rolling_gyro_min):
                self.motion_state = MotionState.IDLE
                
    def _check_throw_pattern(self) -> bool:
        """
        Check if a throw pattern has been detected.
        
        A throw consists of:
        1. Initial acceleration spike
        2. Period of free fall (near-zero acceleration)
        
        Returns:
            bool: True if throw pattern detected
        """
        if len(self.motion_history) < 5:
            return False
            
        # Check state sequence for a throw
        if self.motion_state == MotionState.FREE_FALL:
            # Make sure we can safely access the latest entry
            if len(self.motion_history) > 0 and 'timestamp' in self.motion_history[-1]:
                timestamp = self.motion_history[-1]['timestamp']
                free_fall_duration = timestamp - self.free_fall_start_time
                
                # Minimum free fall time to be considered a throw
                if free_fall_duration > self.min_free_fall_time:
                    return True
                
        return False
        
    def _check_catch_pattern(self, current_accel_magnitude: float) -> bool:
        """
        Check if a catch pattern has been detected.
        
        A catch consists of:
        1. Period of free fall
        2. Sudden deceleration (impact)
        
        Args:
            current_accel_magnitude: Current acceleration magnitude
            
        Returns:
            bool: True if catch pattern detected
        """
        return (self.motion_state == MotionState.IMPACT and 
                any(MotionPattern.THROW.name in self.detected_patterns))
        
    def _check_arc_swing_pattern(self) -> bool:
        """
        Check if an arc swing pattern has been detected.
        
        An arc swing involves:
        1. Significant rotation around one primary axis
        2. Smooth change in orientation over time
        
        Returns:
            bool: True if arc swing detected
        """
        if len(self.motion_history) < 8:
            return False
            
        # Use game rotation quaternion for smooth rotation detection
        rotations = []
        for entry in self.motion_history:
            game_rot = entry.get("game_rotation", (0, 0, 0, 1))
            if isinstance(game_rot, tuple) and len(game_rot) == 4:
                rotations.append(game_rot)
            else:
                # Skip invalid data
                continue
        
        # Check if we have significant rotation around a consistent axis
        # This is a simplified approach - a more sophisticated approach would
        # analyze the quaternion changes more carefully
        if len(rotations) >= 3:
            # Calculate angular velocity between samples
            total_rotation = 0
            for i in range(len(rotations) - 1):
                q1 = rotations[i]
                q2 = rotations[i+1]
                # Simple quaternion difference - approximation
                dot_product = q1[0]*q2[0] + q1[1]*q2[1] + q1[2]*q2[2] + q1[3]*q2[3]
                # Calculate angle using dot product (acos)
                angle = 2 * acos(min(1.0, abs(dot_product)))
                total_rotation += angle
            
            # If total rotation is significant
            if total_rotation > self.arc_rotation_threshold:
                return True
                
        return False
        
    def _check_shake_pattern(self) -> bool:
        """
        Check if a shake pattern has been detected.
        
        A shake involves:
        1. Rapid alternating acceleration in opposite directions
        2. Multiple reversals in a short time
        
        Returns:
            bool: True if shake detected
        """
        if len(self.motion_history) < 6:
            return False
            
        # Get recent acceleration values
        accelerations = [entry.get("linear_acceleration", (0, 0, 0)) for entry in self.motion_history[-6:]]
        
        # Count direction changes
        direction_changes = 0
        prev_direction = None
        
        for accel in accelerations:
            # Use the largest component of acceleration as the primary direction
            max_component = max(abs(accel[0]), abs(accel[1]), abs(accel[2]))
            current_direction = None
            for i in range(3):
                if abs(accel[i]) == max_component:
                    current_direction = 1 if accel[i] > 0 else -1
                    break
                    
            # Count direction changes
            if prev_direction is not None and current_direction is not None and current_direction != prev_direction:
                direction_changes += 1
                
            prev_direction = current_direction
            
        # If we have multiple rapid direction changes and high acceleration
        return direction_changes >= 3
        
    def _check_rolling_pattern(self) -> bool:
        """
        Check if a rolling pattern has been detected.
        
        A rolling motion is characterized by:
        1. Moderate but consistent linear acceleration (less than throwing but more than stationary)
        2. Continuous rotation around primarily one axis
        3. Sustained motion for a certain duration
        4. Optional: rotation axis perpendicular to acceleration direction
        
        Returns:
            bool: True if rolling motion detected
        """
        if len(self.motion_history) < 5:
            return False
            
        # Check if in rolling state
        if self.motion_state == MotionState.ROLLING:
            timestamp = self.motion_history[-1]['timestamp']
            rolling_duration = timestamp - self.rolling_start_time
            
            # Minimum duration to be considered rolling
            if rolling_duration > self.rolling_duration:
                # Analyze gyro data to verify consistent rotation axis
                gyro_readings = []
                # Get the last 5 valid gyro readings
                for entry in list(self.motion_history)[-5:]:
                    gyro = entry.get("gyro", (0, 0, 0))
                    if isinstance(gyro, tuple) and len(gyro) == 3:
                        gyro_readings.append(gyro)
                
                # If we don't have enough valid readings, return False
                if len(gyro_readings) < 3:
                    return False
                
                # Find the dominant rotation axis (x, y, or z)
                axis_totals = [0, 0, 0]
                for gyro in gyro_readings:
                    for i in range(3):
                        axis_totals[i] += abs(gyro[i])
                
                dominant_axis = axis_totals.index(max(axis_totals))
                dominant_ratio = axis_totals[dominant_axis] / (sum(axis_totals) + 0.0001)
                
                # If one axis dominates the rotation (rolling tends to rotate around one axis)
                if dominant_ratio > 0.6:  # 60% of rotation is around this axis
                    return True
                
        return False

    def find_heading(self, dqw: float, dqx: float, dqy: float, dqz: float) -> float:
        """
        Calculate heading from quaternion values.
        
        This function converts quaternion values to heading in degrees (0-360 clockwise).
        The heading is calculated using the rotation vector quaternion values.
        
        Args:
            dqw (float): Real component of quaternion
            dqx (float): i component of quaternion
            dqy (float): j component of quaternion
            dqz (float): k component of quaternion
            
        Returns:
            float: Heading in degrees (0-360 clockwise)
        """
        # Normalize quaternion
        norm = sqrt(dqw * dqw + dqx * dqx + dqy * dqy + dqz * dqz)
        dqw = dqw / norm
        dqx = dqx / norm
        dqy = dqy / norm
        dqz = dqz / norm

        # Calculate heading using quaternion to Euler angle conversion
        ysqr = dqy * dqy
        t3 = +2.0 * (dqw * dqz + dqx * dqy)
        t4 = +1.0 - 2.0 * (ysqr + dqz * dqz)
        yaw_raw = atan2(t3, t4)
        yaw = yaw_raw * 180.0 / pi
        
        # Convert to 0-360 clockwise
        if yaw > 0:
            yaw = 360 - yaw
        else:
            yaw = abs(yaw)
            
        return yaw
    
    def calculate_energy(self, linear_acceleration: Tuple[float, float, float], 
                         gyro: Tuple[float, float, float], 
                         accel_weight: float = MoveActivityConfig.ACCEL_WEIGHT, 
                         gyro_weight: float = MoveActivityConfig.GYRO_WEIGHT) -> float:
        """
        Calculate movement energy level (0-1) based on acceleration and rotation.
        
        This provides a normalized measure of how much the device is moving,
        combining both linear acceleration and rotational movement.
        
        Args:
            linear_acceleration: Linear acceleration values (x, y, z) in m/s^2
            gyro: Gyroscope values (x, y, z) in rad/s
            accel_weight: Weight given to acceleration component (default from MoveActivityConfig)
            gyro_weight: Weight given to gyroscope component (default from MoveActivityConfig)
            
        Returns:
            float: Movement energy level from 0 (still) to 1 (very active)
        """
        # Calculate acceleration magnitude
        accel_magnitude = sqrt(
            linear_acceleration[0]**2 + 
            linear_acceleration[1]**2 + 
            linear_acceleration[2]**2
        )
        
        # Normalize acceleration (assuming max acceleration of 20 m/s^2)
        max_accel = 20.0  # m/s^2
        accel_energy = min(1.0, accel_magnitude / max_accel)
        
        # Calculate rotation magnitude
        gyro_magnitude = sqrt(gyro[0]**2 + gyro[1]**2 + gyro[2]**2)
        
        # Normalize rotation (assuming max rotation of 10 rad/s)
        max_gyro = 10.0  # rad/s
        gyro_energy = min(1.0, gyro_magnitude / max_gyro)
        
        # Combine energies with weights
        return (accel_energy * accel_weight + gyro_energy * gyro_weight)

    def detect_free_fall(self, linear_acceleration: Tuple[float, float, float]) -> bool:
        """
        Detect if the device is in free fall.
        
        Free fall is characterized by very low linear acceleration magnitude,
        as gravity is effectively cancelled out during free fall.
        
        Args:
            linear_acceleration: Linear acceleration values (x, y, z) in m/s^2
            
        Returns:
            bool: True if device appears to be in free fall
        """
        # Calculate acceleration magnitude
        accel_magnitude = sqrt(
            linear_acceleration[0]**2 + 
            linear_acceleration[1]**2 + 
            linear_acceleration[2]**2
        )
        
        # In free fall, acceleration should be very close to zero
        return accel_magnitude < self.free_fall_threshold
        
    def get_motion_state(self) -> str:
        """
        Get the current motion state.
        
        Returns:
            str: Current motion state name
        """
        return self.motion_state.name
        
    def get_recent_patterns(self) -> List[str]:
        """
        Get recently detected motion patterns.
        
        Returns:
            List[str]: Names of recently detected patterns
        """
        return self.detected_patterns

    async def check_and_calibrate(self) -> bool:
        """
        Check calibration status and perform calibration if needed.
        
        Returns:
            bool: True if calibration is good, False otherwise
        """
        return await self.interface.check_and_calibrate()
        
    def print_data(self, data: Dict[str, Any]):
        """
        Print sensor data to console for debugging.
        
        Args:
            data: Sensor data dictionary to print
        """
        for key, value in data.items():
            if isinstance(value, tuple):
                print(f"{key}:")
                for i, val in enumerate(value):
                    print(f"{i}: {val}")
            else:
                print(f"{key}: {value}")
        
        # Already included in the data dictionary
        print("")