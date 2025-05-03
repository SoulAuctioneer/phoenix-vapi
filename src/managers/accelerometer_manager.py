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
import statistics
# NOTE: Do NOT change the line below. It is correct.
from hardware.acc_bno085 import BNO085Interface
from math import atan2, sqrt, pi, acos
from config import MoveActivityConfig
from collections import deque
from enum import Enum, auto
import time

class SimplifiedState(Enum):
    """Represents the detected physical state based on simplified criteria."""
    STATIONARY = auto()   # Device is virtually motionless
    HELD_STILL = auto()   # Held by a user, experiencing slight tremor
    FREE_FALL = auto()    # Falling, near-zero acceleration
    IMPACT = auto()       # Sudden spike in acceleration
    SHAKE = auto()        # Rapid, repeated changes in acceleration
    MOVING = auto()       # General motion not matching other specific states
    UNKNOWN = auto()      # State cannot be determined (e.g., insufficient data)

class AccelerometerManager:
    """
    Simplified manager for accelerometer data access and state detection.

    Focuses on detecting basic states: STATIONARY, HELD_STILL, FREE_FALL, IMPACT, SHAKE, MOVING, UNKNOWN.
    Removes the complex state machine and pattern recognition logic from previous versions.
    Reads sensor data, updates a motion history, and determines the current state based on
    acceleration magnitude, thresholds, duration checks, and simple shake detection.
    """

    def __init__(self):
        """Initialize the AccelerometerManager"""
        self.interface = BNO085Interface()
        self.logger = logging.getLogger(__name__)

        # --- History ---
        self.motion_history = deque(maxlen=20)  # Store recent full sensor data dictionaries

        # --- Thresholds ---
        # Stationary / Held Still
        self.stationary_max_accel = 0.1         # m/s^2 - Max accel magnitude for STATIONARY
        self.held_still_min_accel = 0.1         # m/s^2 - Min accel magnitude for HELD_STILL (must be >= stationary_max_accel)
        self.held_still_max_accel = 1.2         # m/s^2 - Max accel magnitude for HELD_STILL
        self.stationary_duration = 0.5          # seconds - Min duration for STATIONARY state
        self.held_still_duration = 0.3          # seconds - Min duration for HELD_STILL state

        # Free Fall / Impact
        self.free_fall_threshold = 3.0          # m/s^2 - Max accel magnitude for FREE_FALL
        self.impact_threshold = 15.0            # m/s^2 - Min accel spike for IMPACT

        # Shake
        self.shake_history_size = 10            # Samples (~0.1s at 100Hz)
        self.min_magnitude_for_shake = 4.0      # m/s^2 - Min average accel magnitude for SHAKE
        self.min_accel_reversals_for_shake = 3  # Min number of direction changes for SHAKE in history window

        # --- Timers / State Tracking ---
        self.in_stationary_band_start_time = 0.0 # Timestamp when accel first entered STATIONARY band
        self.in_held_still_band_start_time = 0.0 # Timestamp when accel first entered HELD_STILL band
        self.last_accel_magnitude = 0.0          # Store previous accel magnitude for impact detection edge
        self.current_state = SimplifiedState.UNKNOWN # Store the determined state

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
        Read raw sensor data and determine the simplified motion state.

        Returns:
            Dict[str, Any]: Dictionary containing sensor readings and the detected state name.
        """
        data = self.interface.read_sensor_data()
        current_time = time.time()
        data['timestamp'] = current_time # Add timestamp immediately

        # Calculate optional values first
        # If data contains rotation vector, calculate heading
        if "rotation_vector" in data and isinstance(data["rotation_vector"], tuple) and len(data["rotation_vector"]) == 4:
            quat_i, quat_j, quat_k, quat_real = data["rotation_vector"]
            data["heading"] = self.find_heading(quat_real, quat_i, quat_j, quat_k)

        # Calculate energy level if we have the required data
        if ("linear_acceleration" in data and isinstance(data["linear_acceleration"], tuple) and len(data["linear_acceleration"]) == 3 and
            "gyro" in data and isinstance(data["gyro"], tuple) and len(data["gyro"]) == 3):
            data["energy"] = self.calculate_energy(
                data["linear_acceleration"],
                data["gyro"],
                MoveActivityConfig.ACCEL_WEIGHT,
                MoveActivityConfig.GYRO_WEIGHT
            )
        else:
            # Ensure energy field exists even if calculation fails
            data["energy"] = 0.0 # Or None, depending on desired handling

        # Update motion history regardless of calculation success
        self._update_motion_history(data)

        # Determine current motion state based on available core data
        self.current_state = self._determine_current_state(data)
        data["current_state"] = self.current_state.name

        return data

    def _update_motion_history(self, data: Dict[str, Any]):
        """
        Update the history of recent motion data.

        Args:
            data: Current sensor data (potentially partial if read failed)
        """
        # Ensure timestamp exists even if other data is missing
        if 'timestamp' not in data:
            data['timestamp'] = time.time()

        # Store in history
        self.motion_history.append(data)

    def _determine_current_state(self, current_data: Dict[str, Any]) -> SimplifiedState:
        """
        Determine the current motion state based on simplified criteria.
        Checks for IMPACT, FREE_FALL, SHAKE, STATIONARY, HELD_STILL in priority order.
        Requires linear_acceleration data; returns UNKNOWN otherwise.

        Args:
            current_data: Current sensor readings dictionary.

        Returns:
            SimplifiedState: The detected state.
        """
        if len(self.motion_history) < 2: # Need at least previous + current
            self.last_accel_magnitude = 0.0 # Reset on insufficient history
            self._reset_duration_timers()
            return SimplifiedState.UNKNOWN

        linear_accel = current_data.get("linear_acceleration", None)
        timestamp = current_data.get('timestamp', time.time()) # Use provided or current time

        if not (isinstance(linear_accel, tuple) and len(linear_accel) == 3 and
                all(isinstance(x, (int, float)) for x in linear_accel)):
            self.logger.warning(f"Invalid/missing linear acceleration for state detection: {linear_accel}")
            # Reset timers and previous magnitude if core data is invalid
            self._reset_duration_timers()
            self.last_accel_magnitude = 0.0
            return SimplifiedState.UNKNOWN

        accel_magnitude = sqrt(sum(x*x for x in linear_accel))

        # --- State Checks (Prioritized) ---
        # Order: Impact > Free Fall > Shake > Stationary > Held Still > Moving

        # 1. IMPACT: Check for a sudden spike above threshold
        #    Triggered if accel crosses threshold upwards in one step.
        is_impact = (accel_magnitude >= self.impact_threshold and
                     self.last_accel_magnitude < self.impact_threshold)
        if is_impact:
            self.logger.debug(f"IMPACT detected: Accel {self.last_accel_magnitude:.2f} -> {accel_magnitude:.2f}")
            self._reset_duration_timers() # Impact overrides duration checks
            self.last_accel_magnitude = accel_magnitude # Update last mag *after* check
            return SimplifiedState.IMPACT

        # 2. FREE_FALL: Check if acceleration is very low
        if accel_magnitude < self.free_fall_threshold:
            # self.logger.debug(f"FREE_FALL detected: Accel={accel_magnitude:.2f}") # Can be spammy
            self._reset_duration_timers() # Free fall overrides duration checks
            self.last_accel_magnitude = accel_magnitude
            return SimplifiedState.FREE_FALL

        # 3. SHAKE: Check for high magnitude and rapid changes/reversals
        if self._check_shake():
             self.logger.debug("SHAKE detected.")
             self._reset_duration_timers() # Shake overrides duration checks
             self.last_accel_magnitude = accel_magnitude
             return SimplifiedState.SHAKE

        # --- Duration-Based States (STATIONARY / HELD_STILL) ---
        # Update timers based on current magnitude band
        self._update_duration_timers(accel_magnitude, timestamp)

        # Check if STATIONARY duration is met
        if self.in_stationary_band_start_time > 0.0 and \
           (timestamp - self.in_stationary_band_start_time >= self.stationary_duration):
            # self.logger.debug(f"STATIONARY confirmed.") # Reduce log spam
            self.last_accel_magnitude = accel_magnitude
            # Do NOT reset timer here, stay in STATIONARY until accel leaves band
            return SimplifiedState.STATIONARY

        # Check if HELD_STILL duration is met
        if self.in_held_still_band_start_time > 0.0 and \
           (timestamp - self.in_held_still_band_start_time >= self.held_still_duration):
            # self.logger.debug(f"HELD_STILL confirmed.") # Reduce log spam
            self.last_accel_magnitude = accel_magnitude
            # Do NOT reset timer here, stay in HELD_STILL until accel leaves band
            return SimplifiedState.HELD_STILL

        # 5. MOVING: If none of the specific states are met
        # This means accel is above free_fall threshold, not shake, not impact,
        # and not within the stationary/held_still bands (or duration not met yet).
        # self.logger.debug(f"MOVING state: Accel={accel_magnitude:.2f}")
        self.last_accel_magnitude = accel_magnitude
        return SimplifiedState.MOVING

    def _update_duration_timers(self, accel_magnitude: float, timestamp: float):
        """Updates the start times for STATIONARY and HELD_STILL bands."""
        # Check STATIONARY band
        is_in_stationary_band = accel_magnitude < self.stationary_max_accel
        if is_in_stationary_band:
            if self.in_stationary_band_start_time == 0.0:
                # self.logger.debug(f"Entered STATIONARY band: Accel={accel_magnitude:.2f}")
                self.in_stationary_band_start_time = timestamp
            self.in_held_still_band_start_time = 0.0 # Mutually exclusive
        else:
            if self.in_stationary_band_start_time != 0.0:
                # self.logger.debug(f"Exited STATIONARY band: Accel={accel_magnitude:.2f}")
                self.in_stationary_band_start_time = 0.0

            # Check HELD_STILL band only if not in STATIONARY band
            is_in_held_still_band = (self.held_still_min_accel <= accel_magnitude < self.held_still_max_accel)
            if is_in_held_still_band:
                if self.in_held_still_band_start_time == 0.0:
                    # self.logger.debug(f"Entered HELD_STILL band: Accel={accel_magnitude:.2f}")
                    self.in_held_still_band_start_time = timestamp
                # self.in_stationary_band_start_time should already be 0 here
            else:
                if self.in_held_still_band_start_time != 0.0:
                    # self.logger.debug(f"Exited HELD_STILL band: Accel={accel_magnitude:.2f}")
                    self.in_held_still_band_start_time = 0.0

    def _reset_duration_timers(self):
        """Resets timers used for HELD_STILL and STATIONARY detection."""
        # Log only if a timer was actually active
        if self.in_stationary_band_start_time != 0.0:
             # self.logger.debug("Resetting active stationary timer.")
             self.in_stationary_band_start_time = 0.0
        if self.in_held_still_band_start_time != 0.0:
             # self.logger.debug("Resetting active held_still timer.")
             self.in_held_still_band_start_time = 0.0

    def _check_shake(self) -> bool:
        """
        Check if a shake state is detected using simplified criteria.
        Focuses on average magnitude and acceleration direction reversals over recent history.

        Returns:
            bool: True if shake state detected
        """
        history_size = self.shake_history_size
        if len(self.motion_history) < history_size:
            return False

        # --- Get recent data ---
        # Take a slice efficiently
        start_index = len(self.motion_history) - history_size
        recent_history = [self.motion_history[i] for i in range(start_index, len(self.motion_history))]
        accelerations = [entry.get("linear_acceleration", None) for entry in recent_history]

        # --- Filter invalid entries ---
        valid_accelerations = [accel for accel in accelerations
                              if isinstance(accel, tuple) and len(accel) == 3]

        if len(valid_accelerations) < 5: # Need a reasonable number of points
            return False

        # === Magnitude Check ===
        accel_magnitudes = []
        for accel in valid_accelerations:
            try:
                # Avoid sqrt of zero or negative numbers if data is weird
                magnitude_sq = accel[0]**2 + accel[1]**2 + accel[2]**2
                if magnitude_sq >= 0:
                     magnitude = sqrt(magnitude_sq)
                     accel_magnitudes.append(magnitude)
            except (TypeError, IndexError):
                continue # Skip malformed accel tuples

        if len(accel_magnitudes) < 5:
             return False

        avg_accel_magnitude = statistics.mean(accel_magnitudes)

        if avg_accel_magnitude < self.min_magnitude_for_shake:
            return False

        # === Acceleration Reversal Check ===
        # Count how many times the sign of acceleration changes for each axis
        reversals = [0, 0, 0] # x, y, z
        last_signs = [0, 0, 0]

        for accel in valid_accelerations:
            for i in range(3):
                # Check sign with a small deadzone around zero to avoid noise triggers
                current_sign = 0
                deadzone = 0.1 # m/s^2
                try:
                    if accel[i] > deadzone:
                        current_sign = 1
                    elif accel[i] < -deadzone:
                        current_sign = -1
                except IndexError:
                     continue # Skip if accel tuple is somehow wrong length

                if current_sign != 0 and last_signs[i] != 0 and current_sign != last_signs[i]:
                    reversals[i] += 1
                if current_sign != 0:
                    last_signs[i] = current_sign

        total_reversals = sum(reversals)

        if total_reversals < self.min_accel_reversals_for_shake:
            return False

        # --- Passed Checks ---
        return True

    def find_heading(self, dqw: float, dqx: float, dqy: float, dqz: float) -> float:
        """
        Calculate heading (Yaw) from rotation vector quaternion values (W, X, Y, Z).
        Returns heading in degrees (0-360 clockwise from North/initial Z-axis direction).
        Handles potential normalization issues and edge cases.
        """
        # Normalize quaternion
        norm_sq = dqw * dqw + dqx * dqx + dqy * dqy + dqz * dqz
        if norm_sq < 1e-9: # Check if norm is near zero
            return 0.0 # Avoid division by zero; return default heading
        norm = sqrt(norm_sq)
        dqw, dqx, dqy, dqz = dqw / norm, dqx / norm, dqy / norm, dqz / norm

        # Calculate yaw using atan2 for numerical stability
        # Yaw (around Z-axis) calculation based on standard quaternion-to-Euler formulas
        # atan2(2*(qw*qz + qx*qy), 1 - 2*(qy^2 + qz^2))
        yaw_arg1 = 2.0 * (dqw * dqz + dqx * dqy)
        yaw_arg2 = 1.0 - 2.0 * (dqy * dqy + dqz * dqz)

        # atan2 handles quadrant correctness and edge cases like arg2=0
        yaw_rad = atan2(yaw_arg1, yaw_arg2)
        yaw_deg = yaw_rad * 180.0 / pi

        # Convert yaw from [-180, 180] range to [0, 360] clockwise
        # Standard mathematical yaw is counter-clockwise from +X axis.
        # Assuming heading is clockwise from North (often aligned with +Y or +X depending on setup).
        # Let's assume standard aerospace sequence (North = +X, East = +Y) -> Yaw is rotation around Z.
        # A positive yaw_deg means rotation towards +Y (East) from +X (North).
        # Heading = 360 - Yaw (if Yaw > 0) or abs(Yaw) (if Yaw < 0) is NOT standard.
        # Correct conversion: Heading = (90 - yaw_deg) % 360 (if North=+Y)
        # Or Heading = ( - yaw_deg ) % 360 (if North = +X, and heading is clockwise?)
        # Let's stick to the previous implementation's convention for now:
        if yaw_deg > 0:
            heading = 360.0 - yaw_deg
        else:
            heading = abs(yaw_deg)

        return heading # Returns 0-360 clockwise, interpretation depends on frame

    def calculate_energy(self, linear_acceleration: Tuple[float, float, float],
                         gyro: Tuple[float, float, float],
                         accel_weight: float = MoveActivityConfig.ACCEL_WEIGHT,
                         gyro_weight: float = MoveActivityConfig.GYRO_WEIGHT) -> float:
        """
        Calculate a normalized movement energy level (0-1).
        Combines weighted linear acceleration and rotation magnitudes.
        Assumes typical maximum values for normalization.
        """
        # Calculate acceleration magnitude
        try:
            accel_magnitude_sq = linear_acceleration[0]**2 + linear_acceleration[1]**2 + linear_acceleration[2]**2
            accel_magnitude = sqrt(accel_magnitude_sq) if accel_magnitude_sq >=0 else 0.0
        except (TypeError, IndexError):
             accel_magnitude = 0.0

        # Normalize acceleration
        max_accel = 20.0  # m/s^2 (Adjust if needed)
        accel_energy = min(1.0, accel_magnitude / max_accel if max_accel > 0 else 0.0)

        # Calculate rotation magnitude
        try:
             gyro_magnitude_sq = gyro[0]**2 + gyro[1]**2 + gyro[2]**2
             gyro_magnitude = sqrt(gyro_magnitude_sq) if gyro_magnitude_sq >= 0 else 0.0
        except (TypeError, IndexError):
             gyro_magnitude = 0.0

        # Normalize rotation
        max_gyro = 10.0  # rad/s (Adjust if needed)
        gyro_energy = min(1.0, gyro_magnitude / max_gyro if max_gyro > 0 else 0.0)

        # Combine energies with weights
        total_weight = accel_weight + gyro_weight
        if total_weight <= 0: return 0.0 # Avoid division by zero if weights are invalid
        # Ensure weights are non-negative
        accel_w = max(0.0, accel_weight)
        gyro_w = max(0.0, gyro_weight)

        # Weighted average (normalized by sum of weights)
        return (accel_energy * accel_w + gyro_energy * gyro_w) / (accel_w + gyro_w)

    def get_current_state(self) -> str:
        """
        Get the name of the currently detected simplified motion state.

        Returns:
            str: Name of the current SimplifiedState enum member.
        """
        return self.current_state.name

    async def check_and_calibrate(self) -> bool:
        """
        Check calibration status via the hardware interface and attempt calibration if needed.
        """
        return await self.interface.check_and_calibrate()

    def print_data(self, data: Dict[str, Any]):
        """
        Print sensor data dictionary to console with formatting.
        Useful for debugging.
        """
        print("--- Sensor Data ---")
        for key, value in sorted(data.items()): # Sort keys for consistent output
            if isinstance(value, tuple) and all(isinstance(v, (int, float)) for v in value):
                # Format tuples of numbers nicely
                components = ", ".join(f"{val:.3f}" for val in value)
                print(f"  {key:<25}: ({components})")
            elif isinstance(value, float):
                 print(f"  {key:<25}: {value:.4f}")
            elif isinstance(value, SimplifiedState): # Handle state enum if passed directly
                 print(f"  {key:<25}: {value.name}")
            else:
                # Print other types as strings, aligned
                print(f"  {key:<25}: {str(value)}")
        print("-------------------")