"""
Core sensor functionality for reading and processing touch sensor data.
"""

import time
import logging
import config
import asyncio
import platform
import random
from typing import Callable, Optional, List, Awaitable, Union

# Only import hardware-specific libraries on Raspberry Pi
if config.PLATFORM == "raspberry-pi":
    import board
    import busio
    import adafruit_ads1x15.ads1115 as ADS
    from adafruit_ads1x15.analog_in import AnalogIn
    from adafruit_ads1x15.ads1x15 import Mode

# Type aliases for callbacks
TouchCallback = Union[Callable[[bool], Awaitable[None]], Callable[[bool], None]]
PositionCallback = Union[Callable[[float], Awaitable[None]], Callable[[float], None]]
StrokeCallback = Union[Callable[[str], Awaitable[None]], Callable[[str], None]]
StrokeIntensityCallback = Union[Callable[[float], Awaitable[None]], Callable[[float], None]]

class TouchManager:
    """Main class for interacting with the touch sensor"""
    def __init__(self):
        self.touch_state = TouchState()
        self.stroke_detector = StrokeDetector()
        self.running = False
        self.position_callbacks: List[PositionCallback] = []
        self.stroke_callbacks: List[StrokeCallback] = []
        self.touch_callbacks: List[TouchCallback] = []
        self.stroke_intensity_callbacks: List[StrokeIntensityCallback] = []
        
        # Stroke intensity level tracking
        self.stroke_intensity_level = 0.0  # 0.0 to 1.0
        self.last_stroke_intensity_update = time.time()
        self._pending_intensity_update = None  # Track pending update task

        if config.PLATFORM == "raspberry-pi":
            self.ads, self.chan = self._setup_adc()
        else:
            # Mock ADC for non-Raspberry Pi platforms
            self.ads = None
            self.chan = MockAnalogIn()
            logging.info("Initialized mock touch sensor for non-Raspberry Pi platform")
        
    def _setup_adc(self):
        """Initialize the ADC connection
        
        Uses hardware I2C port (1, 3, 2) and default I2C address 0x48 for ADS1115
        """
        try:
            # Create the I2C bus
            i2c = busio.I2C(board.SCL, board.SDA)
            
            # Create the ADC object using the I2C bus
            ads = ADS.ADS1115(i2c)  # Change to ADS1015 if using that model

            # Set the ADC to continuous conversion mode
            # TODO: Uncomment this to test when everything else works
            # ads.mode = Mode.CONTINUOUS
            
            # Create single-ended input on channel 0
            chan = AnalogIn(ads, ADS.P0)
            
            ads.gain = 1
            return ads, chan
        except Exception as e:
            logging.error(f"Failed to initialize ADC: {str(e)}")
            raise

    def on_position(self, callback: Callable[[float], None]):
        """Register callback for position updates
        
        Args:
            callback: Function taking normalized position (0-1) as argument
        """
        self.position_callbacks.append(callback)
        
    def on_stroke(self, callback: Callable[[str], None]):
        """Register callback for stroke detection
        
        Args:
            callback: Function taking stroke direction ("left" or "right") as argument
        """
        self.stroke_callbacks.append(callback)
        
    def on_touch(self, callback: Callable[[bool], None]):
        """Register callback for touch state changes
        
        Args:
            callback: Function taking touch state (True/False) as argument
        """
        self.touch_callbacks.append(callback)
        
    def on_stroke_intensity(self, callback: Callable[[float], None]):
        """Register callback for stroke intensity level updates
        
        Args:
            callback: Function taking stroke intensity level (0-1) as argument
        """
        self.stroke_intensity_callbacks.append(callback)
        
    async def _execute_callbacks(self, callbacks: List[Union[Callable, Awaitable]], *args):
        """Helper method to execute callbacks that may be async or sync"""
        for callback in callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(*args)
                else:
                    callback(*args)
            except Exception as e:
                logging.error(f"Error in callback {callback.__name__}: {str(e)}")
    
    def _update_stroke_intensity_level(self) -> bool:
        """Update stroke intensity level based on time decay
        
        The stroke intensity naturally decays over time when no new strokes are detected.
        We want to track:
        1. Any non-zero decay
        2. When intensity reaches exactly 0
        
        Returns:
            bool: True if intensity was updated and callbacks should be triggered
        """
        now = time.time()
        elapsed = now - self.last_stroke_intensity_update
        
        # Apply time-based decay
        decay = config.STROKE_INTENSITY_DECAY_RATE * elapsed
        new_intensity = max(0.0, self.stroke_intensity_level - decay)
        
        # Update if:
        # 1. There is any decay
        # 2. We've just reached zero
        if new_intensity < self.stroke_intensity_level:
            self.stroke_intensity_level = new_intensity
            self.last_stroke_intensity_update = now
            return True
        
        # Just update the timestamp if no change
        self.last_stroke_intensity_update = now
        return False

    async def _notify_intensity_update(self):
        """Helper method to notify intensity callbacks"""
        if self.stroke_intensity_callbacks:
            await self._execute_callbacks(self.stroke_intensity_callbacks, self.stroke_intensity_level)

    def _calculate_stroke_intensity_increase(self, distance: float, speed: float) -> float:
        """Calculate stroke intensity increase based on stroke metrics
        
        Args:
            distance: Total distance of stroke (0-1 range)
            speed: Speed of stroke (positions per second)
            
        Returns:
            float: Amount to increase stroke intensity (0-1 range)
        """
        # Ensure minimum speed to prevent very slow strokes from causing large increases
        speed = max(config.STROKE_INTENSITY_MIN_SPEED, speed)
        
        # Increase is proportional to distance and inversely proportional to speed
        # Add a small constant (0.1) to speed to prevent division by very small numbers
        increase = (distance * config.STROKE_INTENSITY_DISTANCE_FACTOR) / ((speed * config.STROKE_INTENSITY_SPEED_FACTOR) + 0.1)
        
        # Clamp the increase to configured maximum
        return min(config.STROKE_INTENSITY_MAX_INCREASE, max(0.0, increase))
    
    async def start(self, sample_rate_hz: float = config.SAMPLE_RATE_HZ):
        """Start the sensor reading loop
        
        Args:
            sample_rate_hz: Sampling rate in Hz (defaults to config.SAMPLE_RATE_HZ)
        """
        if self.running:
            return
            
        self.running = True
        interval = 1.0 / sample_rate_hz
        
        # Create a separate task for processing callbacks
        async def process_callbacks():
            while self.running:
                try:
                    value = self.chan.value
                    was_touching = self.touch_state.is_touching
                    is_touching = self.touch_state.update(value)
                    
                    # Update stroke intensity level and notify if changed
                    if self._update_stroke_intensity_level():
                        await self._notify_intensity_update()
                    
                    # Notify touch state changes
                    if is_touching != was_touching:
                        await self._execute_callbacks(self.touch_callbacks, is_touching)
                    
                    # Process point and check for strokes
                    stroke_detected, direction = self.stroke_detector.add_point(value, is_touching)
                    
                    if is_touching:
                        # Calculate normalized position
                        position = ((value - config.LEFT_MIN) / (config.RIGHT_MAX - config.LEFT_MIN))
                        position = max(0, min(position, 1.0))
                        
                        # Notify position updates
                        await self._execute_callbacks(self.position_callbacks, position)
                    
                    if stroke_detected:
                        # Get stroke metrics from detector
                        times = [t for t, p in self.stroke_detector.touch_history]
                        positions = [p for t, p in self.stroke_detector.touch_history]
                        total_distance = abs(positions[-1] - positions[0])
                        total_time = times[-1] - times[0]
                        speed = total_distance / total_time if total_time > 0 else 0
                        
                        # Calculate and apply stroke intensity increase based on stroke metrics
                        increase = self._calculate_stroke_intensity_increase(total_distance, speed)
                        self.stroke_intensity_level = min(1.0, self.stroke_intensity_level + increase)
                        self.last_stroke_intensity_update = time.time()
                        
                        # Log the stroke intensity calculation
                        logging.info(f"Stroke intensity increase: {increase:.3f} (distance: {total_distance:.3f}, speed: {speed:.3f})")
                        
                        # Notify stroke detection and intensity update
                        await self._execute_callbacks(self.stroke_callbacks, direction)
                        await self._notify_intensity_update()
                    
                except Exception as e:
                    logging.error(f"Error reading sensor: {str(e)}")
                
                await asyncio.sleep(interval)
        
        try:
            # Start the callback processing task but don't await it
            self._processing_task = asyncio.create_task(process_callbacks())
            # Return immediately to not block the event loop
            return
        except Exception as e:
            logging.error(f"Failed to start touch processing: {str(e)}")
            self.running = False
            raise
    
    def stop(self):
        """Stop the sensor reading loop"""
        self.running = False
        # Cancel the processing task if it exists
        if hasattr(self, '_processing_task') and self._processing_task:
            self._processing_task.cancel()

