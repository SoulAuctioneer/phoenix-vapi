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
    """
    States for motion pattern detection.
    Represents the current physical state of the device at a single moment.
    Part of a state machine where only one state is active at any time.
    Updated with every sensor reading.
    """
    IDLE = auto()
    ACCELERATION = auto()
    FREE_FALL = auto()
    IMPACT = auto()
    ROLLING = auto()
    LINEAR_MOTION = auto()  # Movement in a straight line
    HELD_STILL = auto()  # Being held by a human attempting to keep it still

class MotionPattern(Enum):
    """
    Types of detectable motion patterns
    Represents a higher-level recognized gesture or activity.
    Multiple patterns can be detected simultaneously.
    Based on sequences of states and motion history.
    Used for application-level gesture recognition (the "what" the user is doing).
    Detected when specific criteria are met across multiple readings.
    """
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
        self.pattern_history = deque(maxlen=5)  # Store recent pattern detections for sequence recognition
        
        # Thresholds for pattern detection
        self.throw_acceleration_threshold = 10.0  # m/s^2
        self.free_fall_threshold = 3.5  # m/s^2, increased from 2.0 to better detect short drops
        self.impact_threshold = 8.0  # m/s^2, lowered from 12.0 to better detect catches
        self.arc_rotation_threshold = 1.5  # rad/s, increased from 1.0 to reduce false positives
        self.shake_threshold = 8.0  # m/s^2
        self.rolling_accel_min = 0.5  # m/s^2
        self.rolling_accel_max = 3.0  # m/s^2
        self.rolling_gyro_min = 1.0  # rad/s
        self.rolling_duration = 0.5  # seconds
        
        # Human tremor detection
        self.held_still_max_accel = 1.2  # m/s^2, max acceleration for hand tremor
        self.held_still_min_accel = 0.05  # m/s^2, min acceleration to detect human tremor
        self.held_still_duration = 0.3  # seconds required to confirm HELD_STILL state
        self.held_still_start_time = 0
        self.idle_linear_transitions = 0  # Count IDLE<->LINEAR_MOTION transitions
        self.max_transition_interval = 0.5  # seconds between transitions to be considered tremor
        self.last_transition_time = 0
        
        # Timing parameters
        self.min_free_fall_time = 0.05  # seconds, reduced from 0.15 for shorter drops
        self.max_free_fall_time = 2.0  # seconds
        self.free_fall_start_time = 0
        self.rolling_start_time = 0
        
        # Pattern tracking
        self.throw_detected_time = 0
        self.throw_in_progress = False
        
        # Debugging
        self.consecutive_low_accel = 0  # Count consecutive low acceleration readings
        
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
        
        # Calculate magnitudes with type checking
        accel_magnitude = 0.0
        if isinstance(linear_accel, tuple) and all(isinstance(x, (int, float)) for x in linear_accel):
            accel_magnitude = sqrt(sum(x*x for x in linear_accel))
        else:
            self.logger.warning(f"Invalid linear acceleration data: {linear_accel}")
            
        gyro_magnitude = 0.0
        if isinstance(gyro, tuple) and all(isinstance(x, (int, float)) for x in gyro):
            gyro_magnitude = sqrt(sum(x*x for x in gyro))
        else:
            self.logger.warning(f"Invalid gyro data: {gyro}")
        
        # Update motion state based on current data
        self._update_motion_state(accel_magnitude, gyro_magnitude, current_data['timestamp'])
        
        # Check for specific patterns
        try:
            current_time = time.time()
            
            # For short drops directly from ACCELERATION to IMPACT, add THROW pattern
            if self.motion_state == MotionState.IMPACT and self.throw_in_progress:
                if not any(MotionPattern.THROW.name in patterns for _, patterns in self.pattern_history):
                    detected_patterns.append(MotionPattern.THROW.name)
                    self.logger.debug(f"THROW detected: short drop (ACCEL→IMPACT)")
            
            # Normal throw detection for FREE_FALL state
            elif self._check_throw_pattern():
                detected_patterns.append(MotionPattern.THROW.name)
                self.throw_detected_time = current_time
                self.throw_in_progress = True
                self.logger.debug(f"THROW detected: via free fall")
                
            if self._check_catch_pattern(accel_magnitude):
                detected_patterns.append(MotionPattern.CATCH.name)
                self.throw_in_progress = False
                
            if self._check_arc_swing_pattern():
                # Only detect arc swings when not in free fall to avoid false positives
                if self.motion_state != MotionState.FREE_FALL:
                    detected_patterns.append(MotionPattern.ARC_SWING.name)
                
            if self._check_shake_pattern():
                # Avoid detecting shakes during free fall
                if self.motion_state != MotionState.FREE_FALL:
                    detected_patterns.append(MotionPattern.SHAKE.name)
                
            if self._check_rolling_pattern():
                detected_patterns.append(MotionPattern.ROLLING.name)
                
            # Store patterns in history for sequence detection
            if detected_patterns:
                self.pattern_history.append((current_time, detected_patterns))
                
            # Expire throw in progress after maximum free fall time
            if self.throw_in_progress and (current_time - self.throw_detected_time > self.max_free_fall_time):
                self.throw_in_progress = False
                
        except Exception as e:
            # Log detailed information about the exception with context
            self.logger.error(f"Error detecting motion patterns: {e}", exc_info=True)
            self.logger.debug(f"Current data that caused error: {current_data}")
            # Could track error frequency or report if errors become too common
            
        return detected_patterns
        
    def _update_motion_state(self, accel_magnitude: float, gyro_magnitude: float, timestamp: float):
        """
        Update the motion state machine based on current acceleration and rotation.
        
        Args:
            accel_magnitude: Magnitude of linear acceleration
            gyro_magnitude: Magnitude of angular velocity
            timestamp: Current timestamp
        """
        # Log state transitions for debugging
        previous_state = self.motion_state
        current_time = timestamp
        
        # State transitions
        if self.motion_state == MotionState.IDLE:
            if accel_magnitude > self.throw_acceleration_threshold:
                self.motion_state = MotionState.ACCELERATION
                self.free_fall_start_time = timestamp  # Set this here for very short drops
                self.logger.debug(f"IDLE → ACCELERATION: accel={accel_magnitude:.2f}")
            elif self._check_rolling_criteria() and not self._check_linear_motion():
                # Only enter ROLLING if rotation is around a dominant axis (not linear motion)
                self.motion_state = MotionState.ROLLING
                self.rolling_start_time = timestamp
                self.logger.debug(f"IDLE → ROLLING: accel={accel_magnitude:.2f}, gyro={gyro_magnitude:.2f}")
            elif accel_magnitude > self.rolling_accel_min and self._check_linear_motion():
                # Check for hand tremor pattern (repeated transitions between IDLE and LINEAR_MOTION)
                if hasattr(self, 'last_state_was_linear') and self.last_state_was_linear:
                    # We're oscillating between IDLE and LINEAR_MOTION, likely hand tremor
                    self.motion_state = MotionState.HELD_STILL
                    self.last_held_still_time = timestamp
                    self.logger.debug(f"IDLE → HELD_STILL (oscillation): accel={accel_magnitude:.2f}")
                else:
                    # Normal transition to LINEAR_MOTION
                    self.motion_state = MotionState.LINEAR_MOTION
                    self.last_state_was_linear = True
                    self.logger.debug(f"IDLE → LINEAR_MOTION: accel={accel_magnitude:.2f}, gyro={gyro_magnitude:.2f}")
            else:
                self.last_state_was_linear = False
                
        elif self.motion_state == MotionState.ACCELERATION:
            # Track consecutive low acceleration readings to detect short free falls
            if accel_magnitude < self.free_fall_threshold:
                self.consecutive_low_accel += 1
                # Require at least 2 consecutive readings below threshold to confirm free fall
                if self.consecutive_low_accel >= 2:
                    self.motion_state = MotionState.FREE_FALL
                    self.free_fall_start_time = timestamp
                    self.logger.debug(f"ACCELERATION → FREE_FALL: accel={accel_magnitude:.2f}")
                    self.consecutive_low_accel = 0
            else:
                self.consecutive_low_accel = 0
                if accel_magnitude > self.impact_threshold:
                    # If a rapid acceleration is followed by an even higher acceleration, 
                    # it might be an impact without free fall (e.g., quick tap or very short drop)
                    self.motion_state = MotionState.IMPACT
                    # Log this special transition
                    self.logger.debug(f"ACCELERATION → IMPACT (direct): accel={accel_magnitude:.2f}")
                    # For very short drops, we might not see free fall state, so force throw detection
                    self.throw_in_progress = True
                    self.throw_detected_time = timestamp
                elif self._check_rolling_criteria() and not self._check_linear_motion():
                    self.motion_state = MotionState.ROLLING
                    self.rolling_start_time = timestamp
                    self.logger.debug(f"ACCELERATION → ROLLING: accel={accel_magnitude:.2f}, gyro={gyro_magnitude:.2f}")
                elif accel_magnitude < self.throw_acceleration_threshold and self._check_linear_motion():
                    # Transition to LINEAR_MOTION if acceleration decreases but linear movement continues
                    self.motion_state = MotionState.LINEAR_MOTION
                    self.logger.debug(f"ACCELERATION → LINEAR_MOTION: accel={accel_magnitude:.2f}, gyro={gyro_magnitude:.2f}")
                
        elif self.motion_state == MotionState.FREE_FALL:
            free_fall_duration = timestamp - self.free_fall_start_time
            
            if accel_magnitude > self.impact_threshold:
                self.motion_state = MotionState.IMPACT
                self.logger.debug(f"FREE_FALL → IMPACT: accel={accel_magnitude:.2f} duration={free_fall_duration:.3f}s")
            elif free_fall_duration > self.max_free_fall_time:
                # Too long in free fall, reset to idle
                self.motion_state = MotionState.IDLE
                self.logger.debug(f"FREE_FALL → IDLE (timeout): duration={free_fall_duration:.3f}s")
                
        elif self.motion_state == MotionState.IMPACT:
            # Impact is a transient state, move to IDLE after detection
            # Adding a small delay before transitioning to IDLE to ensure the impact is fully processed
            if accel_magnitude < self.throw_acceleration_threshold:
                self.motion_state = MotionState.IDLE
                self.logger.debug(f"IMPACT → IDLE: accel={accel_magnitude:.2f}")
            
        elif self.motion_state == MotionState.ROLLING:
            # Check if still rolling - need both acceleration in range AND rotation around dominant axis
            if not self._check_rolling_criteria():
                if self._check_linear_motion() and accel_magnitude > self.rolling_accel_min:
                    self.motion_state = MotionState.LINEAR_MOTION
                    self.logger.debug(f"ROLLING → LINEAR_MOTION: accel={accel_magnitude:.2f}, gyro={gyro_magnitude:.2f}")
                else:
                    self.motion_state = MotionState.IDLE
                    self.logger.debug(f"ROLLING → IDLE: accel={accel_magnitude:.2f}, gyro={gyro_magnitude:.2f}")
        
        elif self.motion_state == MotionState.LINEAR_MOTION:
            # Exit LINEAR_MOTION if acceleration drops or motion is no longer linear
            if accel_magnitude < self.rolling_accel_min:
                # Check for hand tremor pattern (repeated transitions between IDLE and LINEAR_MOTION)
                if hasattr(self, 'last_state_was_idle') and self.last_state_was_idle:
                    # We're oscillating between IDLE and LINEAR_MOTION, likely hand tremor
                    self.motion_state = MotionState.HELD_STILL
                    self.last_held_still_time = timestamp
                    self.logger.debug(f"LINEAR_MOTION → HELD_STILL (oscillation): accel={accel_magnitude:.2f}")
                else:
                    # Normal transition to IDLE
                    self.motion_state = MotionState.IDLE
                    self.last_state_was_idle = True
                    self.logger.debug(f"LINEAR_MOTION → IDLE: accel={accel_magnitude:.2f}")
            elif accel_magnitude > self.throw_acceleration_threshold:
                self.motion_state = MotionState.ACCELERATION
                self.last_state_was_idle = False
                self.logger.debug(f"LINEAR_MOTION → ACCELERATION: accel={accel_magnitude:.2f}")
            elif self._check_rolling_criteria() and not self._check_linear_motion():
                self.motion_state = MotionState.ROLLING
                self.last_state_was_idle = False
                self.rolling_start_time = timestamp
                self.logger.debug(f"LINEAR_MOTION → ROLLING: accel={accel_magnitude:.2f}, gyro={gyro_magnitude:.2f}")
            else:
                self.last_state_was_idle = False
        
        elif self.motion_state == MotionState.HELD_STILL:
            # Define thresholds for exiting HELD_STILL state
            held_still_max_duration = 30.0  # Maximum time to stay in HELD_STILL without reevaluation
            held_still_time = timestamp - self.last_held_still_time
            
            if accel_magnitude > self.throw_acceleration_threshold:
                # Strong acceleration - exit to ACCELERATION
                self.motion_state = MotionState.ACCELERATION
                self.logger.debug(f"HELD_STILL → ACCELERATION: accel={accel_magnitude:.2f}")
            elif accel_magnitude < 0.1:
                # Very low acceleration - device might be on a stable surface
                self.motion_state = MotionState.IDLE
                self.logger.debug(f"HELD_STILL → IDLE (very stable): accel={accel_magnitude:.2f}")
            elif accel_magnitude > 2.0 and self._check_linear_motion():
                # Definite movement that's not just tremor
                self.motion_state = MotionState.LINEAR_MOTION
                self.logger.debug(f"HELD_STILL → LINEAR_MOTION (definite movement): accel={accel_magnitude:.2f}")
            elif self._check_rolling_criteria():
                # Rotation detected
                self.motion_state = MotionState.ROLLING
                self.rolling_start_time = timestamp
                self.logger.debug(f"HELD_STILL → ROLLING: accel={accel_magnitude:.2f}, gyro={gyro_magnitude:.2f}")
            elif held_still_time > held_still_max_duration:
                # Timeout - reevaluate the state
                if accel_magnitude < self.rolling_accel_min:
                    self.motion_state = MotionState.IDLE
                    self.logger.debug(f"HELD_STILL → IDLE (timeout): accel={accel_magnitude:.2f}")
                else:
                    self.last_held_still_time = timestamp  # Reset timer but stay in HELD_STILL
                
        # Log state transition if changed
        if previous_state != self.motion_state:
            self.logger.debug(f"Motion state change: {previous_state.name} → {self.motion_state.name} " +
                             f"(accel={accel_magnitude:.2f}, gyro={gyro_magnitude:.2f})")
            
            # Reset tracking variables when changing states
            if self.motion_state != MotionState.HELD_STILL:
                self.last_state_was_idle = False
                self.last_state_was_linear = False
        
    def _check_rolling_criteria(self) -> bool:
        """
        Check if the current motion meets basic rolling criteria based on acceleration and gyro.
        
        Returns:
            bool: True if basic rolling criteria are met
        """
        # Get the latest motion data
        if len(self.motion_history) < 2:
            return False
            
        latest = self.motion_history[-1]
        
        # Extract acceleration and gyro values
        accel = latest.get("linear_acceleration", (0, 0, 0))
        gyro = latest.get("gyro", (0, 0, 0))
        
        if not (isinstance(accel, tuple) and len(accel) == 3 and 
                isinstance(gyro, tuple) and len(gyro) == 3):
            return False
            
        # Calculate magnitudes
        accel_magnitude = sqrt(accel[0]**2 + accel[1]**2 + accel[2]**2)
        gyro_magnitude = sqrt(gyro[0]**2 + gyro[1]**2 + gyro[2]**2)
        
        # Check if within rolling criteria
        return (self.rolling_accel_min < accel_magnitude < self.rolling_accel_max and 
                gyro_magnitude > self.rolling_gyro_min)
    
    def _check_linear_motion(self) -> bool:
        """
        Check if the current motion is primarily linear (rather than rotational).
        
        Linear motion typically has:
        1. Consistent acceleration direction
        2. Low rotation around the acceleration axis
        3. No dominant rotation axis
        
        Returns:
            bool: True if motion appears to be linear rather than rolling
        """
        if len(self.motion_history) < 3:
            return False
            
        # Get recent gyro readings
        gyro_readings = [entry.get("gyro", (0, 0, 0)) for entry in list(self.motion_history)[-3:]
                        if isinstance(entry.get("gyro", (0, 0, 0)), tuple) 
                        and len(entry.get("gyro", (0, 0, 0))) == 3]
        
        if len(gyro_readings) < 3:
            return False
            
        # Calculate dominant rotation axis
        axis_totals = [0, 0, 0]
        for gyro in gyro_readings:
            for i in range(3):
                axis_totals[i] += abs(gyro[i])
        
        # Find the dominant axis and its ratio
        max_axis = max(axis_totals)
        sum_total = sum(axis_totals) + 0.0001  # Avoid division by zero
        dominant_ratio = max_axis / sum_total
        
        # Get acceleration direction consistency
        accel_readings = [entry.get("linear_acceleration", (0, 0, 0)) for entry in list(self.motion_history)[-3:]
                       if isinstance(entry.get("linear_acceleration", (0, 0, 0)), tuple) 
                       and len(entry.get("linear_acceleration", (0, 0, 0))) == 3]
        
        # Check if acceleration direction is consistent (indicating linear motion)
        direction_consistent = True
        if len(accel_readings) >= 2:
            # Find main direction of first reading
            first_accel = accel_readings[0]
            main_component = max(range(3), key=lambda i: abs(first_accel[i]))
            main_direction = 1 if first_accel[main_component] > 0 else -1
            
            # Check if direction stays consistent
            for accel in accel_readings[1:]:
                if (accel[main_component] * main_direction) < 0:  # Direction changed
                    direction_consistent = False
                    break
        
        # Linear motion typically has:
        # 1. No clear dominant rotation axis (dominant_ratio < 0.6)
        # 2. OR consistent acceleration direction
        return (dominant_ratio < 0.6) or direction_consistent
        
    def _check_throw_pattern(self) -> bool:
        """
        Check if a throw pattern has been detected.
        
        A throw consists of:
        1. Initial acceleration spike
        2. Period of free fall (near-zero acceleration)
        
        Returns:
            bool: True if throw pattern detected
        """
        if len(self.motion_history) < 3:  # Reduced from 5 to better detect short throws
            return False
            
        # Check state sequence for a throw
        if self.motion_state == MotionState.FREE_FALL:
            # Make sure we can safely access the latest entry
            if len(self.motion_history) > 0 and 'timestamp' in self.motion_history[-1]:
                timestamp = self.motion_history[-1]['timestamp']
                free_fall_duration = timestamp - self.free_fall_start_time
                
                # Log free fall data for debugging
                self.logger.debug(f"Free fall duration: {free_fall_duration:.3f}s, min required: {self.min_free_fall_time:.3f}s")
                
                # Minimum free fall time to be considered a throw - reduced for shorter drops
                if free_fall_duration > self.min_free_fall_time:
                    # Check for significant vertical movement (typical in throws/drops)
                    accel_data = [entry.get("linear_acceleration", (0, 0, 0)) for entry in list(self.motion_history)[-3:]]
                    
                    # For debugging
                    accel_info = ", ".join([f"({a[0]:.1f},{a[1]:.1f},{a[2]:.1f})" for a in accel_data])
                    self.logger.debug(f"Checking vertical movement in free fall. Accel data: {accel_info}")
                    
                    return True
                
        return False
        
    def _check_catch_pattern(self, current_accel_magnitude: float) -> bool:
        """
        Check if a catch pattern has been detected.
        
        A catch consists of:
        1. Period of free fall (or very short drop with direct ACCELERATION → IMPACT transition)
        2. Sudden deceleration (impact)
        
        Args:
            current_accel_magnitude: Current acceleration magnitude
            
        Returns:
            bool: True if catch pattern detected
        """
        # A catch is detected if:
        # 1. We're in IMPACT state, indicating sudden deceleration
        # 2. There was a throw detected recently (within max_free_fall_time) OR
        #    We came directly from ACCELERATION state (very short drop)
        if self.motion_state == MotionState.IMPACT:
            # Check if we had a throw in progress
            if self.throw_in_progress:
                self.logger.debug(f"CATCH detected: throw was in progress")
                return True
            
            # Also check pattern history for recent THROW (backup method)
            current_time = time.time()
            for timestamp, patterns in self.pattern_history:
                if (current_time - timestamp) <= self.max_free_fall_time:
                    if MotionPattern.THROW.name in patterns:
                        self.logger.debug(f"CATCH detected: via pattern history")
                        return True
            
        return False
        
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
            
        # Don't detect arc swings during free fall
        if self.motion_state == MotionState.FREE_FALL:
            return False
            
        # Use game rotation quaternion for smooth rotation detection
        # Convert to list first for safety and filter out invalid data
        rotations = [entry.get("game_rotation", (0, 0, 0, 1)) for entry in list(self.motion_history)
                    if isinstance(entry.get("game_rotation", (0, 0, 0, 1)), tuple) 
                    and len(entry.get("game_rotation", (0, 0, 0, 1))) == 4]
        
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
            
            # If total rotation is significant - increased threshold to reduce false positives
            if total_rotation > self.arc_rotation_threshold:
                # Check that rotation is smooth (not erratic as in shaking)
                # For a smooth rotation, the angle differences should be relatively consistent
                angles = []
                for i in range(len(rotations) - 1):
                    q1 = rotations[i]
                    q2 = rotations[i+1]
                    dot_product = q1[0]*q2[0] + q1[1]*q2[1] + q1[2]*q2[2] + q1[3]*q2[3]
                    angle = 2 * acos(min(1.0, abs(dot_product)))
                    angles.append(angle)
                
                # Calculate the standard deviation of angles to check smoothness
                if len(angles) >= 2:
                    mean_angle = sum(angles) / len(angles)
                    variance = sum((angle - mean_angle) ** 2 for angle in angles) / len(angles)
                    std_dev = sqrt(variance)
                    
                    # If the standard deviation is low, rotation is smooth
                    smoothness_threshold = 0.3  # Radians
                    if std_dev < smoothness_threshold:
                        return True
                
        return False
        
    def _check_shake_pattern(self) -> bool:
        """
        Check if a shake pattern has been detected.
        
        A shake involves:
        1. Rapid alternating acceleration in opposite directions
        2. Multiple reversals in a short time
        3. Sufficient acceleration magnitude to be considered significant
        
        Returns:
            bool: True if shake detected
        """
        if len(self.motion_history) < 6:
            return False
        
        # Don't detect shake during free fall
        if self.motion_state == MotionState.FREE_FALL:
            return False
            
        # Get recent acceleration values - convert deque to list before slicing for safety
        # Filter out invalid acceleration data in the comprehension
        accelerations = [entry.get("linear_acceleration", (0, 0, 0)) for entry in list(self.motion_history)[-6:]
                         if isinstance(entry.get("linear_acceleration", (0, 0, 0)), tuple) 
                         and len(entry.get("linear_acceleration", (0, 0, 0))) == 3]
        
        # If we don't have enough valid data points, return False
        if len(accelerations) < 3:
            self.logger.warning("Not enough valid acceleration data points for shake detection")
            return False
            
        # Calculate the average acceleration magnitude to filter out small movements
        accel_magnitudes = []
        for accel in accelerations:
            try:
                magnitude = sqrt(accel[0]**2 + accel[1]**2 + accel[2]**2)
                accel_magnitudes.append(magnitude)
            except (TypeError, IndexError):
                continue
                
        if not accel_magnitudes:
            return False
            
        avg_magnitude = sum(accel_magnitudes) / len(accel_magnitudes)
        
        # Require a minimum average acceleration magnitude
        min_shake_magnitude = 3.0  # Increased from 2.0 to reduce false positives
        
        if avg_magnitude < min_shake_magnitude:
            return False
        
        # Count direction changes
        direction_changes = 0
        prev_direction = None
        significant_changes = 0  # Count only significant direction changes
        
        for idx, accel in enumerate(accelerations):
            try:
                # Use the largest component of acceleration as the primary direction
                max_component = max(abs(accel[0]), abs(accel[1]), abs(accel[2]))
                
                # Ignore very small accelerations (noise)
                if max_component < 1.5:  # Increased from 1.0 to reduce false positives
                    continue
                    
                current_direction = None
                for i in range(3):
                    if abs(accel[i]) == max_component:
                        current_direction = 1 if accel[i] > 0 else -1
                        break
                        
                # Count direction changes
                if (prev_direction is not None and 
                    current_direction is not None and 
                    current_direction != prev_direction):
                    direction_changes += 1
                    
                    # Check if this is a significant change
                    if max_component > 4.0:  # Increased from 3.0 to reduce false positives
                        significant_changes += 1
                    
                prev_direction = current_direction
            except (TypeError, IndexError) as e:
                # Log invalid entries instead of silently continuing
                self.logger.error(f"Error processing acceleration data at index {idx}: {e}, data: {accel}")
        
        # Require both overall direction changes and some significant ones
        return direction_changes >= 4 and significant_changes >= 2
        
    def _check_rolling_pattern(self) -> bool:
        """
        Check if a rolling pattern has been detected.
        
        A rolling motion is characterized by:
        1. Moderate but consistent linear acceleration (less than throwing but more than stationary)
        2. Continuous rotation around primarily one axis
        3. Sustained motion for a certain duration
        4. Not exhibiting characteristics of linear motion
        
        Returns:
            bool: True if rolling motion detected
        """
        if len(self.motion_history) < 5:
            return False
            
        # Check if in rolling state
        if self.motion_state == MotionState.ROLLING:
            # Make sure we can safely access the latest entry
            if len(self.motion_history) == 0 or 'timestamp' not in self.motion_history[-1]:
                self.logger.warning("Cannot access timestamp in motion history for rolling detection")
                return False
            
            timestamp = self.motion_history[-1]['timestamp']
            rolling_duration = timestamp - self.rolling_start_time
            
            # Minimum duration to be considered rolling
            if rolling_duration > self.rolling_duration:
                # Check if motion is linear rather than rolling
                if self._check_linear_motion():
                    self.logger.debug("Motion appears to be linear, not rolling")
                    return False
                
                # Get the last 5 valid gyro readings - convert to list first for safety
                # Filter out invalid data in the comprehension
                gyro_readings = [entry.get("gyro", (0, 0, 0)) for entry in list(self.motion_history)[-5:]
                                if isinstance(entry.get("gyro", (0, 0, 0)), tuple) 
                                and len(entry.get("gyro", (0, 0, 0))) == 3]
                
                # If we don't have enough valid readings, return False
                if len(gyro_readings) < 3:
                    self.logger.warning(f"Not enough valid gyro readings for rolling detection. Only found {len(gyro_readings)}")
                    return False
                
                # Find the dominant rotation axis (x, y, or z)
                axis_totals = [0, 0, 0]
                for gyro in gyro_readings:
                    for i in range(3):
                        axis_totals[i] += abs(gyro[i])
                
                # Log the axis data for debugging
                self.logger.debug(f"Rolling axis totals: x={axis_totals[0]:.2f}, y={axis_totals[1]:.2f}, z={axis_totals[2]:.2f}")
                
                dominant_axis = axis_totals.index(max(axis_totals))
                axis_names = ['x', 'y', 'z']
                sum_total = sum(axis_totals) + 0.0001  # Avoid division by zero
                dominant_ratio = axis_totals[dominant_axis] / sum_total
                
                # If one axis dominates the rotation (rolling tends to rotate around one axis)
                # Raise the required ratio from 0.6 to 0.7 to be more strict
                if dominant_ratio > 0.7:  # 70% of rotation is around this axis
                    self.logger.debug(f"Detected rolling around {axis_names[dominant_axis]} axis with ratio {dominant_ratio:.2f}")
                    
                    # Verify consistency of rotation direction around dominant axis
                    last_direction = None
                    direction_changes = 0
                    
                    for gyro in gyro_readings:
                        current_direction = 1 if gyro[dominant_axis] > 0 else -1
                        if last_direction is not None and current_direction != last_direction:
                            direction_changes += 1
                        last_direction = current_direction
                    
                    # True rolling should have consistent rotation direction
                    if direction_changes <= 1:  # Allow at most one direction change
                        return True
                    else:
                        self.logger.debug(f"Too many direction changes ({direction_changes}) for true rolling")
                else:
                    self.logger.debug(f"No dominant rotation axis detected. Dominant axis: {axis_names[dominant_axis]} with ratio {dominant_ratio:.2f}")
                
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