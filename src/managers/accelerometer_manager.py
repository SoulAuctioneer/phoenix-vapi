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

Core Concepts:
- Motion State (`MotionState` enum): Represents the *instantaneous* physical
  state of the device (e.g., IDLE, ACCELERATING, FREE_FALL). Only one state
  is active at a time. Updated on every sensor reading via `_update_motion_state`.
  Transitions depend on sensor magnitudes (acceleration, gyro) exceeding or
  falling below defined thresholds.
- Motion Pattern (`MotionPattern` enum): Represents a *recognized gesture* or
  activity over a period (e.g., THROW, CATCH, SHAKE, ROLL). Multiple patterns
  can be detected. Detected in `_detect_motion_patterns` based on sequences
  of motion states, sensor data history (`motion_history`), and specific
  criteria defined in `_check_*` helper methods (e.g., duration, magnitude,
  rotation consistency).

Motion State Machine (`_update_motion_state`):
- Takes current acceleration and gyro magnitudes and the timestamp.
- Compares these values against thresholds (e.g., `throw_acceleration_threshold`,
  `free_fall_threshold`, `impact_threshold`, `rolling_accel_min/max`,
  `rolling_gyro_min`, `held_still_min/max_accel`).
- Transitions the `self.motion_state` based on the comparisons and the *current* state.
  For example:
    - `IDLE` -> `ACCELERATION` if accel exceeds `throw_acceleration_threshold`.
    - `ACCELERATION` -> `FREE_FALL` if accel drops below `free_fall_threshold`.
    - `FREE_FALL` -> `IMPACT` if accel spikes above `impact_threshold`.
    - `IMPACT` -> `IDLE` or `HELD_STILL` after accel stabilizes below `impact_exit_threshold` for a delay.
    - `IDLE`/`ACCELERATION`/`LINEAR_MOTION`/`HELD_STILL` -> `ROLLING` if rolling criteria (`_check_rolling_criteria`) are met (moderate accel, significant gyro) and it's not linear motion (`_check_linear_motion`).
    - `IDLE`/`ACCELERATION`/`ROLLING`/`HELD_STILL` -> `LINEAR_MOTION` if linear criteria (`_check_linear_motion`) are met (low gyro, consistent accel direction) and accel is above minimum.
    - `IDLE`/`IMPACT`/`ROLLING`/`LINEAR_MOTION` -> `HELD_STILL` if accel is within the low `held_still` band for a minimum duration.
- Manages timers (`free_fall_start_time`, `rolling_start_time`, `held_still_start_time`, `impact_exit_timer`) to track durations needed for state transitions or pattern detection.

Motion Pattern Detection (`_detect_motion_patterns`):
- Called after the motion state is updated.
- Uses the current `self.motion_state` and recent data in `self.motion_history`.
- Calls specific `_check_*_pattern` methods:
    - `_check_throw_pattern`: Looks for `FREE_FALL` state lasting longer than `min_free_fall_time`. Also handles very short throws detected via `ACCELERATION` -> `IMPACT`. Sets `throw_in_progress` flag.
    - `_check_catch_pattern`: Looks for `IMPACT` state while `throw_in_progress` is true. Uses `catch_detected_last_cycle` flag to ensure `throw_in_progress` isn't cleared prematurely.
    - `_check_arc_swing_pattern`: Uses `game_rotation` history to detect significant, smooth rotation (low standard deviation of rotation angles) above a threshold, excluding `ROLLING`, `FREE_FALL` or `IMPACT` states.
    - `_check_shake_pattern`: Looks for rapid, significant acceleration reversals over a short history, excluding `ROLLING`, `FREE_FALL` or `IMPACT` states.
    - `_check_rolling_pattern`: Requires `ROLLING` state for a minimum `rolling_duration`, checks for a dominant rotation axis and consistent direction, and ensures it's not mistaken for `LINEAR_MOTION`.
- Stores detected patterns in `self.detected_patterns` and `self.pattern_history`.
- Calculates `newly_detected_patterns` by comparing current patterns to the previous cycle's.

Other Features:
- Calculates heading from the rotation vector quaternion (`find_heading`).
- Calculates a normalized movement energy level (`calculate_energy`).
- Provides calibration checks via the hardware interface (`check_and_calibrate`).
- Maintains history buffers (`motion_history`, `pattern_history`) using `deque` for efficient fixed-size storage.
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
    IDLE = auto()           # Device is relatively stationary or motion is below thresholds
    ACCELERATION = auto()   # Significant acceleration detected, possibly start of a throw or other energetic movement
    FREE_FALL = auto()      # Near-zero acceleration, indicating the device is likely falling
    IMPACT = auto()         # Sharp spike in acceleration, usually after free fall (catch) or hitting a surface
    ROLLING = auto()        # Moderate acceleration with significant rotation, suggesting rolling on a surface
    LINEAR_MOTION = auto()  # Movement primarily in one direction with low rotation
    HELD_STILL = auto()     # Low, stable acceleration within human hand-tremor range, held relatively still by a user

class MotionPattern(Enum):
    """
    Types of detectable motion patterns
    Represents a higher-level recognized gesture or activity.
    Multiple patterns can be detected simultaneously.
    Based on sequences of states and motion history.
    Used for application-level gesture recognition (the "what" the user is doing).
    Detected when specific criteria are met across multiple readings.
    """
    THROW = auto()      # High acceleration followed by free fall
    CATCH = auto()      # Impact detected shortly after a throw (during or after free fall)
    ARC_SWING = auto()  # Smooth, significant rotation around an axis (like swinging an arm)
    SHAKE = auto()      # Rapid, repeated changes in acceleration direction
    DROP = auto()       # Free fall followed by impact (similar to throw/catch but may lack initial acceleration)
    ROLLING = auto()    # Sustained rolling motion detected