class StrokeDetector:
    """Class to detect stroking motions on the touch sensor"""
    def __init__(self):
        self.touch_history = []  # List of (timestamp, position) tuples
        self.last_stroke_time = 0
        self.was_touching = False  # Track previous touch state
        self.pending_stroke = None  # Store detected stroke until next touch
        
    def add_point(self, value, is_touching):
        """Add a touch point to history and check for stroke on release
        
        Args:
            value (int): Raw sensor value
            is_touching (bool): Current touch state
            
        Returns:
            tuple: (bool: stroke detected, str: stroke direction if detected) or (False, None)
        """
        now = time.time()
        
        # Handle touch state transition
        if is_touching != self.was_touching:
            if self.was_touching and not is_touching:  # Finger lifted
                # Check for stroke only when finger is lifted
                if len(self.touch_history) >= config.MIN_STROKE_POINTS:
                    self.pending_stroke = self._check_stroke()
            else:  # New touch started
                self.touch_history = []  # Clear history only on new touch
                self.pending_stroke = None
            
            self.was_touching = is_touching
            
            # Return pending stroke detection if finger was just lifted
            if self.pending_stroke:
                result = self.pending_stroke
                self.pending_stroke = None
                return result
            return False, None
            
        # Only add points while touching
        if not is_touching:
            return False, None
            
        # Convert value to normalized position (0 to 1)
        position = ((value - config.LEFT_MIN) / (config.RIGHT_MAX - config.LEFT_MIN))
        position = max(0, min(position, 1.0))  # Clamp to valid range
        
        # Only add non-zero positions to history
        if position > 0:
            self.touch_history.append((now, position))
            logging.debug(f"Added position: {position:.3f} from value: {value}")
        
        return False, None
    
    def _check_stroke(self):
        """Internal method to check if the completed touch was a stroke
        
        Returns:
            tuple: (bool: stroke detected, str: stroke direction if detected)
        """
        if not self.touch_history:  # Safety check
            return False, None
            
        # History is already chronological and filtered for non-zero positions
        times = [t for t, p in self.touch_history]
        positions = [p for t, p in self.touch_history]
        
        # Trim inconsistent readings at the end (lift-off artifacts)
        original_len = len(positions)
        if len(positions) >= 3:
            # Look for sudden direction changes or large jumps at the end
            for i in range(len(positions)-2, max(0, len(positions)-10), -1):
                diff1 = positions[i] - positions[i-1]  # Direction of movement
                diff2 = positions[i+1] - positions[i]  # Direction of next movement
                
                # If direction suddenly changes significantly or there's a large jump
                if (abs(diff2) > 0.4 or  # Large position jump (40% of sensor range)
                    (abs(diff1) > 0.05 and abs(diff2) > 0.05 and  # Both movements are significant (5%)
                     diff1 * diff2 < 0)):  # Direction changed
                    # Trim the history to remove lift-off artifacts
                    times = times[:i+1]
                    positions = positions[:i+1]
                    logging.info(f"Trimmed {original_len - len(positions)} points from end of stroke")
                    break
        
        if len(positions) < config.MIN_STROKE_POINTS:
            logging.info(f"Not enough points for stroke: {len(positions)} < {config.MIN_STROKE_POINTS}")
            return False, None
            
        # Calculate stroke metrics
        total_distance = abs(positions[-1] - positions[0])
        total_time = times[-1] - times[0]
        
        if total_time == 0:
            logging.info("Zero time duration for stroke")
            return False, None
            
        speed = total_distance / total_time
        direction = self.calculate_stroke_direction(positions)
        
        if not direction:
            logging.info("Could not determine stroke direction")
            return False, None
            
        # Check if motion is mostly monotonic in the determined direction
        is_monotonic = self.is_mostly_monotonic(positions, times, direction)
        
        # Log all stroke metrics at once
        logging.info(f"Stroke metrics - Distance: {total_distance:.3f}, Speed: {speed:.3f}, Direction: {direction}, Monotonic: {is_monotonic}")
        logging.info(f"Positions from {positions[0]:.3f} to {positions[-1]:.3f} over {total_time:.3f}s")
        
        # Check if stroke criteria are met
        now = time.time()
        if total_distance < config.MIN_STROKE_DISTANCE:
            logging.info(f"Distance too small: {total_distance:.3f} < {config.MIN_STROKE_DISTANCE}")
        elif not is_monotonic:
            logging.info("Movement not monotonic enough")
        elif speed < config.MIN_STROKE_SPEED:
            logging.info(f"Speed too low: {speed:.3f} < {config.MIN_STROKE_SPEED}")
        elif now - self.last_stroke_time < config.STROKE_TIME_WINDOW:
            logging.info(f"Too soon after last stroke: {now - self.last_stroke_time:.3f}s < {config.STROKE_TIME_WINDOW}s")
        else:
            self.last_stroke_time = now
            return True, direction
            
        return False, None
    
    def calculate_stroke_direction(self, positions):
        """Calculate the dominant direction of movement using linear regression
        
        Args:
            positions: List of position values
            
        Returns:
            str: "right" or "left" based on dominant direction
        """
        if len(positions) < 2:
            return None
            
        # Use simple linear regression to find trend
        x = list(range(len(positions)))
        y = positions
        n = len(positions)
        
        # Calculate slope using least squares
        mean_x = sum(x) / n
        mean_y = sum(y) / n
        numerator = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n))
        denominator = sum((x[i] - mean_x) ** 2 for i in range(n))
        
        if denominator == 0:
            return None
            
        slope = numerator / denominator
        return "right" if slope > 0 else "left"
    
    def is_mostly_monotonic(self, positions, times, direction):
        """Check if movement is mostly monotonic with some tolerance for reversals
        
        Args:
            positions: List of position values
            times: List of timestamps
            direction: Expected direction ("right" or "left")
            
        Returns:
            bool: True if movement is mostly monotonic
        """
        if len(positions) < 2:
            return True
            
        expected_sign = 1 if direction == "right" else -1
        total_time = times[-1] - times[0]
        reversal_time = 0  # Total time spent in reversal
        
        for i in range(1, len(positions)):
            diff = positions[i] - positions[i-1]
            if abs(diff) > config.DIRECTION_REVERSAL_TOLERANCE:
                if (diff * expected_sign) < 0:
                    # Add the time spent in this reversal
                    reversal_time += times[i] - times[i-1]
        
        # Allow up to 25% of total time to be spent in reversals
        return reversal_time <= total_time * 0.25


