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
    Uses the BNO085's stability classification for STATIONARY and HELD_STILL states.
    Uses acceleration magnitude and history for IMPACT, SHAKE, and FREE_FALL.
    """

    def __init__(self):
        """Initialize the AccelerometerManager"""
        self.interface = BNO085Interface()
        self.logger = logging.getLogger(__name__)

        # --- History ---
        # Store recent motion samples.  Needs to be at least as long as `self.shake_history_size`.
        self.motion_history = deque(maxlen=40)  # 40 samples ≈ 0.2 s at 200 Hz

        # --- Thresholds ---
        # Stationary / Held Still (Now determined by BNO085 stability report)
        # Removed self.stationary_max_accel
        # Removed self.held_still_min_accel
        # Removed self.held_still_max_accel
        # Removed self.stationary_duration
        # Removed self.held_still_duration

        # Free Fall / Impact - Multi-sensor approach
        # Free fall detection using sensor fusion for accuracy
        self.free_fall_accel_threshold = 7.0    # m/s^2 - Max total accel magnitude for FREE_FALL (more realistic)
        self.free_fall_min_rotation = 1.0       # rad/s - Min gyro magnitude indicating tumbling motion
        self.free_fall_min_duration = 0.02      # seconds - Min duration to confirm free fall (1-2 samples)
        self.free_fall_max_duration = 5.0       # seconds - Max reasonable free fall duration
        self.impact_threshold = 15.0             # m/s^2 - Min accel spike for IMPACT
        
        # Free fall state tracking
        self.free_fall_start_time = None
        self.free_fall_candidate_start = None

        # Shake detection tuning (peak-magnitude approach)
        self.shake_history_size = 30            # Samples (~0.15–0.2 s at 200 Hz)
        self.peak_magnitude_for_shake = 8.0     # m/s^2 – require at least one spike ≥ 0.8 g
        self.min_magnitude_for_shake = 2.0      # m/s^2 – discard almost-still windows
        self.min_accel_reversals_for_shake = 3  # Require back-and-forth motion

        # --- History ---
        # Make sure the buffer can always accommodate at least `shake_history_size` samples.
        # If the constant above is ever increased but `motion_history` was left smaller, resize it here.
        if self.motion_history.maxlen < self.shake_history_size:
            new_len = self.shake_history_size * 2  # keep extra headroom for other algorithms
            self.logger.warning(
                "motion_history.maxlen (%s) smaller than shake_history_size (%s); resizing to %s", 
                self.motion_history.maxlen, self.shake_history_size, new_len
            )
            # Recreate deque preserving any samples already stored (should be empty at init time)
            self.motion_history = deque(self.motion_history, maxlen=new_len)

        # --- State Tracking ---
        # Removed self.in_stationary_band_start_time
        # Removed self.in_held_still_band_start_time
        self.last_accel_magnitude = 0.0          # Store previous accel magnitude for impact detection edge
        self.current_state = SimplifiedState.UNKNOWN # Store the determined state

        # --- Quaternion / Rotation Tracking ---
        # Cache the previous Game Rotation quaternion to compute rotational speed
        self._prev_game_quat: Optional[Tuple[float, float, float, float]] = None
        self._prev_quat_ts: float = 0.0

        # Low-motion thresholds used to validate BNO stability reports
        self.low_linear_accel_max = 1.0   # m/s^2 – ~0.1 g tolerance
        self.low_rot_speed_max   = 0.5   # rad/s  – slow orientation drift

    async def initialize(self) -> bool:
        """
        Initialize the accelerometer hardware.

        Returns:
            bool: True if initialization was successful, False otherwise
        """
        return await self.interface.initialize()

    def deinitialize(self):
        """
        Deinitialize the accelerometer hardware.
        """
        self.interface.deinitialize()

    async def read_sensor_data(self) -> Dict[str, Any]:
        """
        Read raw sensor data and determine the simplified motion state.

        Returns:
            Dict[str, Any]: Dictionary containing sensor readings and the detected state name.
        """
        data = await self.interface.read_sensor_data()
        current_time = time.time()
        data['timestamp'] = current_time # Add timestamp immediately

        # Skip expensive calculations for performance optimization
        # Only calculate rotation speed (needed for state detection)
        rot_speed = 0.0
        if "game_rotation" in data and isinstance(data["game_rotation"], tuple) and len(data["game_rotation"]) == 4:
            current_quat = data["game_rotation"]
            now_ts = current_time
            # Compute rotational speed if we have a previous quaternion
            if self._prev_game_quat is not None and now_ts > self._prev_quat_ts:
                dt = now_ts - self._prev_quat_ts
                if dt > 0:
                    rot_speed = self._rotation_speed_from_quats(self._prev_game_quat, current_quat, dt)
            # Cache for next iteration regardless
            self._prev_game_quat = current_quat
            self._prev_quat_ts = now_ts
        data["rot_speed"] = rot_speed

        # Skip heading and energy calculations for performance
        # These can be added back if needed for specific applications

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
        Checks for IMPACT, SHAKE, then uses BNO stability for STATIONARY/HELD_STILL,
        then checks FREE_FALL. Requires linear_acceleration and stability data.

        Args:
            current_data: Current sensor readings dictionary.

        Returns:
            SimplifiedState: The detected state.
        """
        if len(self.motion_history) < 2: # Need at least previous + current
            self.last_accel_magnitude = 0.0 # Reset on insufficient history
            # No timers to reset now
            return SimplifiedState.UNKNOWN

        # Use RAW acceleration for free fall detection
        accel_raw = current_data.get("acceleration", None)
        # Still need linear accel for other checks like shake, keep it
        linear_accel = current_data.get("linear_acceleration", None)
        timestamp = current_data.get('timestamp', time.time()) # Use provided or current time
        stability = current_data.get("stability", "Unknown") # Get stability from BNO

        # Validate RAW acceleration for free fall check
        if not (isinstance(accel_raw, tuple) and len(accel_raw) == 3 and
                all(isinstance(x, (int, float)) for x in accel_raw)):
            self.logger.warning(f"Invalid/missing RAW acceleration for free fall detection: {accel_raw}")
            # If raw is bad, can we still determine state? Maybe fallback needed?
            # For now, treat as UNKNOWN if raw is missing, might prevent free fall detection.
            self.last_accel_magnitude = 0.0 # Reset based on linear or raw? Let's use linear for consistency with IMPACT.
            return SimplifiedState.UNKNOWN

        # Calculate RAW acceleration magnitude for free fall check
        accel_magnitude_raw = sqrt(sum(x*x for x in accel_raw))

        # Calculate Linear acceleration magnitude for IMPACT/other checks (if needed)
        # Need to handle potential missing linear_accel for subsequent checks (e.g. IMPACT)
        accel_magnitude_linear = 0.0
        if isinstance(linear_accel, tuple) and len(linear_accel) == 3:
            try:
                accel_magnitude_linear = sqrt(sum(x*x for x in linear_accel))
            except TypeError:
                 self.logger.warning(f"Invalid linear acceleration data: {linear_accel}, falling back to magnitude 0")
                 accel_magnitude_linear = 0.0 # Fallback
        else:
            # If linear accel is missing/invalid, impact/shake detection might fail later.
            # Log this potential issue.
            self.logger.warning(f"Missing or invalid linear acceleration: {linear_accel}. Impact/Shake detection may be affected.")
            # Keep accel_magnitude_linear as 0.0

        # --- State Checks (Prioritized) ---
        # Desired order: IMPACT (from FREE_FALL) -> STATIONARY/HELD_STILL -> SHAKE -> FREE_FALL -> MOVING
        # Check stability-based states first to avoid false FREE_FALL detection when stationary

        # 1. IMPACT: Check for a sudden spike AND if the previous state was FREE_FALL
        previous_state = self.current_state # Store state from *before* this determination
        is_potential_impact = (accel_magnitude_linear >= self.impact_threshold and
                               self.last_accel_magnitude < self.impact_threshold)

        if is_potential_impact and previous_state == SimplifiedState.FREE_FALL:
            self.logger.debug(f"IMPACT detected (from FREE_FALL): Linear Accel {self.last_accel_magnitude:.2f} -> {accel_magnitude_linear:.2f}")
            # Update last magnitude based on what impact check used (linear)
            self.last_accel_magnitude = accel_magnitude_linear
            return SimplifiedState.IMPACT
        # Optional: Log if potential impact occurs but not from FREE_FALL?
        elif is_potential_impact:
             self.logger.debug(f"Potential impact ignored (not from FREE_FALL): Prev State={previous_state.name}, Accel {self.last_accel_magnitude:.2f} -> {accel_magnitude_linear:.2f}")

        # 2. STATIONARY / HELD_STILL (use sensor data directly, ignore slow BNO stability)
        rot_speed_current = current_data.get("rot_speed", 0.0)
        gyro = current_data.get("gyro", (0, 0, 0))
        gyro_mag = sqrt(sum(x*x for x in gyro)) if isinstance(gyro, tuple) and len(gyro) == 3 else 0.0

        # Very strict stationary detection: extremely low motion on all sensors
        is_very_still = (accel_magnitude_linear < 0.1 and  # Very low linear acceleration
                        gyro_mag < 0.05 and               # Very low rotation
                        rot_speed_current < 0.1)          # Very low quaternion-derived rotation

        # Moderately still (held by hand with slight tremor)
        is_held_still = (accel_magnitude_linear < self.low_linear_accel_max and 
                        gyro_mag < 0.2 and 
                        rot_speed_current < self.low_rot_speed_max)

        if is_very_still:
            self.last_accel_magnitude = accel_magnitude_linear
            return SimplifiedState.STATIONARY
        elif is_held_still:
            self.last_accel_magnitude = accel_magnitude_linear
            return SimplifiedState.HELD_STILL

        # 3. SHAKE: Either library-provided shake report OR our custom algorithm.
        # Built-in shake detection (from activity classifier or dedicated shake detector)
        bno_reports_shake = self._sensor_reports_shake(current_data.get("shake", False))
        custom_shake = self._check_shake()
        if bno_reports_shake or custom_shake:
            self.logger.debug("SHAKE detected (built-in:%s custom:%s)", bno_reports_shake, custom_shake)
            self.last_accel_magnitude = accel_magnitude_linear
            return SimplifiedState.SHAKE

        # 4. FREE_FALL: Multi-sensor fusion approach
        # Check for free fall using total acceleration, gyroscope, and duration
        free_fall_detected = self._detect_free_fall_multisensor(
            accel_magnitude_raw, 
            current_data.get("gyro", (0, 0, 0)), 
            stability, 
            timestamp
        )
        
        if free_fall_detected:
            if self.current_state != SimplifiedState.FREE_FALL:
                self.logger.debug(f"FREE_FALL detected: Total Accel={accel_magnitude_raw:.2f}, Stability={stability}")
            self.last_accel_magnitude = accel_magnitude_linear
            return SimplifiedState.FREE_FALL

        # 5. MOVING: If none of the specific states above are met
        # (includes BNO "In motion" or "Unknown" stability if not caught by other states)
        # Only log if state changes
        if self.current_state != SimplifiedState.MOVING:
            self.logger.debug(f"MOVING state: Linear Accel={accel_magnitude_linear:.2f}, Stability={stability}")
        self.last_accel_magnitude = accel_magnitude_linear # Update based on linear
        return SimplifiedState.MOVING

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

        # === Magnitude Check (peak-based) ===
        accel_magnitudes = []
        for accel in valid_accelerations:
            try:
                # Compute magnitude squared and avoid sqrt of negatives
                mag_sq = accel[0]**2 + accel[1]**2 + accel[2]**2
                if mag_sq >= 0:
                    accel_magnitudes.append(sqrt(mag_sq))
            except (TypeError, IndexError):
                continue  # skip malformed sample

        if len(accel_magnitudes) < 5:
            return False

        peak_accel_magnitude = max(accel_magnitudes)
        avg_accel_magnitude  = statistics.mean(accel_magnitudes)

        # Need at least one strong spike
        if peak_accel_magnitude < self.peak_magnitude_for_shake:
            return False

        # Also reject windows that are nearly still overall
        if avg_accel_magnitude < self.min_magnitude_for_shake:
            return False

        # --- Passed Checks ---
        return True

    def _sensor_reports_shake(self, shake_val: Any) -> bool:
        """Return True if sensor indicates a shake via the dedicated SHAKE_DETECTOR.

        The Adafruit driver exposes a latched boolean at `imu.shake`; we ferry that
        through `data['shake']`.  Just verify it's truthy and boolean.
        """
        return bool(shake_val)

    def _detect_free_fall_multisensor(self, total_accel_mag: float, gyro: Tuple[float, float, float], 
                                    stability: str, timestamp: float) -> bool:
        """
        Detect free fall using multi-sensor fusion approach.
        
        True free fall characteristics:
        1. Low total acceleration (weightlessness)
        2. Some rotational motion (objects tumble during free fall)
        3. NOT extremely still (rules out stationary objects)
        4. Sustained for minimum duration
        
        Args:
            total_accel_mag: Total acceleration magnitude (m/s²)
            gyro: Gyroscope readings (rad/s)
            stability: BNO085 stability classification (ignored, kept for compatibility)
            timestamp: Current timestamp
            
        Returns:
            bool: True if free fall is detected
        """
        # Calculate gyroscope magnitude
        try:
            gyro_mag = sqrt(sum(x*x for x in gyro)) if isinstance(gyro, tuple) and len(gyro) == 3 else 0.0
        except (TypeError, ValueError):
            gyro_mag = 0.0
        
        # Rule out if device is extremely still (stationary detection)
        # Use stricter thresholds than the main stationary detection to avoid conflicts
        is_extremely_still = (total_accel_mag > 9.0 and total_accel_mag < 11.0 and  # Near 1g (9.8 m/s²) - sitting still
                             gyro_mag < 0.1)  # Almost no rotation
        
        if is_extremely_still:
            self._reset_free_fall_tracking()
            return False
        
        # Check if current conditions suggest free fall candidate
        is_low_accel = total_accel_mag < self.free_fall_accel_threshold
        has_rotation = gyro_mag > self.free_fall_min_rotation
        
        # Free fall requires BOTH low acceleration AND some rotation
        # (stationary objects have low accel but no rotation)
        is_free_fall_candidate = is_low_accel and has_rotation
        
        if is_free_fall_candidate:
            # Start tracking if this is the first candidate sample
            if self.free_fall_candidate_start is None:
                self.free_fall_candidate_start = timestamp
                self.logger.debug(f"Free fall candidate started: accel={total_accel_mag:.2f}, gyro={gyro_mag:.3f}")
                return False  # Don't declare free fall immediately
            
            # Check if we've sustained the conditions long enough
            duration = timestamp - self.free_fall_candidate_start
            
            if duration >= self.free_fall_min_duration:
                # Confirm free fall and start official tracking
                if self.free_fall_start_time is None:
                    self.free_fall_start_time = self.free_fall_candidate_start
                    self.logger.debug(f"FREE_FALL confirmed after {duration:.3f}s")
                
                # Check for maximum reasonable duration
                total_duration = timestamp - self.free_fall_start_time
                if total_duration > self.free_fall_max_duration:
                    self.logger.warning(f"Free fall duration exceeded maximum ({total_duration:.1f}s), resetting")
                    self._reset_free_fall_tracking()
                    return False
                
                return True
            else:
                # Still building up to minimum duration
                return False
        else:
            # Conditions no longer met, reset tracking
            if self.free_fall_candidate_start is not None:
                duration = timestamp - self.free_fall_candidate_start
                self.logger.debug(f"Free fall candidate ended after {duration:.3f}s: accel={total_accel_mag:.2f}, gyro={gyro_mag:.3f}")
            self._reset_free_fall_tracking()
            return False
    
    def _reset_free_fall_tracking(self):
        """Reset free fall tracking state."""
        self.free_fall_start_time = None
        self.free_fall_candidate_start = None

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
                         gyro_weight: float = MoveActivityConfig.GYRO_WEIGHT,
                         rot_speed: float = 0.0,
                         rot_weight: float = MoveActivityConfig.ROT_WEIGHT) -> float:
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

        # Normalize gyro rotation magnitude
        max_gyro = 10.0  # rad/s (Adjust if needed)
        gyro_energy = min(1.0, gyro_magnitude / max_gyro if max_gyro > 0 else 0.0)

        # Normalize quaternion-derived rotation speed
        max_rot = 10.0  # rad/s (tunable)
        rot_energy = min(1.0, rot_speed / max_rot if max_rot > 0 else 0.0)

        # Combine energies with weights
        total_weight = accel_weight + gyro_weight + rot_weight
        if total_weight <= 0: return 0.0 # Avoid division by zero if weights are invalid
        # Ensure weights are non-negative
        accel_w = max(0.0, accel_weight)
        gyro_w = max(0.0, gyro_weight)
        rot_w = max(0.0, rot_weight)

        # Weighted average (normalized by sum of weights)
        return (accel_energy * accel_w + gyro_energy * gyro_w + rot_energy * rot_w) / (accel_w + gyro_w + rot_w)

    @staticmethod
    def _rotation_speed_from_quats(q_prev: Tuple[float, float, float, float],
                                   q_cur: Tuple[float, float, float, float],
                                   dt: float) -> float:
        """Compute absolute rotational speed (rad/s) between two orientation quaternions"""
        if dt <= 0:
            return 0.0
        # Dot product gives cos(theta/2) where theta is angle between orientations
        dot = abs(q_prev[0]*q_cur[0] + q_prev[1]*q_cur[1] + q_prev[2]*q_cur[2] + q_prev[3]*q_cur[3])
        # Clamp to valid range for acos to avoid NaNs due to numerical error
        dot = min(1.0, max(-1.0, dot))
        theta = 2.0 * acos(dot)  # Angle in radians
        return theta / dt

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