class AccelerometerManager:
    """
    Manager for accelerometer data access and processing.
    
    This class serves as a bridge between hardware and application layers,
    providing access to accelerometer data and motion detection.

    Core Concepts:
    - Motion State (`MotionState` enum): Represents the *instantaneous* physical
      state of the device (e.g., IDLE, ACCELERATING, FREE_FALL). Only one state
      is active at a time. Updated on every sensor reading via `_update_motion_state`.
      Transitions depend on sensor magnitudes (acceleration, gyro) exceeding or
      falling below defined thresholds.
    - Motion Pattern (`MotionPattern` enum): Represents a *recognized gesture* or
      activity over a period (e.g., THROW, CATCH, SHAKE, ROLL). Multiple patterns
      can be detected. Detected in `_detect_motion_patterns` based on sequences
      of motion states, sensor data history (`motion_history`), and specific
      criteria defined in `_check_*` helper methods (e.g., duration, magnitude,
      rotation consistency).

    Motion State Machine (`_update_motion_state`):
    - Takes current acceleration and gyro magnitudes and the timestamp.
    - Compares these values against thresholds (e.g., `throw_acceleration_threshold`,
      `free_fall_threshold`, `impact_threshold`, `rolling_accel_min/max`,
      `rolling_gyro_min`, `held_still_min/max_accel`).
    - Transitions the `self.motion_state` based on the comparisons and the *current* state.
      For example:
        - `IDLE` -> `ACCELERATION` if accel exceeds `throw_acceleration_threshold`.
        - `ACCELERATION` -> `FREE_FALL` if accel drops below `free_fall_threshold`.
        - `FREE_FALL` -> `IMPACT` if accel spikes above `impact_threshold`.
        - `IMPACT` -> `IDLE` or `HELD_STILL` after accel stabilizes below `impact_exit_threshold` for a delay.
        - `IDLE`/`ACCELERATION`/`LINEAR_MOTION`/`HELD_STILL` -> `ROLLING` if rolling criteria (`_check_rolling_criteria`) are met (moderate accel, significant gyro) and it's not linear motion (`_check_linear_motion`).
        - `IDLE`/`ACCELERATION`/`ROLLING`/`HELD_STILL` -> `LINEAR_MOTION` if linear criteria (`_check_linear_motion`) are met (low gyro, consistent accel direction) and accel is above minimum.
        - `IDLE`/`IMPACT`/`ROLLING`/`LINEAR_MOTION` -> `HELD_STILL` if accel is within the low `held_still` band for a minimum duration.
    - Manages timers (`free_fall_start_time`, `rolling_start_time`, `held_still_start_time`, `impact_exit_timer`) to track durations needed for state transitions or pattern detection.

    Motion Pattern Detection (`_detect_motion_patterns`):
    - Called after the motion state is updated.
    - Uses the current `self.motion_state` and recent data in `self.motion_history`.
    - Calls specific `_check_*_pattern` methods:
        - `_check_throw_pattern`: Looks for `FREE_FALL` state lasting longer than `min_free_fall_time`. Also handles very short throws detected via `ACCELERATION` -> `IMPACT`. Sets `throw_in_progress` flag.
        - `_check_catch_pattern`: Looks for `IMPACT` state while `throw_in_progress` is true. Uses `catch_detected_last_cycle` flag to ensure `throw_in_progress` isn't cleared prematurely.
        - `_check_arc_swing_pattern`: Uses `game_rotation` history to detect significant, smooth rotation (low standard deviation of rotation angles) above a threshold, excluding `ROLLING`, `FREE_FALL` or `IMPACT` states.
        - `_check_shake_pattern`: Looks for rapid, significant acceleration reversals over a short history, excluding `ROLLING`, `FREE_FALL` or `IMPACT` states.
        - `_check_rolling_pattern`: Requires `ROLLING` state for a minimum `rolling_duration`, checks for a dominant rotation axis and consistent direction, and ensures it's not mistaken for `LINEAR_MOTION`.
    - Stores detected patterns in `self.detected_patterns` and `self.pattern_history`.
    - Calculates `newly_detected_patterns` by comparing current patterns to the previous cycle's.

    Other Features:
    - Calculates heading from the rotation vector quaternion (`find_heading`).
    - Calculates a normalized movement energy level (`calculate_energy`).
    - Provides calibration checks via the hardware interface (`check_and_calibrate`).
    - Maintains history buffers (`motion_history`, `pattern_history`) using `deque` for efficient fixed-size storage.
    """
    
    def __init__(self):
        """Initialize the AccelerometerManager"""
        self.interface = BNO085Interface()
        self.logger = logging.getLogger(__name__)
        
        # --- Motion State & History ---
        self.motion_state = MotionState.IDLE
        self.motion_history = deque(maxlen=20)  # Store recent full sensor data dictionaries
        self.detected_patterns = []             # List of pattern names active in the current cycle
        self.pattern_history = deque(maxlen=5)  # Store recent (timestamp, [patterns]) tuples
        
        # --- Thresholds ---
        # Note: These values may need tuning based on the specific hardware,
        # mounting, and expected use case environment.
        
        # Throw/Catch/Impact
        self.throw_acceleration_threshold = 15.0  # m/s^2 - Min accel to trigger ACCELERATION state (potential throw start)
        self.free_fall_threshold = 3.0          # m/s^2 - Max accel magnitude to be considered FREE_FALL
        self.impact_threshold = 10.0            # m/s^2 - Min accel spike to trigger IMPACT state
        self.impact_exit_threshold = 3.5        # m/s^2 - Max accel magnitude to exit IMPACT state (must be below this)
        
        # Arc Swing
        self.arc_rotation_threshold = 1.5       # rad/s - Min integrated rotation for ARC_SWING
        
        # Shake
        self.shake_threshold = 8.0              # m/s^2 - (Currently unused, shake logic uses magnitude checks directly)
        
        # Rolling
        self.rolling_accel_min = 0.5            # m/s^2 - Min accel magnitude for ROLLING state/pattern
        self.rolling_accel_max = 40.0           # m/s^2 - Max accel magnitude for ROLLING state/pattern (higher might be impact)
        self.rolling_gyro_min = 1.0             # rad/s - Min gyro magnitude for ROLLING state/pattern
        self.rolling_duration = 0.5             # seconds - Min duration in ROLLING state to detect ROLLING pattern
        
        # Linear Motion
        self.linear_motion_history_samples = 5  # Number of samples to average for linear motion check
        self.linear_motion_max_avg_gyro = 0.5   # rad/s - Max average gyro allowed for LINEAR_MOTION
        self.linear_motion_min_avg_dot_product = 0.90 # Min avg dot product (cosine similarity) between consecutive accel vectors
        self.min_accel_for_direction_check = 0.1 # m/s^2 - Ignore accel vector direction if magnitude is below this
        
        # Held Still (Human Tremor)
        self.held_still_max_accel = 1.2         # m/s^2 - Max accel magnitude for HELD_STILL state
        self.held_still_min_accel = 0.05        # m/s^2 - Min accel magnitude for HELD_STILL state (distinguishes from truly idle)
        self.held_still_duration = 0.3          # seconds - Min duration in accel band to confirm HELD_STILL state
        
        # --- Timers & State Tracking ---
        self.free_fall_start_time = 0.0         # Timestamp when FREE_FALL state began
        self.min_free_fall_time = 0.04          # seconds - Min duration in FREE_FALL to detect THROW pattern
        self.max_free_fall_time = 2.0           # seconds - Max duration before FREE_FALL times out to IDLE
        
        self.rolling_start_time = 0.0           # Timestamp when ROLLING state began
        
        self.held_still_start_time = 0.0        # Timestamp when potential HELD_STILL state began (accel in band)
        
        self.throw_detected_time = 0.0          # Timestamp when the THROW pattern was last detected
        self.throw_in_progress = False          # Flag indicating a throw is likely ongoing (between ACCEL/FREE_FALL and CATCH/timeout)
        self.catch_detected_last_cycle = False  # Flag to delay clearing `throw_in_progress` until the cycle *after* CATCH
        
        self.previously_detected_patterns = set() # Set of pattern names detected in the *previous* cycle (for `newly_detected_patterns`)
        
        # --- Internal State / Debugging ---
        self.consecutive_low_accel = 0          # Counter for stable low acceleration readings (used for ACCELERATION -> FREE_FALL)
        self.impact_exit_timer = 0.0            # Timestamp when accel first dropped below `impact_exit_threshold` during IMPACT
        self.impact_exit_delay = 0.05           # seconds - Required delay with low accel before exiting IMPACT state
        self.impact_accel_history = deque(maxlen=3) # Store recent accel magnitudes during IMPACT for averaging exit condition
        
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
            
            # Detect current motion patterns
            detected_patterns = self._detect_motion_patterns(data)
            
            # Determine newly detected patterns
            current_patterns_set = set(detected_patterns)
            newly_detected = list(current_patterns_set - self.previously_detected_patterns)
            
            # Update the set of previously detected patterns for the next cycle
            self.previously_detected_patterns = current_patterns_set
            
            # Add detected and newly detected patterns to the data dictionary
            if detected_patterns:
                data["detected_patterns"] = detected_patterns
                self.detected_patterns = detected_patterns # Keep track of current patterns
            else:
                # Ensure detected_patterns is cleared if none are detected currently
                self.detected_patterns = [] 
                
            if newly_detected:
                data["newly_detected_patterns"] = newly_detected
            
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
        
        # Clear throw_in_progress ONLY if a catch was flagged in the *previous* cycle
        if self.catch_detected_last_cycle:
            self.throw_in_progress = False
            self.catch_detected_last_cycle = False # Reset flag
            self.logger.debug("Cleared throw_in_progress due to catch in previous cycle.")
            
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
            # Log warning but proceed with gyro_magnitude = 0.0
            self.logger.warning(f"Invalid gyro data: {gyro}")

        # --- State Machine Update ---
        # This is the core logic that determines the instantaneous physical state.
        self._update_motion_state(accel_magnitude, gyro_magnitude, current_data['timestamp'])

        # --- Pattern Detection ---
        # Based on the current state and history, check for higher-level gestures.
        detected_patterns_this_cycle = []
        try:
            current_time = current_data['timestamp'] # Use the timestamp from the data for consistency

            # Throw Detection Logic:
            # 1. Check for direct ACCELERATION -> IMPACT transition (very short drops)
            is_short_throw_detected = False
            if self.motion_state == MotionState.IMPACT and self.throw_in_progress:
                # Avoid double-counting if FREE_FALL based throw was detected just before impact
                throw_in_recent_history = any(
                    MotionPattern.THROW.name in patterns
                    for _, patterns in list(self.pattern_history)[-2:] # Check last 2 history entries
                )
                if not throw_in_recent_history:
                     # Check against currently detected patterns in *this* cycle to avoid duplicates if _check_throw_pattern runs later
                    if not any(p == MotionPattern.THROW.name for p in detected_patterns_this_cycle):
                        detected_patterns_this_cycle.append(MotionPattern.THROW.name)
                        is_short_throw_detected = True
                        self.logger.debug(f"THROW detected (Short Drop): ACCEL→IMPACT. Accel={accel_magnitude:.2f}")

            # 2. Check for normal throw via FREE_FALL state duration
            #    Only add if not already detected via the short drop logic above.
            if not is_short_throw_detected and self._check_throw_pattern():
                if not any(p == MotionPattern.THROW.name for p in detected_patterns_this_cycle):
                    detected_patterns_this_cycle.append(MotionPattern.THROW.name)
                # Set flags regardless, as free fall confirms throw intent even if pattern added above
                self.throw_detected_time = current_time
                if not self.throw_in_progress: # Only log if it wasn't already set
                     self.logger.debug(f"THROW detected (Free Fall): Accel={accel_magnitude:.2f}, starting throw_in_progress.")
                self.throw_in_progress = True


            # Catch Detection:
            # If detected, set flag for next cycle but DON'T clear throw_in_progress yet.
            # This ensures throw pattern isn't prematurely ended if catch occurs on the *same* cycle.
            if self._check_catch_pattern(accel_magnitude):
                if not any(p == MotionPattern.CATCH.name for p in detected_patterns_this_cycle): # Avoid duplicates
                    detected_patterns_this_cycle.append(MotionPattern.CATCH.name)
                    self.logger.debug(f"CATCH detected: Accel={accel_magnitude:.2f}. Setting flag for next cycle.")
                self.catch_detected_last_cycle = True # Flag to clear throw_in_progress next cycle

            # Arc Swing Detection:
            if self._check_arc_swing_pattern():
                # Exclude false positives during free fall.
                if self.motion_state != MotionState.FREE_FALL:
                    if not any(p == MotionPattern.ARC_SWING.name for p in detected_patterns_this_cycle):
                        detected_patterns_this_cycle.append(MotionPattern.ARC_SWING.name)
                        self.logger.debug("ARC_SWING pattern detected.")

            # Shake Detection:
            shake_result = self._check_shake_pattern()
            # self.logger.debug(f"_check_shake_pattern returned: {shake_result} (Current state: {self.motion_state.name})") # Verbose Debug
            if shake_result:
                if not any(p == MotionPattern.SHAKE.name for p in detected_patterns_this_cycle):
                    detected_patterns_this_cycle.append(MotionPattern.SHAKE.name)
                    self.logger.debug("SHAKE pattern detected.")

            # Rolling Detection:
            if self._check_rolling_pattern():
                # self.logger.debug("ROLLING pattern detected by _check_rolling_pattern(), appending.") # Verbose Debug
                if not any(p == MotionPattern.ROLLING.name for p in detected_patterns_this_cycle):
                    detected_patterns_this_cycle.append(MotionPattern.ROLLING.name)
                    self.logger.debug("ROLLING pattern detected.")
                # else:
                    # self.logger.debug("ROLLING pattern NOT detected by _check_rolling_pattern().") # Verbose Debug

            # --- Update History & State ---
            if detected_patterns_this_cycle:
                self.pattern_history.append((current_time, detected_patterns_this_cycle))

            # Expire throw_in_progress if it's been too long since the throw was detected
            if self.throw_in_progress and (current_time - self.throw_detected_time > self.max_free_fall_time):
                self.logger.debug(f"THROW pattern timed out after {self.max_free_fall_time}s. Clearing throw_in_progress.")
                self.throw_in_progress = False

        except Exception as e:
            # Log detailed information about the exception with context
            self.logger.error(f"Error detecting motion patterns: {e}", exc_info=True)
            self.logger.debug(f"Current data that caused error: {current_data}")

        return detected_patterns_this_cycle # Return patterns detected in *this* cycle
        
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
            elif self.held_still_min_accel < accel_magnitude < self.held_still_max_accel:
                if self.held_still_start_time == 0:
                    self.held_still_start_time = timestamp # Start timer
                elif timestamp - self.held_still_start_time > self.held_still_duration:
                    self.motion_state = MotionState.HELD_STILL
                    self.logger.debug(f"IDLE → HELD_STILL: accel={accel_magnitude:.2f} (stable low)")
                # Keep last_state_was_linear = False if accel is in this range but duration not met yet.
                self.last_state_was_linear = False
            elif accel_magnitude > self.rolling_accel_min and self._check_linear_motion():
                # Normal transition to LINEAR_MOTION
                self.motion_state = MotionState.LINEAR_MOTION
                self.logger.debug(f"IDLE → LINEAR_MOTION: accel={accel_magnitude:.2f}, gyro={gyro_magnitude:.2f}")
            else:
                # Default case if no other transition matches
                self.last_state_was_linear = False
                # Reset HELD_STILL timer if accel is outside the band or below min when in IDLE
                if not (self.held_still_min_accel < accel_magnitude < self.held_still_max_accel):
                    self.held_still_start_time = 0
                
        elif self.motion_state == MotionState.ACCELERATION:
            # Track consecutive low acceleration readings to detect short free falls
            if accel_magnitude < self.free_fall_threshold:
                self.consecutive_low_accel += 1
                # Require only 1 reading below threshold to confirm free fall (more sensitive)
                if self.consecutive_low_accel >= 1:
                    self.motion_state = MotionState.FREE_FALL
                    self.free_fall_start_time = timestamp
                    self.logger.debug(f"ACCELERATION → FREE_FALL: accel={accel_magnitude:.2f}")
                    self.consecutive_low_accel = 0 # Reset count after transition
            else:
                # Reset count if acceleration goes back up
                self.consecutive_low_accel = 0
                
                # Transition to IMPACT only if acceleration exceeds the *new*, higher threshold
                if accel_magnitude > self.impact_threshold:
                    # If a rapid acceleration is followed by an even higher acceleration, 
                    # it might be an impact without free fall (e.g., quick tap or very short drop)
                    self.motion_state = MotionState.IMPACT
                    self.logger.debug(f"ACCELERATION → IMPACT (direct): accel={accel_magnitude:.2f}")
                    # For very short drops, we might not see free fall state, so force throw detection
                    # Set the time and flag here, duration starts ticking.
                    if not self.throw_in_progress: # Avoid resetting time if already in progress from free fall
                         self.logger.debug(f"ACCEL->IMPACT transition detected, but not setting throw_in_progress.")

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
            # Store recent acceleration magnitude for averaging
            self.impact_accel_history.append(accel_magnitude)
            
            # Calculate average acceleration during impact (if enough history)
            avg_impact_accel = accel_magnitude
            if len(self.impact_accel_history) == self.impact_accel_history.maxlen:
                avg_impact_accel = sum(self.impact_accel_history) / len(self.impact_accel_history)
                
            # Impact is transient. Stay in IMPACT until avg accel is low for a short delay.
            if avg_impact_accel < self.impact_exit_threshold: 
                if self.impact_exit_timer == 0:
                     self.impact_exit_timer = timestamp # Start timer
                elif timestamp - self.impact_exit_timer > self.impact_exit_delay:
                     # Delay met: Transition out of IMPACT based on current conditions.
                     # Check HELD_STILL first, as a catch might end with the device held.
                     if self.held_still_min_accel < accel_magnitude < self.held_still_max_accel:
                          self.motion_state = MotionState.HELD_STILL
                          self.held_still_start_time = timestamp # Start timer for HELD_STILL duration check
                          self.logger.debug(f"IMPACT → HELD_STILL: avg_accel={avg_impact_accel:.2f}, cur_accel={accel_magnitude:.2f}")
                     else:
                          # Default transition to IDLE if not meeting HELD_STILL criteria
                          self.motion_state = MotionState.IDLE
                          self.logger.debug(f"IMPACT → IDLE: avg_accel={avg_impact_accel:.2f}, stable low for {self.impact_exit_delay}s")
                     # Reset timer and clear history *after* successful transition
                     self.impact_exit_timer = 0 
                     self.impact_accel_history.clear()
                     # Ensure throw is no longer in progress after impact fully settles
                     if self.throw_in_progress and not self.catch_detected_last_cycle:
                          self.logger.warning("Clearing throw_in_progress on IMPACT exit without recent catch.")
                          self.throw_in_progress = False
            else:
                 # Still above exit threshold OR within the exit delay period, reset timer if it was running
                 # This ensures we need a *continuous* period of low acceleration to exit IMPACT.
                 self.impact_exit_timer = 0
            
        elif self.motion_state == MotionState.ROLLING:
            # Check if still rolling
            if not self._check_rolling_criteria():
                # Rolling criteria failed, determine the next state
                self.logger.debug(f"Exiting ROLLING: accel={accel_magnitude:.2f}, gyro={gyro_magnitude:.2f}")
                # Prioritize checking for high-acceleration events first
                if accel_magnitude > self.throw_acceleration_threshold:
                    self.motion_state = MotionState.ACCELERATION
                    self.logger.debug(f"ROLLING → ACCELERATION: accel={accel_magnitude:.2f}")
                elif accel_magnitude > self.impact_threshold:
                    # Treat exceeding rolling max as potential impact if high enough
                    self.motion_state = MotionState.IMPACT 
                    self.logger.debug(f"ROLLING → IMPACT: accel={accel_magnitude:.2f}")
                # Then check for low-acceleration/stable states
                elif self.held_still_min_accel < accel_magnitude < self.held_still_max_accel:
                    # Start timer or transition if duration met
                    if self.held_still_start_time == 0:
                        self.held_still_start_time = timestamp
                    elif timestamp - self.held_still_start_time > self.held_still_duration:
                        self.motion_state = MotionState.HELD_STILL
                        self.logger.debug(f"ROLLING → HELD_STILL: accel={accel_magnitude:.2f} (stable low)")
                    #else: remain in ROLLING until timer expires or other conditions met?
                    # No, if rolling criteria failed, we must transition. HELD_STILL timer just started.
                elif self._check_linear_motion() and accel_magnitude > self.rolling_accel_min:
                    # Check if it's linear motion instead
                    self.motion_state = MotionState.LINEAR_MOTION
                    self.logger.debug(f"ROLLING → LINEAR_MOTION: accel={accel_magnitude:.2f}, gyro={gyro_magnitude:.2f}")
                else:
                    # Fallback to IDLE if no other specific state matches
                    self.motion_state = MotionState.IDLE
                    self.logger.debug(f"ROLLING → IDLE (fallback): accel={accel_magnitude:.2f}, gyro={gyro_magnitude:.2f}")
            # else: Still meets rolling criteria, stay in ROLLING state
            
            # Reset HELD_STILL timer if acceleration is outside the specific band while rolling
            # This prevents accidental transition to HELD_STILL if rolling briefly enters the band
            if not (self.held_still_min_accel < accel_magnitude < self.held_still_max_accel):
                self.held_still_start_time = 0
        
        elif self.motion_state == MotionState.LINEAR_MOTION:
             # Check for transition to HELD_STILL first
            if self.held_still_min_accel < accel_magnitude < self.held_still_max_accel:
                if self.held_still_start_time == 0:
                     self.held_still_start_time = timestamp
                elif timestamp - self.held_still_start_time > self.held_still_duration:
                     self.motion_state = MotionState.HELD_STILL
                     self.logger.debug(f"LINEAR_MOTION → HELD_STILL: accel={accel_magnitude:.2f} (stable low)")
            # Exit LINEAR_MOTION if acceleration drops significantly or motion changes
            elif accel_magnitude < self.rolling_accel_min:
                # Transition to IDLE (don't need complex oscillation check anymore)
                self.motion_state = MotionState.IDLE
                self.logger.debug(f"LINEAR_MOTION → IDLE: accel={accel_magnitude:.2f}")
            elif accel_magnitude > self.throw_acceleration_threshold:
                self.motion_state = MotionState.ACCELERATION
                self.logger.debug(f"LINEAR_MOTION → ACCELERATION: accel={accel_magnitude:.2f}")
            elif self._check_rolling_criteria() and not self._check_linear_motion():
                self.motion_state = MotionState.ROLLING
                self.rolling_start_time = timestamp
                self.logger.debug(f"LINEAR_MOTION → ROLLING: accel={accel_magnitude:.2f}, gyro={gyro_magnitude:.2f}")

            # Reset held_still timer if accel is outside the band
            if not (self.held_still_min_accel < accel_magnitude < self.held_still_max_accel):
                self.held_still_start_time = 0
        
        elif self.motion_state == MotionState.HELD_STILL:
            # Exit HELD_STILL if acceleration goes outside the stable band
            if not (self.held_still_min_accel < accel_magnitude < self.held_still_max_accel):
                 # Determine next state based on magnitude
                 if accel_magnitude > self.throw_acceleration_threshold:
                      self.motion_state = MotionState.ACCELERATION
                      self.logger.debug(f"HELD_STILL → ACCELERATION: accel={accel_magnitude:.2f}")
                 elif self._check_rolling_criteria() and not self._check_linear_motion():
                      self.motion_state = MotionState.ROLLING
                      self.rolling_start_time = timestamp
                      self.logger.debug(f"HELD_STILL → ROLLING: accel={accel_magnitude:.2f}, gyro={gyro_magnitude:.2f}")
                 elif accel_magnitude >= self.rolling_accel_min: # Use rolling_accel_min as threshold for linear motion
                      self.motion_state = MotionState.LINEAR_MOTION
                      self.logger.debug(f"HELD_STILL → LINEAR_MOTION: accel={accel_magnitude:.2f}")
                 else: # If below linear motion threshold, go to IDLE
                      self.motion_state = MotionState.IDLE
                      self.logger.debug(f"HELD_STILL → IDLE: accel={accel_magnitude:.2f}")
                 # Reset the timer when exiting HELD_STILL
                 self.held_still_start_time = 0
            # Optional: Add a max duration check if needed, but primary exit is accel band
            # held_still_max_duration = 30.0
            # if self.held_still_start_time > 0 and timestamp - self.held_still_start_time > held_still_max_duration:
            #    # Force re-evaluation similar to above exit logic
            #    ...

        # Log state transition if changed
        if previous_state != self.motion_state:
            self.logger.debug(f"Motion state change: {previous_state.name} → {self.motion_state.name} " +
                             f"(accel={accel_magnitude:.2f}, gyro={gyro_magnitude:.2f})")
            
            # Reset impact exit timer on any state change *away* from IMPACT
            if previous_state == MotionState.IMPACT and self.motion_state != MotionState.IMPACT:
                 self.impact_exit_timer = 0
                 self.impact_accel_history.clear() # Clear history when leaving impact
                 
            # Reset consecutive low accel count if not transitioning TO free fall
            if self.motion_state != MotionState.FREE_FALL:
                 self.consecutive_low_accel = 0

            # Reset held still timer when changing state *away* from HELD_STILL
            if previous_state == MotionState.HELD_STILL and self.motion_state != MotionState.HELD_STILL:
                 self.held_still_start_time = 0
            # Also reset if transitioning *away* from IDLE or LINEAR_MOTION
            # as these are the entry points for HELD_STILL check
            if previous_state in [MotionState.IDLE, MotionState.LINEAR_MOTION] and \
               self.motion_state not in [MotionState.IDLE, MotionState.LINEAR_MOTION, MotionState.HELD_STILL]:
                self.held_still_start_time = 0
            # Correction 5: Reset HELD_STILL timer when leaving IDLE for non-HELD_STILL states
            # Ensure HELD_STILL timer is reset if we leave a state where it could have been started
            # (IDLE, LINEAR_MOTION, ROLLING, IMPACT) and *don't* enter HELD_STILL.
            if previous_state in [MotionState.IDLE, MotionState.LINEAR_MOTION, MotionState.ROLLING, MotionState.IMPACT] and \
                self.motion_state != MotionState.HELD_STILL:
                  self.held_still_start_time = 0

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
    
    def _normalize_vector(self, vec: Tuple[float, float, float]) -> Optional[Tuple[float, float, float]]:
        """Normalize a 3D vector."""
        mag = sqrt(vec[0]**2 + vec[1]**2 + vec[2]**2)
        if mag < 1e-6: # Avoid division by zero for near-zero vectors
            return None
        return (vec[0] / mag, vec[1] / mag, vec[2] / mag)

    def _dot_product(self, v1: Tuple[float, float, float], v2: Tuple[float, float, float]) -> float:
        """Calculate the dot product of two 3D vectors."""
        # Added try-except for robustness against potential non-numeric data
        try:
            return v1[0]*v2[0] + v1[1]*v2[1] + v1[2]*v2[2]
        except (TypeError, IndexError):
            self.logger.warning(f"Invalid vector component found during dot product: v1={v1}, v2={v2}")
            return 0.0 # Return neutral value on error

    def _check_linear_motion(self) -> bool:
        """
        Check if the current motion is primarily linear (consistent direction, low rotation).
        
        Linear motion must have BOTH:
        1. Low average angular velocity (gyro magnitude).
        2. Consistent linear acceleration direction (high dot product between consecutive vectors).
        
        Returns:
            bool: True if motion appears to be linear.
        """
        history_size = len(self.motion_history)
        samples_to_check = self.linear_motion_history_samples
        
        if history_size < samples_to_check:
            return False
            
        # Get recent samples
        recent_samples = list(self.motion_history)[-samples_to_check:]
        
        # 1. Check average gyro magnitude
        gyro_magnitudes = []
        for entry in recent_samples:
            gyro = entry.get("gyro", None)
            if isinstance(gyro, tuple) and len(gyro) == 3:
                gyro_magnitudes.append(sqrt(gyro[0]**2 + gyro[1]**2 + gyro[2]**2))
        
        if not gyro_magnitudes: # Not enough valid gyro data
             return False
             
        avg_gyro_magnitude = sum(gyro_magnitudes) / len(gyro_magnitudes)
        
        if avg_gyro_magnitude >= self.linear_motion_max_avg_gyro:
            self.logger.debug(f"Linear motion check failed: Avg gyro {avg_gyro_magnitude:.2f} >= {self.linear_motion_max_avg_gyro:.2f}")
            return False # Rotation is too high
            
        # 2. Check acceleration direction consistency using dot product
        dot_products = []
        prev_norm_accel = None
        valid_accel_count = 0
        
        for entry in recent_samples:
            accel = entry.get("linear_acceleration", None)
            if not (isinstance(accel, tuple) and len(accel) == 3):
                continue # Skip invalid entries
                
            # Only consider direction if acceleration is significant
            accel_mag = sqrt(accel[0]**2 + accel[1]**2 + accel[2]**2)
            if accel_mag < self.min_accel_for_direction_check:
                 # Treat low accel as consistent with previous direction if available
                 if prev_norm_accel is not None:
                      dot_products.append(1.0) # Assume consistency if motion nearly stopped
                 continue
                 
            norm_accel = self._normalize_vector(accel)
            if norm_accel is None:
                 continue # Skip zero vectors
            
            valid_accel_count += 1
            if prev_norm_accel is not None:
                # Calculate dot product (cosine of angle between vectors)
                dot_product = self._dot_product(norm_accel, prev_norm_accel)
                dot_products.append(dot_product)
                
            prev_norm_accel = norm_accel
            
        # Require at least 2 valid, significant acceleration vectors to compare
        if len(dot_products) < 1 or valid_accel_count < 2: 
            self.logger.debug("Linear motion check failed: Not enough valid accel vectors for comparison.")
            return False 
            
        avg_dot_product = sum(dot_products) / len(dot_products)
        
        if avg_dot_product < self.linear_motion_min_avg_dot_product:
            self.logger.debug(f"Linear motion check failed: Avg dot product {avg_dot_product:.3f} < {self.linear_motion_min_avg_dot_product:.3f}")
            return False # Direction is not consistent enough
            
        # If both checks passed:
        self.logger.debug(f"Linear motion check PASSED: Avg gyro={avg_gyro_magnitude:.2f}, Avg dot={avg_dot_product:.3f}")
        return True
        
    def _check_throw_pattern(self) -> bool:
        """
        Check if a throw pattern has been detected.
        
        A throw consists of:
        1. Initial acceleration spike
        2. Period of free fall (near-zero acceleration)
        
        Returns:
            bool: True if throw pattern detected
        """
        # Reduce required history slightly if needed, but 3 seems reasonable
        if len(self.motion_history) < 3:
            return False
            
        # Check state sequence for a throw
        if self.motion_state == MotionState.FREE_FALL:
            # Check if free fall has lasted minimum duration
            if len(self.motion_history) > 0 and 'timestamp' in self.motion_history[-1]:
                timestamp = self.motion_history[-1]['timestamp']
                if self.free_fall_start_time > 0: # Ensure start time is valid
                    free_fall_duration = timestamp - self.free_fall_start_time
                    
                    # Log free fall data for debugging
                    self.logger.debug(f"In FREE_FALL state. Duration: {free_fall_duration:.3f}s (min required: {self.min_free_fall_time:.3f}s)")
                    
                    # Minimum free fall time to be considered a throw - adjusted threshold
                    if free_fall_duration > self.min_free_fall_time:
                        # Optionally add more checks here (e.g., significant prior acceleration) if needed
                        # For now, relying on state machine (ACCEL -> FREE_FALL) + duration
                        return True
                else:
                     self.logger.warning("In FREE_FALL state but free_fall_start_time is invalid.")
                    
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
        # 1. We just transitioned into IMPACT state OR are currently in it.
        # 2. A throw was recently initiated (throw_in_progress is True).
        
        # Check current state first
        if self.motion_state == MotionState.IMPACT:
            # Check if we had a throw in progress leading to this impact
            if self.throw_in_progress:
                # Check if the impact magnitude is significant enough for a catch
                # (This uses the same impact_threshold, could potentially be different)
                if current_accel_magnitude >= self.impact_threshold:
                    self.logger.debug(f"CATCH detected: IMPACT state (accel={current_accel_magnitude:.2f}) while throw_in_progress=True.")
                    return True
                else:
                    # Impact state but low magnitude, might be settling after free fall without a hard catch
                    self.logger.debug(f"In IMPACT state with throw_in_progress, but accel {current_accel_magnitude:.2f} < impact_threshold {self.impact_threshold:.2f}. Not a catch.")
            #     # Entered IMPACT state but throw was not in progress - could be a bump or drop without prior accel.
            #     pass # No need to log if not a catch scenario

        # Backup check: Look at recent pattern history (less reliable than state flag)
        # Consider removing or reducing reliance on this if the state flag method works well
        # current_time = time.time()
        # for timestamp, patterns in reversed(self.pattern_history): # Check recent history first
        #     if (current_time - timestamp) <= self.max_free_fall_time:
        #         if MotionPattern.THROW.name in patterns:
        #             # Check if impact also occurred around this time (more robust)
        #             # This requires correlating history which is complex, prefer state flag.
        #             # self.logger.debug(f"CATCH detected: via pattern history (THROW found {current_time - timestamp:.2f}s ago).\")
        #             # return True 
        #     else:
        #         break # Stop checking older history
            
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
        # Correction 3: Prevent Arc Swing during Rolling
        if self.motion_state == MotionState.ROLLING:
             self.logger.debug("Arc swing check skipped: State is ROLLING.")
             return False

        if len(self.motion_history) < 8:
            return False
            
        # Don't detect arc swings during free fall or impact settling
        if self.motion_state in [MotionState.FREE_FALL, MotionState.IMPACT]:
            return False
            
        # Use game rotation quaternion for smooth rotation detection
        # Convert to list first for safety and filter out invalid data
        rotations = [entry.get("game_rotation", (0, 0, 0, 1)) for entry in list(self.motion_history)
                    if isinstance(entry.get("game_rotation", (0, 0, 0, 1)), tuple) 
                    and len(entry.get("game_rotation", (0, 0, 0, 1))) == 4]
        
        # Check if we have significant rotation around a consistent axis
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
                    # Ensure dot product is clamped within [-1, 1] for acos stability
                    dot_product = max(-1.0, min(1.0, dot_product))
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
                        # ADDED: Check for ongoing rotation
                        latest_gyro_mag = 0.0
                        latest_entry = self.motion_history[-1]
                        if isinstance(latest_entry.get("gyro"), tuple) and len(latest_entry.get("gyro")) == 3:
                            gyro = latest_entry.get("gyro")
                            latest_gyro_mag = sqrt(sum(x*x for x in gyro))
                        
                        # Require gyro magnitude to stay somewhat high to maintain ARC pattern
                        min_ongoing_arc_rotation = self.arc_rotation_threshold * 0.6 # e.g., 60% of peak threshold
                        if latest_gyro_mag >= min_ongoing_arc_rotation:
                            return True
                        else:
                             self.logger.debug(f"Arc swing check failed: ongoing rotation {latest_gyro_mag:.2f} < threshold {min_ongoing_arc_rotation:.2f}")

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
        # Prevent Shake during Rolling
        if self.motion_state == MotionState.ROLLING:
            self.logger.debug("Shake check skipped: State is ROLLING.")
            return False

        if len(self.motion_history) < 6:
            return False
        
        # Don't detect shake during free fall or impact
        # DEBUG: Log state just before the check
        self.logger.debug(f"Checking shake pattern. Current state: {self.motion_state.name}")
        if self.motion_state in [MotionState.FREE_FALL, MotionState.IMPACT]:
            self.logger.debug("Shake check skipped: State is FREE_FALL or IMPACT.")
            return False # Should exit here if state is IMPACT

        # Get recent acceleration values - convert deque to list before slicing for safety
        accelerations = [entry.get("linear_acceleration", (0, 0, 0))
                         for entry in list(self.motion_history)[-6:]
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
                self.logger.debug(f"Rolling pattern check: Duration requirement met ({rolling_duration:.2f}s > {self.rolling_duration:.2f}s)")
                # Ensure the motion isn't primarily linear (e.g., sliding without much rotation)
                is_linear = self._check_linear_motion()
                if is_linear:
                    self.logger.debug("Rolling pattern check failed: Motion appears to be linear.")
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
                
                # Check for a dominant axis of rotation
                dominant_axis_info = self._dominant_rotation_axis(gyro_readings)
                if dominant_axis_info is None:
                    self.logger.debug("Rolling pattern check failed: Could not determine dominant axis (negligible/invalid rotation?).")
                    return False

                dominant_axis, dominant_ratio = dominant_axis_info
                axis_names = ['x', 'y', 'z']
                
                # Define the minimum ratio needed *before* logging it
                min_dominant_ratio = 0.35 # Lowered from 0.55
                self.logger.debug(f"Rolling pattern check: Dominant axis is {axis_names[dominant_axis]} with ratio {dominant_ratio:.2f} (min required: {min_dominant_ratio:.2f})")
                
                # If one axis dominates the rotation (rolling tends to rotate around one axis)
                # Relaxed the required ratio from 0.7 to 0.55 to allow more wobble
                if dominant_ratio > min_dominant_ratio:
                    self.logger.debug(f"Rolling check passed: Dominant axis {axis_names[dominant_axis]} ratio {dominant_ratio:.2f} > {min_dominant_ratio:.2f}")
                    
                    # Verify consistency of rotation direction around dominant axis
                    last_direction = None
                    direction_changes = 0
                    
                    for gyro in gyro_readings:
                        current_direction = 1 if gyro[dominant_axis] > 0 else -1
                        if last_direction is not None and current_direction != last_direction:
                            direction_changes += 1
                        last_direction = current_direction
                    
                    # True rolling should have consistent rotation direction
                    # Relaxed allowed changes from 1 to 2
                    max_direction_changes = 3
                    if direction_changes <= max_direction_changes:
                        self.logger.debug(f"Rolling check passed: Direction changes {direction_changes} <= {max_direction_changes}")
                        return True
                    else:
                        self.logger.debug(f"Rolling check failed: Too many direction changes ({direction_changes} > {max_direction_changes})")
                else:
                    self.logger.debug(f"Rolling check failed: No dominant rotation axis detected.") # Log updated
            else:
                # Log only if the state is still ROLLING but duration isn't met yet
                # Avoids log spam if the state changes before duration is met
                if self.motion_state == MotionState.ROLLING:
                    self.logger.debug(f"Rolling pattern check: In ROLLING state, but duration requirement NOT met ({rolling_duration:.2f}s <= {self.rolling_duration:.2f}s)")
        return False

    def _dominant_rotation_axis(self, gyro_readings: List[Tuple[float, float, float]]) -> Optional[Tuple[int, float]]:
        """
        Find the dominant rotation axis (0=x, 1=y, 2=z) and its ratio over a list of gyro readings.

        Args:
            gyro_readings: List of (gx, gy, gz) tuples.

        Returns:
            Tuple containing (dominant_axis_index, dominant_ratio) or None if input is invalid or negligible rotation.
        """
        if not gyro_readings:
            return None

        axis_totals = [0.0, 0.0, 0.0]
        valid_readings = 0
        for gyro in gyro_readings:
            try:
                # Ensure gyro is a tuple of 3 numbers
                if isinstance(gyro, tuple) and len(gyro) == 3 and all(isinstance(v, (int, float)) for v in gyro):
                    axis_totals[0] += abs(gyro[0])
                    axis_totals[1] += abs(gyro[1])
                    axis_totals[2] += abs(gyro[2])
                    valid_readings += 1
                else:
                    self.logger.warning(f"Skipping invalid gyro reading in _dominant_rotation_axis: {gyro}")
            except Exception as e: # Catch potential errors during processing
                self.logger.warning(f"Error processing gyro reading {gyro} in _dominant_rotation_axis: {e}")
                continue

        if valid_readings == 0:
            return None # No valid data to process

        # self.logger.debug(f"Rolling axis totals: x={axis_totals[0]:.2f}, y={axis_totals[1]:.2f}, z={axis_totals[2]:.2f}") # Verbose debug
        sum_total = sum(axis_totals)
        if sum_total < 1e-6: # Avoid division by zero if total rotation is negligible
            return None

        dominant_axis = axis_totals.index(max(axis_totals))
        dominant_ratio = axis_totals[dominant_axis] / sum_total
        return dominant_axis, dominant_ratio

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
        
        print("")