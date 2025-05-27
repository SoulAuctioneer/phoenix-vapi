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

        # Free Fall / Impact - Multi-sensor approach with stricter criteria
        # Free fall detection using sensor fusion for accuracy
        self.free_fall_accel_threshold = 6.0     # m/s^2 - Increased from 4.0 to accommodate real throws
        self.free_fall_min_rotation = 2.0       # rad/s - Reduced from 2.5 to catch gentler throws
        self.free_fall_max_rotation = 15.0      # rad/s - Upper limit to exclude violent shaking
        self.free_fall_min_duration = 0.05      # seconds - Longer minimum duration (was 0.02)
        self.free_fall_max_duration = 5.0       # seconds - Max reasonable free fall duration
        
        # Additional criteria to distinguish from gentle movements
        self.free_fall_linear_accel_max = 12.0   # m/s^2 - Increased from 4.0 due to sensor noise in linear accel during real free fall
        self.free_fall_accel_consistency_samples = 3  # Require consistent readings
        
        self.impact_threshold = 15.0             # m/s^2 - Min accel spike for IMPACT
        
        # Free fall state tracking
        self.free_fall_start_time = None
        self.free_fall_candidate_start = None

        # Shake detection tuning (enhanced 3D vector approach)
        self.shake_history_size = 30            # Samples (~0.15–0.2 s at 200 Hz)
        self.peak_magnitude_for_shake = 12.0     # m/s^2 – increased from 11.0 to require stronger motion
        self.min_magnitude_for_shake = 6.0      # m/s^2 – increased from 5.0 to filter out gentle movements
        self.min_accel_reversals_for_shake = 6  # Increased from 4 - require more direction changes for true shake

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
        self.last_accel_magnitude = 0.0          # Store previous accel magnitude for impact detection edge
        self.current_state = SimplifiedState.UNKNOWN # Store the determined state
        
        # State stability tracking to prevent rapid oscillation
        self.state_change_time = 0.0              # When the last state change occurred
        self.min_state_duration = 1.0             # Minimum time to stay in a state (1000ms) - increased from 500ms

        # --- Quaternion / Rotation Tracking ---
        # Cache the previous Game Rotation quaternion to compute rotational speed
        self._prev_game_quat: Optional[Tuple[float, float, float, float]] = None
        self._prev_quat_ts: float = 0.0

        # Improved thresholds with hysteresis for stable state detection
        # Based on real-world testing showing oscillation between 0.05-0.47 m/s² when "holding steady"
        # AND observed "completely stationary" values up to 0.048 m/s² linear, 0.029 rad/s gyro
        # Need much larger separation between STATIONARY and HELD_STILL to prevent oscillation
        
        # STATIONARY: Device completely still (on table, etc.) - RELAXED THRESHOLDS
        # Real stationary devices can have sensor noise, so be more realistic
        self.stationary_linear_accel_max = 0.10   # m/s² - More realistic for sensor noise (was 0.05)
        self.stationary_gyro_max = 0.05           # rad/s - More realistic for sensor noise (was 0.02)
        self.stationary_rot_speed_max = 0.05      # rad/s - More realistic for sensor noise (was 0.02)
        self.stationary_consistency_required = 5  # Require 5 consecutive consistent readings
        self.stationary_max_variance = 0.005     # m/s² - Much more lenient variance threshold (was 0.001)
        self.stationary_min_duration = 1.0       # seconds - Shorter duration for faster detection (was 2.0)
        
        # HELD_STILL: Device held by hand - More permissive with large gap
        self.held_still_linear_accel_max = 1.5    # m/s² - Large gap above STATIONARY
        self.held_still_gyro_max = 0.50           # rad/s - More permissive for hand tremor
        self.held_still_rot_speed_max = 0.50      # rad/s - More permissive for hand tremor
        
        # Hysteresis: Moderate hysteresis to prevent oscillation but allow transitions
        self.hysteresis_factor = 2.0               # Reduced from 4.0 for easier transitions
        
        # Stationary state tracking for consistency checking
        self.stationary_candidate_start = None
        self.stationary_candidate_readings = deque(maxlen=10)  # Store recent readings for variance check

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
        data = await self.interface.read_sensor_data_optimized()
        current_time = time.time()
        data['timestamp'] = current_time # Add timestamp immediately

        # Skip expensive calculations for performance optimization
        # Only calculate rotation speed (needed for state detection)
        rot_speed = 0.0
        # DISABLED: Quaternion rotation speed calculation causes false motion detection due to numerical noise
        # if "game_rotation" in data and isinstance(data["game_rotation"], tuple) and len(data["game_rotation"]) == 4:
        #     current_quat = data["game_rotation"]
        #     now_ts = current_time
        #     # Compute rotational speed if we have a previous quaternion
        #     if self._prev_game_quat is not None and now_ts > self._prev_quat_ts:
        #         dt = now_ts - self._prev_quat_ts
        #         if dt > 0:
        #             rot_speed = self._rotation_speed_from_quats(self._prev_game_quat, current_quat, dt)
        #     # Cache for next iteration regardless
        #     self._prev_game_quat = current_quat
        #     self._prev_quat_ts = now_ts
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
        Determine the current motion state with stability and hysteresis to prevent oscillation.
        
        Args:
            current_data: Current sensor readings dictionary.

        Returns:
            SimplifiedState: The detected state.
        """
        if len(self.motion_history) < 2:
            self.last_accel_magnitude = 0.0
            return SimplifiedState.UNKNOWN

        # Extract sensor data
        accel_raw = current_data.get("acceleration", None)
        linear_accel = current_data.get("linear_acceleration", None)
        gyro = current_data.get("gyro", (0, 0, 0))
        timestamp = current_data.get('timestamp', time.time())
        rot_speed_current = current_data.get("rot_speed", 0.0)

        # Validate essential data
        if not (isinstance(accel_raw, tuple) and len(accel_raw) == 3 and
                all(isinstance(x, (int, float)) for x in accel_raw)):
            self.last_accel_magnitude = 0.0
            return SimplifiedState.UNKNOWN

        if not (isinstance(linear_accel, tuple) and len(linear_accel) == 3):
            self.last_accel_magnitude = 0.0
            return SimplifiedState.UNKNOWN

        # Calculate magnitudes
        accel_magnitude_raw = sqrt(sum(x*x for x in accel_raw))
        accel_magnitude_linear = sqrt(sum(x*x for x in linear_accel))
        gyro_mag = sqrt(sum(x*x for x in gyro)) if isinstance(gyro, tuple) and len(gyro) == 3 else 0.0

        # Store previous state for comparison
        previous_state = self.current_state

        # --- Priority 1: IMPACT (from FREE_FALL) ---
        is_potential_impact = (accel_magnitude_linear >= self.impact_threshold and
                               self.last_accel_magnitude < self.impact_threshold)
        
        if is_potential_impact and previous_state == SimplifiedState.FREE_FALL:
            self.last_accel_magnitude = accel_magnitude_linear
            self._update_state_tracking(SimplifiedState.IMPACT, timestamp)
            return SimplifiedState.IMPACT

        # --- Priority 2: FREE_FALL (higher priority than SHAKE for better detection) ---
        free_fall_detected = self._detect_free_fall_multisensor(
            accel_magnitude_raw, gyro, "Unknown", timestamp
        )
        
        if free_fall_detected:
            self.last_accel_magnitude = accel_magnitude_linear
            self._update_state_tracking(SimplifiedState.FREE_FALL, timestamp)
            return SimplifiedState.FREE_FALL

        # --- Priority 3: SHAKE (software-only detection since BNO sensor disabled) ---
        custom_shake = self._check_shake()
        
        # Check if we've been in SHAKE state too long (add timeout)
        time_in_shake = 0.0
        if previous_state == SimplifiedState.SHAKE:
            time_in_shake = timestamp - self.state_change_time
        
        # Prevent false SHAKE detection immediately after IMPACT (post-impact oscillations)
        # This addresses the issue where catching the device after impact causes oscillations
        # that are incorrectly detected as intentional shaking
        allow_shake_transition = previous_state != SimplifiedState.IMPACT
        
        # Use only custom shake detection (BNO shake sensor disabled for performance)
        if custom_shake and time_in_shake < 2.0 and allow_shake_transition:  # 2 second timeout + no IMPACT→SHAKE
            self.last_accel_magnitude = accel_magnitude_linear
            self._update_state_tracking(SimplifiedState.SHAKE, timestamp)
            return SimplifiedState.SHAKE

        # --- Priority 4: STATIONARY/HELD_STILL with hysteresis ---
        candidate_state = self._determine_stable_state(
            accel_magnitude_linear, gyro_mag, rot_speed_current, previous_state
        )
        
        # Apply state stability logic
        stable_state = self._apply_state_stability(candidate_state, timestamp)
        
        self.last_accel_magnitude = accel_magnitude_linear
        return stable_state

    def _determine_stable_state(self, linear_accel_mag: float, gyro_mag: float, 
                               rot_speed: float, current_state: SimplifiedState) -> SimplifiedState:
        """
        Determine if device is in STATIONARY, HELD_STILL, or MOVING state with improved hysteresis
        and realistic STATIONARY detection with consistency checking.
        
        STATIONARY now requires:
        1. Realistic sensor readings (accommodating sensor noise)
        2. Consistent readings over multiple samples
        3. Reasonable variance in acceleration (not perfect stillness)
        4. Sustained duration
        
        This allows truly stationary devices to be detected while preventing hand tremor classification.
        """
        
        # Store current reading for variance analysis
        self.stationary_candidate_readings.append(linear_accel_mag)
        
        # Define base thresholds
        stationary_linear_base = self.stationary_linear_accel_max
        stationary_gyro_base = self.stationary_gyro_max
        stationary_rot_base = self.stationary_rot_speed_max
        
        held_still_linear_base = self.held_still_linear_accel_max
        held_still_gyro_base = self.held_still_gyro_max
        held_still_rot_base = self.held_still_rot_speed_max
        
        # Apply moderate hysteresis based on current state
        if current_state == SimplifiedState.STATIONARY:
            # Currently STATIONARY - use slightly higher thresholds to exit (moderate hysteresis)
            stationary_linear_threshold = stationary_linear_base * self.hysteresis_factor
            stationary_gyro_threshold = stationary_gyro_base * self.hysteresis_factor
            stationary_rot_threshold = stationary_rot_base * self.hysteresis_factor
            
            # For HELD_STILL, use normal thresholds (easier to transition to)
            held_still_linear_threshold = held_still_linear_base
            held_still_gyro_threshold = held_still_gyro_base
            held_still_rot_threshold = held_still_rot_base
            
        elif current_state == SimplifiedState.HELD_STILL:
            # Currently HELD_STILL - use moderate hysteresis to exit
            held_still_linear_threshold = held_still_linear_base * self.hysteresis_factor
            held_still_gyro_threshold = held_still_gyro_base * self.hysteresis_factor
            held_still_rot_threshold = held_still_rot_base * self.hysteresis_factor
            
            # For STATIONARY, use normal thresholds (allow transition if truly stationary)
            stationary_linear_threshold = stationary_linear_base
            stationary_gyro_threshold = stationary_gyro_base
            stationary_rot_threshold = stationary_rot_base
            
        else:
            # Not currently in a stable state - use normal thresholds for entry
            stationary_linear_threshold = stationary_linear_base
            stationary_gyro_threshold = stationary_gyro_base
            stationary_rot_threshold = stationary_rot_base
            
            held_still_linear_threshold = held_still_linear_base
            held_still_gyro_threshold = held_still_gyro_base
            held_still_rot_threshold = held_still_rot_base
        
        # Check basic STATIONARY criteria (must pass these first)
        meets_basic_stationary = (linear_accel_mag < stationary_linear_threshold and
                                 gyro_mag < stationary_gyro_threshold and
                                 rot_speed < stationary_rot_threshold)
        
        # Enhanced STATIONARY detection with consistency and variance checking
        is_truly_stationary = False
        if meets_basic_stationary:
            is_truly_stationary = self._verify_stationary_consistency(
                linear_accel_mag, gyro_mag, rot_speed, current_state
            )
        else:
            # Only reset stationary tracking if we've been failing for a while
            # This prevents constant restarting due to brief sensor spikes
            if self.stationary_candidate_start is not None:
                current_time = time.time()
                time_since_start = current_time - self.stationary_candidate_start
                # Only reset if we've been trying for more than 0.5 seconds and still failing
                if time_since_start > 0.5:
                    # self.logger.debug(f"STATIONARY candidate reset after {time_since_start:.1f}s of failing basic criteria")
                    self.stationary_candidate_start = None
        
        # Check for HELD_STILL (less restrictive)
        is_held_still = (linear_accel_mag < held_still_linear_threshold and
                        gyro_mag < held_still_gyro_threshold and
                        rot_speed < held_still_rot_threshold)
        
        # Debug logging for state transitions to understand threshold behavior
        if current_state in [SimplifiedState.STATIONARY, SimplifiedState.HELD_STILL]:
            if is_truly_stationary:
                candidate_state = SimplifiedState.STATIONARY
            elif is_held_still:
                candidate_state = SimplifiedState.HELD_STILL
            else:
                candidate_state = SimplifiedState.MOVING
                
            # if candidate_state != current_state:
            #     self.logger.debug(f"State transition candidate: {current_state.name} → {candidate_state.name}")
            #     self.logger.debug(f"  Linear: {linear_accel_mag:.3f} (STAT<{stationary_linear_threshold:.3f}, HELD<{held_still_linear_threshold:.3f})")
            #     self.logger.debug(f"  Gyro: {gyro_mag:.3f} (STAT<{stationary_gyro_threshold:.3f}, HELD<{held_still_gyro_threshold:.3f})")
            #     self.logger.debug(f"  RotSpeed: {rot_speed:.3f} (STAT<{stationary_rot_threshold:.3f}, HELD<{held_still_rot_threshold:.3f})")
            #     self.logger.debug(f"  STATIONARY checks: basic={meets_basic_stationary}, truly={is_truly_stationary}")
        
        if is_truly_stationary:
            return SimplifiedState.STATIONARY

        if is_held_still:
            return SimplifiedState.HELD_STILL

        # Default to MOVING
        return SimplifiedState.MOVING
    
    def _verify_stationary_consistency(self, linear_accel_mag: float, gyro_mag: float, 
                                     rot_speed: float, current_state: SimplifiedState) -> bool:
        """
        Verify that the device is truly stationary using consistency and variance checks.
        
        True stationary devices should have:
        1. Consistent readings over time
        2. Reasonable variance in acceleration (accommodating sensor noise)
        3. Sustained low readings
        
        Args:
            linear_accel_mag: Current linear acceleration magnitude
            gyro_mag: Current gyroscope magnitude  
            rot_speed: Current rotation speed
            current_state: Current state for tracking
            
        Returns:
            bool: True if device is truly stationary
        """
        current_time = time.time()
        
        # Start tracking if this is the first qualifying sample
        if self.stationary_candidate_start is None:
            self.stationary_candidate_start = current_time
            # self.logger.debug(f"STATIONARY candidate started: linear={linear_accel_mag:.3f}, gyro={gyro_mag:.3f}")
            return False  # Don't declare stationary immediately
        
        # Check if we have enough readings for variance analysis
        if len(self.stationary_candidate_readings) < self.stationary_consistency_required:
            return False
        
        # Calculate variance in recent linear acceleration readings
        recent_readings = list(self.stationary_candidate_readings)[-self.stationary_consistency_required:]
        if len(recent_readings) >= 3:  # Need at least 3 points for meaningful variance
            try:
                variance = statistics.variance(recent_readings)
                
                # Debug: Show the actual readings that led to this variance
                readings_str = ", ".join([f"{r:.4f}" for r in recent_readings])
                
                # Only log variance check occasionally to avoid spam
                duration_so_far = current_time - self.stationary_candidate_start
                should_log_variance = (duration_so_far < 0.5) or (int(duration_so_far * 10) % 10 == 0)  # Log first 0.5s, then every 0.1s
                # DISABLE because it's spammy
                should_log_variance = False
                
                if should_log_variance:
                    self.logger.debug(f"STATIONARY variance check: readings=[{readings_str}], variance={variance:.6f}")
                
                # Use realistic variance threshold based on actual sensor behavior
                # Real stationary devices can have sensor noise fluctuations
                adjusted_variance_threshold = self.stationary_max_variance
                
                # Be more lenient with variance - only reject if variance is extremely high
                if variance > adjusted_variance_threshold:
                    # Don't immediately restart - be more patient with sensor noise
                    # Only restart if variance is extremely high (10x threshold) or we've been trying for a long time
                    extreme_threshold = adjusted_variance_threshold * 10  # 10x more lenient
                    
                    if variance > extreme_threshold:
                        self.logger.debug(f"STATIONARY rejected: extreme variance {variance:.6f} > {extreme_threshold:.6f}")
                        self.stationary_candidate_start = None
                        return False
                    elif duration_so_far > 3.0:  # After 3 seconds, be stricter
                        self.logger.debug(f"STATIONARY rejected: variance {variance:.6f} > {adjusted_variance_threshold:.6f} after {duration_so_far:.1f}s")
                        self.stationary_candidate_start = None
                        return False
                    else:
                        # Continue tracking despite high variance - sensor might stabilize
                        if should_log_variance:
                            self.logger.debug(f"STATIONARY variance high but continuing: {variance:.6f} > {adjusted_variance_threshold:.6f} (will retry)")
                else:
                    if should_log_variance:
                        self.logger.debug(f"STATIONARY variance good: {variance:.6f} <= {adjusted_variance_threshold:.6f}")
            except statistics.StatisticsError:
                return False
        
        # Check duration requirement
        duration = current_time - self.stationary_candidate_start
        
        if duration >= self.stationary_min_duration:
            # Calculate final variance for logging
            try:
                final_variance = statistics.variance(recent_readings) if len(recent_readings) >= 3 else 0.0
            except statistics.StatisticsError:
                final_variance = 0.0
            #self.logger.debug(f"STATIONARY confirmed: duration={duration:.1f}s, variance={final_variance:.6f}")
            return True
        
        # Still building up consistency - show progress occasionally
        if should_log_variance:
            self.logger.debug(f"STATIONARY building consistency: duration={duration:.1f}s/{self.stationary_min_duration:.1f}s, variance={variance:.6f}")
        return False

    def _apply_state_stability(self, candidate_state: SimplifiedState, timestamp: float) -> SimplifiedState:
        """
        Apply state stability logic to prevent rapid oscillation between states.
        """
        # If candidate state matches current state, stay in current state
        if candidate_state == self.current_state:
            return self.current_state
        
        # For high-priority states (IMPACT, SHAKE, FREE_FALL), allow immediate changes
        if candidate_state in [SimplifiedState.IMPACT, SimplifiedState.SHAKE, SimplifiedState.FREE_FALL]:
            self._update_state_tracking(candidate_state, timestamp)
            return candidate_state
        
        # Special handling for STATIONARY ↔ HELD_STILL oscillation prevention
        # Require longer duration for these specific transitions
        time_since_last_change = timestamp - self.state_change_time
        required_duration = self.min_state_duration
        
        # If transitioning between STATIONARY and HELD_STILL, require slightly longer duration
        if ((self.current_state == SimplifiedState.STATIONARY and candidate_state == SimplifiedState.HELD_STILL) or
            (self.current_state == SimplifiedState.HELD_STILL and candidate_state == SimplifiedState.STATIONARY)):
            required_duration = self.min_state_duration * 1.5  # 1.5 seconds for these transitions (was 2.0)
        
        if time_since_last_change >= required_duration:
            self._update_state_tracking(candidate_state, timestamp)
            return candidate_state
        
        # Not enough time has passed, stay in current state
        return self.current_state

    def _update_state_tracking(self, new_state: SimplifiedState, timestamp: float):
        """Update state tracking variables when state changes."""
        if new_state != self.current_state:
            self.state_change_time = timestamp
            if new_state != SimplifiedState.UNKNOWN:  # Only log meaningful state changes
                self.logger.info(f"State change: {self.current_state.name} → {new_state.name}")
        self.current_state = new_state

    def _check_shake(self) -> bool:
        """
        Check if a shake state is detected using enhanced 3D vector analysis.
        Analyzes acceleration direction changes and oscillation patterns to detect true shaking motion.

        Returns:
            bool: True if shake state detected
        """
        history_size = self.shake_history_size
        if len(self.motion_history) < history_size:
            return False

        # --- Get recent data ---
        start_index = len(self.motion_history) - history_size
        recent_history = [self.motion_history[i] for i in range(start_index, len(self.motion_history))]
        accelerations = [entry.get("linear_acceleration", None) for entry in recent_history]

        # --- Filter invalid entries ---
        valid_accelerations = [accel for accel in accelerations
                              if isinstance(accel, tuple) and len(accel) == 3]

        if len(valid_accelerations) < 8:  # Need more points for direction analysis
            return False

        # === Magnitude Check (peak-based) ===
        accel_magnitudes = []
        for accel in valid_accelerations:
            try:
                mag_sq = accel[0]**2 + accel[1]**2 + accel[2]**2
                if mag_sq >= 0:
                    accel_magnitudes.append(sqrt(mag_sq))
            except (TypeError, IndexError):
                continue

        if len(accel_magnitudes) < 8:
            return False

        peak_accel_magnitude = max(accel_magnitudes)
        avg_accel_magnitude = statistics.mean(accel_magnitudes)

        # Need at least one strong spike
        if peak_accel_magnitude < self.peak_magnitude_for_shake:
            return False

        # Also reject windows that are nearly still overall
        if avg_accel_magnitude < self.min_magnitude_for_shake:
            return False

        # === Enhanced Direction Change Analysis ===
        direction_changes = self._count_direction_changes(valid_accelerations)
        
        # Require multiple direction changes for shake detection
        if direction_changes < self.min_accel_reversals_for_shake:
            return False

        # === Additional Oscillation Pattern Check ===
        # Check for rapid oscillations in acceleration magnitude
        magnitude_oscillations = self._count_magnitude_oscillations(accel_magnitudes)
        
        # Require both direction changes AND magnitude oscillations
        min_oscillations = max(2, self.min_accel_reversals_for_shake // 2)
        
        if magnitude_oscillations < min_oscillations:
            return False

        # === Frequency Analysis ===
        # Check that the oscillations are in a reasonable frequency range for human shaking
        frequency_valid = self._validate_shake_frequency(valid_accelerations)
        
        if not frequency_valid:
            return False

        self.logger.info(f"SHAKE DETECTED! peak={peak_accel_magnitude:.2f}, avg={avg_accel_magnitude:.2f}, dir_changes={direction_changes}, mag_osc={magnitude_oscillations}, freq_valid={frequency_valid}")
        return True

    def _count_direction_changes(self, accel_vectors: List[Tuple[float, float, float]]) -> int:
        """
        Count significant changes in acceleration direction (3D vector analysis).
        
        This analyzes the actual 3D acceleration vectors to detect when the device
        changes direction rapidly, which is characteristic of shaking motion.
        
        Args:
            accel_vectors: List of 3D acceleration vectors
            
        Returns:
            int: Number of significant direction changes detected
        """
        if len(accel_vectors) < 3:
            return 0
        
        direction_changes = 0
        min_magnitude_for_direction = 2.0  # m/s² - minimum magnitude to consider direction meaningful
        min_angle_change = 60.0  # degrees - minimum angle change to count as direction change
        
        # Convert angle threshold to cosine for dot product comparison
        import math
        cos_threshold = math.cos(math.radians(min_angle_change))
        
        prev_vector = None
        valid_vectors_count = 0
        
        for i, current_vector in enumerate(accel_vectors):
            # Calculate magnitude
            magnitude = sqrt(sum(x*x for x in current_vector))
            
            # Skip vectors that are too small to have meaningful direction
            if magnitude < min_magnitude_for_direction:
                continue
            
            valid_vectors_count += 1
            
            # Normalize the vector
            normalized = tuple(x / magnitude for x in current_vector)
            
            if prev_vector is not None:
                # Calculate dot product to find angle between vectors
                dot_product = sum(a * b for a, b in zip(prev_vector, normalized))
                
                # Clamp dot product to valid range for numerical stability
                dot_product = max(-1.0, min(1.0, dot_product))
                
                # If dot product is less than threshold, we have a significant direction change
                if dot_product < cos_threshold:
                    direction_changes += 1
            
            prev_vector = normalized
        
        return direction_changes

    def _count_magnitude_oscillations(self, accel_magnitudes: List[float]) -> int:
        """
        Count oscillations in acceleration magnitude using peak detection.
        
        This detects rapid increases and decreases in acceleration magnitude,
        which complements the direction change analysis for shake detection.
        
        Args:
            accel_magnitudes: List of acceleration magnitudes over time
            
        Returns:
            int: Number of magnitude oscillations detected
        """
        if len(accel_magnitudes) < 5:
            return 0
        
        # Minimum change required to count as a significant oscillation
        min_oscillation_magnitude = 1.5  # m/s² - increased from 1.0 for more selectivity
        
        oscillations = 0
        trend = None  # 'up', 'down', or None
        last_extreme = accel_magnitudes[0]
        consecutive_same_trend = 0  # Track how long we've been in the same trend
        
        for i in range(1, len(accel_magnitudes)):
            current = accel_magnitudes[i]
            
            # Determine current trend with hysteresis
            if current > last_extreme + min_oscillation_magnitude:
                # Significant increase
                if trend == 'down' and consecutive_same_trend >= 2:  # Require sustained trend
                    oscillations += 1
                    consecutive_same_trend = 0
                elif trend != 'up':
                    consecutive_same_trend = 0
                
                trend = 'up'
                last_extreme = current
                consecutive_same_trend += 1
                
            elif current < last_extreme - min_oscillation_magnitude:
                # Significant decrease
                if trend == 'up' and consecutive_same_trend >= 2:  # Require sustained trend
                    oscillations += 1
                    consecutive_same_trend = 0
                elif trend != 'down':
                    consecutive_same_trend = 0
                
                trend = 'down'
                last_extreme = current
                consecutive_same_trend += 1
            else:
                # No significant change, continue current trend
                consecutive_same_trend += 1
        
        return oscillations

    def _validate_shake_frequency(self, accel_vectors: List[Tuple[float, float, float]]) -> bool:
        """
        Validate that the detected motion has characteristics consistent with intentional shaking.
        
        Human shaking typically occurs at 3-8 Hz. This method checks that the detected
        oscillations are in a reasonable frequency range and have sufficient regularity.
        
        Args:
            accel_vectors: List of 3D acceleration vectors
            
        Returns:
            bool: True if the frequency characteristics are consistent with shaking
        """
        if len(accel_vectors) < 10:
            return False
        
        # Calculate time span (corrected sampling rate: ~50Hz based on 20ms intervals)
        sampling_rate = 50.0  # Hz - actual sensor sampling rate (20ms intervals)
        time_span = len(accel_vectors) / sampling_rate  # seconds
        
        # Count zero crossings in the dominant acceleration component
        # Find the component with the highest variance (most active during shaking)
        x_values = [v[0] for v in accel_vectors]
        y_values = [v[1] for v in accel_vectors]
        z_values = [v[2] for v in accel_vectors]
        
        try:
            x_var = statistics.variance(x_values) if len(x_values) > 1 else 0
            y_var = statistics.variance(y_values) if len(y_values) > 1 else 0
            z_var = statistics.variance(z_values) if len(z_values) > 1 else 0
        except statistics.StatisticsError:
            return False
        
        # Use the component with highest variance
        if x_var >= y_var and x_var >= z_var:
            dominant_component = x_values
            dominant_axis = "X"
        elif y_var >= z_var:
            dominant_component = y_values
            dominant_axis = "Y"
        else:
            dominant_component = z_values
            dominant_axis = "Z"
        
        # Remove DC component (mean) to focus on oscillations
        mean_value = statistics.mean(dominant_component)
        centered_values = [v - mean_value for v in dominant_component]
        
        # Count zero crossings
        zero_crossings = 0
        for i in range(1, len(centered_values)):
            if (centered_values[i-1] >= 0) != (centered_values[i] >= 0):
                zero_crossings += 1
        
        # Estimate frequency from zero crossings
        # Each complete cycle has 2 zero crossings
        estimated_frequency = (zero_crossings / 2.0) / time_span if time_span > 0 else 0
        
        # Human shaking is typically 2-10 Hz, but be more lenient for 50Hz sampling
        # At 50Hz with 30 samples (0.6s window), we expect 1.2-6 complete cycles for 2-10Hz shaking
        min_shake_freq = 1.5  # Hz - more lenient lower bound
        max_shake_freq = 15.0  # Hz - more lenient upper bound for rapid shaking
        
        is_valid_frequency = min_shake_freq <= estimated_frequency <= max_shake_freq
        
        # Additional check: ensure there's sufficient variation in the dominant component
        # to distinguish from sensor noise
        try:
            std_dev = statistics.stdev(centered_values)
            min_variation = 1.0  # m/s² - minimum standard deviation for meaningful oscillation
            has_sufficient_variation = std_dev >= min_variation
        except statistics.StatisticsError:
            has_sufficient_variation = False
        
        result = is_valid_frequency and has_sufficient_variation
        
        return result

    def _detect_free_fall_multisensor(self, total_accel_mag: float, gyro: Tuple[float, float, float], 
                                    stability: str, timestamp: float) -> bool:
        """
        Detect free fall using reliable sensor fusion approach.
        
        Real free fall characteristics:
        1. Very low total acceleration (< 6.0 m/s²) - true weightlessness
        2. Significant rotational motion (2.0-15 rad/s) - objects tumble during free fall
        3. High linear acceleration (> 8.0 m/s²) - BNO085 gravity compensation failure signature
        4. Rapid acceleration drop (> 8.0 m/s² drop from recent peak) - distinguishes from circular motion
        5. Sustained for minimum duration (50ms) - rules out brief sensor noise
        
        Note: The BNO085's gravity compensation algorithm predictably fails during free fall,
        causing linear acceleration to read ~10+ m/s² instead of near zero. We exploit this
        predictable failure as a positive indicator of free fall conditions.
        
        This approach specifically excludes:
        - Gentle arc movements (moderate total accel + low rotation)
        - Stationary conditions (high total accel + low rotation + low linear accel)
        - Circular motion (gradual deceleration without rapid acceleration drop)
        - Normal motion (varies widely but doesn't match all four signatures)
        - Sensor noise (brief fluctuations ruled out by duration requirement)
        
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
        
        # Get linear acceleration from recent history for additional validation
        linear_accel_mag = 0.0
        if len(self.motion_history) > 0:
            recent_data = self.motion_history[-1]
            linear_accel = recent_data.get("linear_acceleration", (0, 0, 0))
            if isinstance(linear_accel, tuple) and len(linear_accel) == 3:
                try:
                    linear_accel_mag = sqrt(sum(x*x for x in linear_accel))
                except (TypeError, ValueError):
                    linear_accel_mag = 0.0
        
        # Rule out if device is extremely still (stationary detection)
        # Use stricter thresholds than the main stationary detection to avoid conflicts
        is_extremely_still = (total_accel_mag > 9.0 and total_accel_mag < 11.0 and  # Near 1g (9.8 m/s²) - sitting still
                             gyro_mag < 0.1)  # Almost no rotation
        
        if is_extremely_still:
            self._reset_free_fall_tracking()
            return False
        
        # STRICT CRITERIA: Must be met simultaneously
        is_very_low_accel = total_accel_mag < self.free_fall_accel_threshold  # < 6.0 m/s²
        has_significant_rotation = (gyro_mag > self.free_fall_min_rotation and 
                                   gyro_mag < self.free_fall_max_rotation)  # 2.0-15 rad/s
        
        # Linear acceleration signature: BNO085 gravity compensation fails during free fall
        # This causes linear accel to read ~10+ m/s² instead of near zero
        # We can use this predictable failure as a positive indicator!
        has_free_fall_linear_signature = linear_accel_mag > 8.0  # m/s² - gravity compensation failure signature
        
        # Acceleration rate check: Free fall has rapid acceleration drop, circular motion has gradual decrease
        has_rapid_accel_drop = self._check_rapid_acceleration_drop(total_accel_mag)
        
        # Free fall candidate requires all four criteria:
        # 1. Low total acceleration (weightlessness)
        # 2. Significant rotation (tumbling)  
        # 3. High linear acceleration (gravity compensation failure signature)
        # 4. Rapid acceleration drop (distinguishes from circular motion)
        is_free_fall_candidate = (is_very_low_accel and has_significant_rotation and 
                                 has_free_fall_linear_signature and has_rapid_accel_drop)
        
        # Debug logging for near-miss cases (when some but not all criteria are met)
        if (is_very_low_accel or has_significant_rotation or has_free_fall_linear_signature or has_rapid_accel_drop) and not is_free_fall_candidate:
            self.logger.debug(f"Free fall near-miss: total_accel={total_accel_mag:.2f}(<{self.free_fall_accel_threshold:.1f})={is_very_low_accel}, "
                            f"gyro={gyro_mag:.3f}({self.free_fall_min_rotation:.1f}-{self.free_fall_max_rotation:.1f})={has_significant_rotation}, "
                            f"linear_accel={linear_accel_mag:.2f}(>8.0)={has_free_fall_linear_signature}, "
                            f"rapid_drop={has_rapid_accel_drop}")
        
        if is_free_fall_candidate:
            # Start tracking if this is the first candidate sample
            if self.free_fall_candidate_start is None:
                self.free_fall_candidate_start = timestamp
                self.logger.debug(f"Free fall candidate started: total_accel={total_accel_mag:.2f}, linear_accel={linear_accel_mag:.2f}, gyro={gyro_mag:.3f}")
                return False  # Don't declare free fall immediately
            
            # Check if we've sustained the conditions long enough
            duration = timestamp - self.free_fall_candidate_start
            
            if duration >= self.free_fall_min_duration:
                # Confirm free fall immediately - duration requirement already ensures consistency
                if self.free_fall_start_time is None:
                    self.free_fall_start_time = self.free_fall_candidate_start
                    self.logger.debug(f"FREE_FALL confirmed after {duration:.3f}s (consistency check removed for faster detection)")
                
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
                self.logger.debug(f"Free fall candidate ended after {duration:.3f}s: total_accel={total_accel_mag:.2f}, gyro={gyro_mag:.3f}, linear_accel={linear_accel_mag:.2f}")
                self.logger.debug(f"  Criteria: low_accel={is_very_low_accel}, sig_rotation={has_significant_rotation}, linear_signature={has_free_fall_linear_signature}, rapid_drop={has_rapid_accel_drop}")
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

    def _check_rapid_acceleration_drop(self, total_accel_mag: float) -> bool:
        """
        Check if the acceleration dropped rapidly in recent history.
        
        Free fall: Rapid drop from high acceleration (throw) to low acceleration (weightless)
        Circular motion: Gradual decrease in acceleration as motion slows down
        
        Args:
            total_accel_mag: Current total acceleration magnitude (m/s²)
            
        Returns:
            bool: True if rapid acceleration drop is detected
        """
        if len(self.motion_history) < 8:  # Need enough history to detect rapid change
            return False
        
        # Look back through recent history to find peak acceleration
        recent_samples = 8  # Look back ~160ms at 50Hz (8 samples × 20ms)
        recent_history = list(self.motion_history)[-recent_samples:]
        
        # Extract acceleration magnitudes from recent history
        accel_magnitudes = []
        for sample in recent_history:
            accel_raw = sample.get("acceleration", None)
            if isinstance(accel_raw, tuple) and len(accel_raw) == 3:
                try:
                    accel_mag = sqrt(sum(x*x for x in accel_raw))
                    accel_magnitudes.append(accel_mag)
                except (TypeError, ValueError):
                    continue
        
        if len(accel_magnitudes) < 5:
            return False
        
        # Find the maximum acceleration in recent history
        max_recent_accel = max(accel_magnitudes)
        
        # Check for rapid drop: must have dropped significantly from recent peak
        min_drop_threshold = 8.0  # m/s² - minimum drop to consider "rapid"
        accel_drop = max_recent_accel - total_accel_mag
        
        # Also check that the peak was high enough (indicating a throw)
        min_peak_threshold = 12.0  # m/s² - minimum peak to indicate throwing motion
        
        has_significant_drop = accel_drop >= min_drop_threshold
        had_high_peak = max_recent_accel >= min_peak_threshold
        
        self.logger.debug(f"Rapid drop check: peak={max_recent_accel:.1f}, current={total_accel_mag:.1f}, "
                         f"drop={accel_drop:.1f}(>={min_drop_threshold}), peak_high={had_high_peak}")
        
        return has_significant_drop and had_high_peak