class TouchState:
    """Class to track touch state with hysteresis"""
    def __init__(self):
        self.is_touching = False
        self.last_value = 0
        self.stable_start = 0  # Time when stable count started
        
    def update(self, value):
        """Update touch state with hysteresis to prevent rapid switching
        
        Args:
            value (int): Raw sensor value
            
        Returns:
            bool: True if touching, False if not
        """
        now = time.time()
        
        # Check if value has changed significantly from last reading
        if value < config.NO_TOUCH_THRESHOLD:
            if self.last_value >= config.NO_TOUCH_THRESHOLD:
                self.stable_start = now
        else:
            self.stable_start = now
            
        self.last_value = value
        
        # Update touch state with hysteresis
        if not self.is_touching:
            if value >= config.NO_TOUCH_THRESHOLD:
                self.is_touching = True
        else:
            # Use time-based stability check (20ms) instead of sample count
            if value < config.NO_TOUCH_THRESHOLD and (now - self.stable_start) >= 0.02:
                self.is_touching = False
        
        return self.is_touching


class MockAnalogIn:
    """Mock implementation of AnalogIn for development on non-Raspberry Pi platforms"""
    def __init__(self):
        self._value = config.NO_TOUCH_THRESHOLD - 100  # Start below threshold
        self._last_update = time.time()
        self._touch_active = False
        self._touch_position = 0.5  # Center position
        self._touch_direction = 1  # 1 for right, -1 for left
        
    @property
    def value(self):
        """Simulate touch sensor values
        
        Returns values that simulate:
        1. No touch when inactive (below NO_TOUCH_THRESHOLD)
        2. Touch positions that move smoothly when active
        3. Automatic touch release after some time
        """
        now = time.time()
        elapsed = now - self._last_update
        self._last_update = now
        
        # Randomly start/stop touch sequences
        if not self._touch_active and random.random() < 0.001:  # 0.1% chance to start touch
            self._touch_active = True
            self._touch_position = random.random()  # Random start position
            self._touch_direction = 1 if random.random() > 0.5 else -1
            
        if self._touch_active:
            # Move the touch position
            self._touch_position += self._touch_direction * elapsed * 0.5  # Move 50% of range per second
            
            # Bounce at edges or end touch sequence
            if self._touch_position <= 0 or self._touch_position >= 1:
                if random.random() < 0.7:  # 70% chance to end touch sequence
                    self._touch_active = False
                    self._value = config.NO_TOUCH_THRESHOLD - 100  # Return to no-touch state
                else:
                    self._touch_direction *= -1  # Reverse direction
                    
            if self._touch_active:  # Still active after checks
                self._touch_position = max(0, min(1, self._touch_position))
                # Convert position (0-1) to raw sensor value range, ensuring it's above threshold
                self._value = int(config.LEFT_MIN + (self._touch_position * (config.RIGHT_MAX - config.LEFT_MIN)))
                self._value = max(config.NO_TOUCH_THRESHOLD + 100, self._value)  # Ensure it's above threshold
        
        return self._value

