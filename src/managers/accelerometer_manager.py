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
        self.free_fall_min_rotation = 1.5       # rad/s - Reduced from 2.0 to catch gentler throws and less tumbling
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
        self.state_change_time = None             # When the last state change occurred (None = not initialized)
        self.min_state_duration = 2.0            # Minimum time to stay in a state (2000ms) - increased from 1000ms

        # --- Quaternion / Rotation Tracking ---
        # Cache the previous Game Rotation quaternion to compute rotational speed
        self._prev_game_quat: Optional[Tuple[float, float, float, float]] = None
        self._prev_quat_ts: float = 0.0

        # Enhanced thresholds with balanced hysteresis for stable state detection
        # Based on real-world testing showing oscillation between 0.05-0.47 m/s² when "holding steady"
        # AND observed "completely stationary" values up to 0.048 m/s² linear, 0.029 rad/s gyro
        # Need larger separation between STATIONARY and HELD_STILL to prevent oscillation
        
        # STATIONARY: Device completely still (on table, etc.) - REALISTIC THRESHOLDS
        # Based on actual hardware testing showing readings of 0.2-0.4 m/s² when stationary
        self.stationary_linear_accel_max = 0.50   # m/s² - Realistic for actual hardware (was 0.10)
        self.stationary_gyro_max = 0.08           # rad/s - Realistic for actual hardware (was 0.04)
        self.stationary_rot_speed_max = 0.08      # rad/s - Realistic for actual hardware (was 0.04)
        self.stationary_consistency_required = 4  # Reduced consistency requirement (was 5)
        self.stationary_max_variance = 0.050     # m/s² - Much more lenient variance for hardware (was 0.020)
        self.stationary_min_duration = 0.8       # seconds - Faster responsiveness (was 1.0)
        
        # HELD_STILL: Device held by hand - More permissive with large gap
        self.held_still_linear_accel_max = 1.5    # m/s² - Large gap above STATIONARY
        self.held_still_gyro_max = 0.50           # rad/s - More permissive for hand tremor
        self.held_still_rot_speed_max = 0.50      # rad/s - More permissive for hand tremor
        
        # Hysteresis: Reasonable hysteresis to prevent oscillation
        self.hysteresis_factor = 2.0              # Reasonable hysteresis (was 3.0)
        self.stationary_exit_hysteresis = 2.5     # Reasonable hysteresis for exiting STATIONARY (was 4.0)
        
        # Dead zone: Ignore tiny changes that are likely sensor noise or table vibrations
        self.dead_zone_threshold = 0.30          # m/s² - Larger dead zone for realistic hardware (was 0.20)
        self.dead_zone_duration = 0.5            # seconds - Longer duration to ignore small changes
        self.last_significant_change_time = None # Track when last significant change occurred
        
        # Stability tracking: Prevent rapid oscillations with reasonable timing
        self.oscillation_prevention_window = 3.0  # seconds - Prevent oscillations within this window
        self.last_transition_time = None         # Track last transition to prevent rapid oscillations
        
        # Stationary state tracking for consistency checking
        self.stationary_candidate_start = None
        self.stationary_candidate_readings = deque(maxlen=15)  # Store more readings for better variance analysis (was 10)

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

        # Calculate energy level for movement-based activities
        linear_accel = data.get("linear_acceleration", (0, 0, 0))
        gyro = data.get("gyro", (0, 0, 0))
        if isinstance(linear_accel, tuple) and len(linear_accel) == 3 and isinstance(gyro, tuple) and len(gyro) == 3:
            energy = self.calculate_energy(linear_accel, gyro, rot_speed=rot_speed)
            data["energy"] = energy
        else:
            data["energy"] = 0.0

        # Skip heading calculation for performance (can be added back if needed)

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
        
        # Apply strong hysteresis based on current state, with special handling for STATIONARY
        if current_state == SimplifiedState.STATIONARY:
            # Currently STATIONARY - use very strong hysteresis to prevent tiny jolts from causing transitions
            stationary_linear_threshold = stationary_linear_base * self.stationary_exit_hysteresis  # 8x stronger
            stationary_gyro_threshold = stationary_gyro_base * self.stationary_exit_hysteresis
            stationary_rot_threshold = stationary_rot_base * self.stationary_exit_hysteresis
            
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
        
        # Enhanced dead zone logic: Ignore tiny changes when in stable states
        current_time = time.time()
        if current_state in [SimplifiedState.STATIONARY, SimplifiedState.HELD_STILL]:
            # Get recent readings for better dead zone analysis
            if len(self.stationary_candidate_readings) >= 3:
                recent_readings = list(self.stationary_candidate_readings)[-3:]
                baseline = statistics.median(recent_readings)
                
                # Check if this is a tiny change that should be ignored
                change_magnitude = abs(linear_accel_mag - baseline)
                
                if change_magnitude < self.dead_zone_threshold:
                    # This is within the dead zone - ignore it and stay in current state
                    self.logger.debug(f"Dead zone: ignoring change {change_magnitude:.3f} < {self.dead_zone_threshold:.3f}")
                    return current_state
                else:
                    # This is a significant change - update tracking
                    self.last_significant_change_time = current_time
                    self.logger.debug(f"Significant change detected: {change_magnitude:.3f} >= {self.dead_zone_threshold:.3f}")
            elif self.stationary_candidate_readings:
                # Fallback for fewer readings
                last_reading = self.stationary_candidate_readings[-1]
                change_magnitude = abs(linear_accel_mag - last_reading)
                
                if change_magnitude < self.dead_zone_threshold:
                    self.logger.debug(f"Dead zone (fallback): ignoring change {change_magnitude:.3f} < {self.dead_zone_threshold:.3f}")
                    return current_state
        
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
        
        # Determine candidate state based on criteria
        if is_truly_stationary:
            candidate_state = SimplifiedState.STATIONARY
        elif is_held_still:
            candidate_state = SimplifiedState.HELD_STILL
        else:
            candidate_state = SimplifiedState.MOVING
        
        # Enhanced debug logging for troubleshooting oscillations
        if candidate_state != current_state:
            self.logger.debug(f"State transition candidate: {current_state.name} → {candidate_state.name}")
            self.logger.debug(f"  Linear: {linear_accel_mag:.3f} (STAT<{stationary_linear_threshold:.3f}, HELD<{held_still_linear_threshold:.3f})")
            self.logger.debug(f"  Gyro: {gyro_mag:.3f} (STAT<{stationary_gyro_threshold:.3f}, HELD<{held_still_gyro_threshold:.3f})")
            self.logger.debug(f"  RotSpeed: {rot_speed:.3f} (STAT<{stationary_rot_threshold:.3f}, HELD<{held_still_rot_threshold:.3f})")
            self.logger.debug(f"  STATIONARY checks: basic={meets_basic_stationary}, truly={is_truly_stationary}")
            
            # Show hysteresis factors being applied
            if current_state == SimplifiedState.STATIONARY:
                self.logger.debug(f"  STATIONARY exit hysteresis: {self.stationary_exit_hysteresis}x (thresholds multiplied)")
            elif current_state == SimplifiedState.HELD_STILL:
                self.logger.debug(f"  HELD_STILL exit hysteresis: {self.hysteresis_factor}x (thresholds multiplied)")
            elif current_state == SimplifiedState.UNKNOWN:
                self.logger.debug(f"  UNKNOWN state - using normal entry thresholds")
        
        return candidate_state
    
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
                
                # Enhanced variance checking with outlier filtering
                # Remove outliers before calculating variance to handle brief spikes
                filtered_readings = self._filter_outliers(recent_readings)
                
                if len(filtered_readings) >= 3:
                    try:
                        filtered_variance = statistics.variance(filtered_readings)
                    except statistics.StatisticsError:
                        filtered_variance = variance  # Fall back to original if filtering fails
                else:
                    filtered_variance = variance
                
                # Be more lenient with variance - only reject if variance is extremely high
                if filtered_variance > adjusted_variance_threshold:
                    # Don't immediately restart - be more patient with sensor noise
                    # Only restart if variance is extremely high (15x threshold) or we've been trying for a long time
                    extreme_threshold = adjusted_variance_threshold * 15  # 15x more lenient (was 10x)
                    
                    if filtered_variance > extreme_threshold:
                        self.logger.debug(f"STATIONARY rejected: extreme filtered variance {filtered_variance:.6f} > {extreme_threshold:.6f}")
                        self.stationary_candidate_start = None
                        return False
                    elif duration_so_far > 8.0:  # After 8 seconds, be stricter (was 5.0) - more patient
                        self.logger.debug(f"STATIONARY rejected: filtered variance {filtered_variance:.6f} > {adjusted_variance_threshold:.6f} after {duration_so_far:.1f}s")
                        self.stationary_candidate_start = None
                        return False
                    else:
                        # Continue tracking despite high variance - sensor might stabilize
                        if should_log_variance:
                            self.logger.debug(f"STATIONARY variance high but continuing: filtered={filtered_variance:.6f}, raw={variance:.6f} > {adjusted_variance_threshold:.6f} (will retry)")
                else:
                    if should_log_variance:
                        self.logger.debug(f"STATIONARY variance good: filtered={filtered_variance:.6f}, raw={variance:.6f} <= {adjusted_variance_threshold:.6f}")
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

    def _filter_outliers(self, readings: List[float]) -> List[float]:
        """
        Filter outliers from a list of readings using a simple statistical method.
        
        This helps handle brief spikes in sensor data that shouldn't disqualify
        an otherwise stationary device.
        
        Args:
            readings: List of sensor readings
            
        Returns:
            List[float]: Filtered readings with outliers removed
        """
        if len(readings) < 3:
            return readings
        
        try:
            # Calculate median and median absolute deviation (MAD)
            median = statistics.median(readings)
            deviations = [abs(x - median) for x in readings]
            mad = statistics.median(deviations)
            
            # If MAD is very small, use standard deviation instead
            if mad < 0.001:
                try:
                    std_dev = statistics.stdev(readings)
                    threshold = median + 2.5 * std_dev  # 2.5 sigma rule
                    return [x for x in readings if abs(x - median) <= 2.5 * std_dev]
                except statistics.StatisticsError:
                    return readings
            
            # Use MAD-based outlier detection (more robust than standard deviation)
            # Modified Z-score: 0.6745 * (x - median) / MAD
            # Threshold of 3.5 is commonly used for outlier detection
            threshold = 3.5
            filtered = []
            for reading in readings:
                modified_z_score = 0.6745 * abs(reading - median) / mad
                if modified_z_score <= threshold:
                    filtered.append(reading)
            
            # Ensure we don't filter out too many readings
            if len(filtered) >= len(readings) * 0.6:  # Keep at least 60% of readings
                return filtered
            else:
                return readings  # Return original if too many would be filtered
                
        except (statistics.StatisticsError, ZeroDivisionError):
            return readings

    def _apply_state_stability(self, candidate_state: SimplifiedState, timestamp: float) -> SimplifiedState:
        """
        Apply state stability logic to prevent rapid oscillation between states.
        """
        # Initialize state change time on first call
        if self.state_change_time is None:
            self.state_change_time = timestamp
            self.logger.debug(f"Initializing state tracking at timestamp {timestamp}")
        
        # If candidate state matches current state, stay in current state
        if candidate_state == self.current_state:
            return self.current_state
        
        # For high-priority states (IMPACT, SHAKE, FREE_FALL), allow immediate changes
        if candidate_state in [SimplifiedState.IMPACT, SimplifiedState.SHAKE, SimplifiedState.FREE_FALL]:
            self._update_state_tracking(candidate_state, timestamp)
            return candidate_state
        
        # Calculate time since last state change
        time_since_last_change = timestamp - self.state_change_time
        required_duration = self.min_state_duration
        
        # Check for oscillation prevention first
        if self._is_oscillation_attempt(candidate_state, timestamp):
            self.logger.debug(f"Preventing oscillation: {self.current_state.name}↔{candidate_state.name} within {self.oscillation_prevention_window:.1f}s window")
            return self.current_state
        
        # Special handling for different state transitions with reasonable timing
        if self.current_state == SimplifiedState.UNKNOWN:
            # Allow quick initial transition from UNKNOWN to any state
            required_duration = 0.1  # 100ms for initial state detection
            self.logger.debug(f"UNKNOWN→{candidate_state.name} transition requires {required_duration:.1f}s, elapsed: {time_since_last_change:.1f}s")
        elif self.current_state == SimplifiedState.STATIONARY and candidate_state == SimplifiedState.HELD_STILL:
            # Moderate delay to exit STATIONARY due to tiny jolts, but not excessive
            required_duration = 1.0  # 1.0 second max as requested
            self.logger.debug(f"STATIONARY→HELD_STILL transition requires {required_duration:.1f}s, elapsed: {time_since_last_change:.1f}s")
        elif self.current_state == SimplifiedState.HELD_STILL and candidate_state == SimplifiedState.STATIONARY:
            # Allow reasonable transition back to STATIONARY
            required_duration = 0.8  # Slightly easier to return to STATIONARY
            self.logger.debug(f"HELD_STILL→STATIONARY transition requires {required_duration:.1f}s, elapsed: {time_since_last_change:.1f}s")
        elif ((self.current_state == SimplifiedState.STATIONARY and candidate_state == SimplifiedState.MOVING) or
              (self.current_state == SimplifiedState.HELD_STILL and candidate_state == SimplifiedState.MOVING)):
            # Transitions to MOVING should be easier to allow responsiveness
            required_duration = 0.5  # 0.5 second to transition to MOVING
        
        if time_since_last_change >= required_duration:
            self._update_state_tracking(candidate_state, timestamp)
            return candidate_state
        
        # Not enough time has passed, stay in current state
        return self.current_state

    def _update_state_tracking(self, new_state: SimplifiedState, timestamp: float):
        """Update state tracking variables when state changes."""
        if new_state != self.current_state:
            self.state_change_time = timestamp
            self.last_transition_time = timestamp  # Track for oscillation prevention
            if new_state != SimplifiedState.UNKNOWN:  # Only log meaningful state changes
                self.logger.info(f"State change: {self.current_state.name} → {new_state.name}")
        self.current_state = new_state

    def _is_oscillation_attempt(self, candidate_state: SimplifiedState, timestamp: float) -> bool:
        """
        Check if this transition would be an oscillation (rapid back-and-forth between states).
        
        Prevents rapid oscillations between STATIONARY and HELD_STILL by tracking recent transitions.
        
        Args:
            candidate_state: The state we want to transition to
            timestamp: Current timestamp
            
        Returns:
            bool: True if this would be an oscillation that should be prevented
        """
        if self.last_transition_time is None:
            return False
        
        time_since_last_transition = timestamp - self.last_transition_time
        
        # Only prevent oscillations between stable states
        stable_states = {SimplifiedState.STATIONARY, SimplifiedState.HELD_STILL}
        
        if (self.current_state in stable_states and 
            candidate_state in stable_states and 
            self.current_state != candidate_state and
            time_since_last_transition < self.oscillation_prevention_window):
            return True
        
        return False

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
        return self._validate_shake_frequency(valid_accelerations)

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
        # if (is_very_low_accel or has_significant_rotation or has_free_fall_linear_signature or has_rapid_accel_drop) and not is_free_fall_candidate:
        #     self.logger.debug(f"Free fall near-miss: total_accel={total_accel_mag:.2f}(<{self.free_fall_accel_threshold:.1f})={is_very_low_accel}, "
        #                     f"gyro={gyro_mag:.3f}({self.free_fall_min_rotation:.1f}-{self.free_fall_max_rotation:.1f})={has_significant_rotation}, "
        #                     f"linear_accel={linear_accel_mag:.2f}(>8.0)={has_free_fall_linear_signature}, "
        #                     f"rapid_drop={has_rapid_accel_drop}")
        
        if is_free_fall_candidate:
            # Start tracking if this is the first candidate sample
            if self.free_fall_candidate_start is None:
                self.free_fall_candidate_start = timestamp
                # self.logger.debug(f"Free fall candidate started: total_accel={total_accel_mag:.2f}, linear_accel={linear_accel_mag:.2f}, gyro={gyro_mag:.3f}")
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
        
        Enhanced for free fall: Once a rapid drop is detected, it remains valid for a grace period
        to support sustained free fall detection even after the initial drop.
        
        Args:
            total_accel_mag: Current total acceleration magnitude (m/s²)
            
        Returns:
            bool: True if rapid acceleration drop is detected or recently detected
        """
        if len(self.motion_history) < 8:  # Need enough history to detect rapid change
            return False
        
        # Look back through longer history to find peak acceleration for free fall
        # Use longer window for free fall detection (20 samples = ~400ms at 50Hz)
        extended_samples = min(20, len(self.motion_history))  # Look back up to 400ms
        extended_history = list(self.motion_history)[-extended_samples:]
        
        # Extract acceleration magnitudes from extended history
        accel_magnitudes = []
        timestamps = []
        for sample in extended_history:
            accel_raw = sample.get("acceleration", None)
            timestamp = sample.get("timestamp", 0)
            if isinstance(accel_raw, tuple) and len(accel_raw) == 3:
                try:
                    accel_mag = sqrt(sum(x*x for x in accel_raw))
                    accel_magnitudes.append(accel_mag)
                    timestamps.append(timestamp)
                except (TypeError, ValueError):
                    continue
        
        if len(accel_magnitudes) < 5:
            return False
        
        # Find the maximum acceleration in extended history
        max_extended_accel = max(accel_magnitudes)
        max_index = accel_magnitudes.index(max_extended_accel)
        
        # Check for rapid drop: must have dropped significantly from peak
        min_drop_threshold = 8.0  # m/s² - minimum drop to consider "rapid"
        accel_drop = max_extended_accel - total_accel_mag
        
        # Also check that the peak was high enough (indicating a throw)
        min_peak_threshold = 12.0  # m/s² - minimum peak to indicate throwing motion
        
        has_significant_drop = accel_drop >= min_drop_threshold
        had_high_peak = max_extended_accel >= min_peak_threshold
        
        # Enhanced logic: Check if we're within a reasonable time window after the peak
        # This allows sustained free fall detection even after the initial rapid drop
        current_time = time.time()
        if timestamps and max_index < len(timestamps):
            peak_time = timestamps[max_index]
            time_since_peak = current_time - peak_time
            
            # Allow rapid drop to remain "active" for up to 2 seconds after the peak
            # This supports sustained free fall detection
            within_grace_period = time_since_peak <= 2.0
            
            # Also check that we're currently in a low-acceleration state
            # (to avoid false positives during normal motion)
            currently_low_accel = total_accel_mag < 6.0  # Same as free fall threshold
            
            # Rapid drop is valid if:
            # 1. Traditional criteria are met, OR
            # 2. We had a significant drop recently and are still in low-accel state
            rapid_drop_valid = (has_significant_drop and had_high_peak) or \
                              (within_grace_period and had_high_peak and currently_low_accel and 
                               max_extended_accel - min(accel_magnitudes[-5:]) >= min_drop_threshold)
        else:
            # Fallback to traditional logic if timestamp data is unavailable
            rapid_drop_valid = has_significant_drop and had_high_peak
        
        # self.logger.debug(f"Rapid drop check: peak={max_extended_accel:.1f}, current={total_accel_mag:.1f}, "
        #                  f"drop={accel_drop:.1f}(>={min_drop_threshold}), peak_high={had_high_peak}")
        
        return rapid_drop_valid