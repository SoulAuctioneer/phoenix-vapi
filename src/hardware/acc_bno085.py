"""
BNO085 Accelerometer Hardware Interface

This module provides a low-level interface to the BNO085 sensor, a 9-axis sensor 
that combines an accelerometer, gyroscope, and magnetometer, connected to the I2C bus.

The BNO085 provides a variety of sensor data reports:

Motion Vectors:
- Acceleration Vector: Three axes of acceleration (gravity + linear motion) in m/s^2
- Angular Velocity Vector (Gyro): Three axes of rotational speed in radians per second
- Magnetic Field Vector: Three axes of magnetic field sensing in micro Teslas (uT)
- Linear Acceleration Vector: Three axes of linear acceleration without gravity, in m/s^2

Rotation Vectors:
- Absolute Orientation / Rotation Vector (Quaternion): From accelerometer, gyro, and magnetometer
- Geomagnetic Rotation Vector (Quaternion): Fusing accelerometer and magnetometer only
- Game Rotation Vector (Quaternion): Optimized for gaming, using accelerometer and gyro

Classification Reports:
- Stability Classification: Classifies motion as "On table", "Stable", or "Motion"
- Step Counter: Tracks number of steps taken
- Activity Classification: Classifies activity type with confidence levels
    activities = [
        "Unknown",
        "In-Vehicle",
        "On-Bicycle",
        "On-Foot",
        "Still",
        "Tilting",
        "Walking",
        "Running",
        "OnStairs",
    ]
- Shake Detector: Detects if the sensor has been shaken

Docs:
https://learn.adafruit.com/adafruit-9-dof-orientation-imu-fusion-breakout-bno085/report-types
https://github.com/adafruit/Adafruit_CircuitPython_BNO08x/tree/main/examples
https://docs.circuitpython.org/projects/bno08x/en/latest/api.html
"""

import board
import busio
import logging
from adafruit_bno08x import (
    BNO_REPORT_ACCELEROMETER,
    BNO_REPORT_GYROSCOPE,
    BNO_REPORT_MAGNETOMETER,
    BNO_REPORT_ROTATION_VECTOR,
    BNO_REPORT_LINEAR_ACCELERATION,
    BNO_REPORT_GEOMAGNETIC_ROTATION_VECTOR,
    BNO_REPORT_GAME_ROTATION_VECTOR,
    # BNO_REPORT_STEP_COUNTER,
    BNO_REPORT_SHAKE_DETECTOR,
    BNO_REPORT_STABILITY_CLASSIFIER,
    # BNO_REPORT_ACTIVITY_CLASSIFIER,
    REPORT_ACCURACY_STATUS,
    # Import necessary constants and functions for manual packet sending
    _SET_FEATURE_COMMAND, 
    _BNO_CHANNEL_CONTROL,
    _ENABLED_ACTIVITIES, # Import the specific config for Activity Classifier
)
from adafruit_bno08x.i2c import BNO08X_I2C
from typing import Dict, Any, Tuple, Optional
import asyncio
from struct import pack_into # Re-add pack_into
# import time # No longer directly used for sleep

# Define a timeout for feature enabling (in seconds)
_FEATURE_ENABLE_TIMEOUT = 3.0 # Restore timeout

class BNO085Interface:
    """
    Hardware interface for the BNO085 9-axis sensor.
    
    This class handles the low-level sensor operations including:
    - Hardware initialization and configuration
    - Reading raw sensor data
    - Sensor calibration procedures
    """
    
    def __init__(self):
        """Initialize the BNO085 interface"""
        self.i2c = None
        self.imu = None
        self._calibration_good = False
        self.logger = logging.getLogger(__name__)
        
        # I2C performance tracking
        self._consecutive_slow_reads = 0
        self._total_reads = 0
        self._slow_read_threshold = 100  # ms
        
    async def initialize(self) -> bool:
        """
        Initialize the BNO085 sensor connection.
        
        Returns:
            bool: True if initialization was successful, False otherwise
        """
        try:
            self.logger.info("Initializing BNO085 sensor...")
            # Initialize I2C and BNO085 - Explicitly set frequency to 400kHz
            # These are blocking calls, run them in a separate thread
            def _init_i2c_and_imu():
                i2c = busio.I2C(board.SCL, board.SDA)
                imu = BNO08X_I2C(i2c)
                return i2c, imu
            
            self.i2c, self.imu = await asyncio.to_thread(_init_i2c_and_imu)
            self.logger.info("I2C and IMU object created.")
            
            await asyncio.sleep(0.1) # Small delay after sensor object creation
            
            self.logger.info("Enabling sensor reports...")
            await self._enable_sensor_reports()
            self.logger.info("Sensor reports enabled.")
            
            return True
        except Exception as e:
            self.logger.error(f"Failed to initialize BNO085 sensor: {e}", exc_info=True)
            return False
            
    def deinitialize(self):
        """
        Deinitialize the sensor and clean up resources.
        """
        if self.i2c:
            try:
                # This is a blocking call, but typically fast.
                # If it causes issues, it could also be wrapped in to_thread.
                self.i2c.deinit()
            except Exception as e:
                self.logger.error(f"Error deinitializing I2C: {e}")
    
    async def _enable_sensor_reports(self):
        """
        Enable all required sensor reports from the BNO085 sensor
        with a custom report interval.
        """
        if not self.imu:
            return

        self.logger.info("Using custom interval enabling...")

        async def _enable_feature_wrapper(feature_id, interval_us):
            await self._enable_feature_with_interval(feature_id, interval_us)

        # Essential motion vectors for free fall detection - Reduced frequency to prevent I2C overload
        await _enable_feature_wrapper(BNO_REPORT_ACCELEROMETER, 20000)        # 20ms (50Hz) - Reduced from 200Hz
        await _enable_feature_wrapper(BNO_REPORT_LINEAR_ACCELERATION, 20000)  # 20ms (50Hz) - Reduced from 200Hz
        await _enable_feature_wrapper(BNO_REPORT_GYROSCOPE, 20000)            # 20ms (50Hz) - Reduced from 200Hz
        
        # Rotation data - Lower frequency to reduce I2C load
        await _enable_feature_wrapper(BNO_REPORT_GAME_ROTATION_VECTOR, 50000)  # 50ms (20Hz) - Reduced from 100Hz
        
        # Classification Reports - Very low frequency (optional)
        await _enable_feature_wrapper(BNO_REPORT_STABILITY_CLASSIFIER, 100000) # 100ms (10Hz)
        await _enable_feature_wrapper(BNO_REPORT_SHAKE_DETECTOR, 100000)       # 100ms (10Hz)
        
        # Disabled to reduce I2C overhead - not essential for free fall detection
        # await _enable_feature_wrapper(BNO_REPORT_MAGNETOMETER, 20000)       # 20ms (50Hz)
        # await _enable_feature_wrapper(BNO_REPORT_ROTATION_VECTOR, 10000)     # 10ms (100Hz)
        # await _enable_feature_wrapper(BNO_REPORT_GEOMAGNETIC_ROTATION_VECTOR, 20000) # 20ms (50Hz)
        # await _enable_feature_wrapper(BNO_REPORT_ACTIVITY_CLASSIFIER, 50000)  # 50ms (20Hz) - Library default
        # await _enable_feature_wrapper(BNO_REPORT_STEP_COUNTER, 100000)       # 100ms (10Hz) - Slower is fine

        self.logger.info("Finished enabling features using custom intervals.")

    # Re-add the custom enabling function with corrections
    async def _enable_feature_with_interval(self, feature_id: int, interval_us: int):
        """
        Enables a specific feature with a custom report interval by sending the raw command.
        Uses correct interval units (microseconds) and packing format.
        """
        if not self.imu:
            return
            
        # Determine sensor-specific config
        sensor_config = 0
        # if feature_id == BNO_REPORT_ACTIVITY_CLASSIFIER:
        #     sensor_config = _ENABLED_ACTIVITIES
        #     self.logger.info(f"Enabling feature {feature_id} with interval {interval_us}us and config {sensor_config}")
        # else:
        self.logger.info(f"Enabling feature {feature_id} with interval {interval_us}us")
        
        # Manually construct the _SET_FEATURE_COMMAND packet
        set_feature_report = bytearray(17)
        set_feature_report[0] = _SET_FEATURE_COMMAND # Command
        set_feature_report[1] = feature_id          # Feature Report ID
        # Bytes 2-4: Feature flags (default 0)
        pack_into("<i", set_feature_report, 5, interval_us) # Change Period (LSB) - Use signed int <i
        # Bytes 9-12: Batch Interval (default 0)
        # Bytes 13-16: Sensor-specific config
        pack_into("<I", set_feature_report, 13, sensor_config) # Config uses unsigned int <I
        
        # Send the packet
        try:
            await asyncio.to_thread(self.imu._send_packet, _BNO_CHANNEL_CONTROL, set_feature_report)
        except Exception as e:
            self.logger.error(f"Failed to send feature command for {feature_id}: {e}", exc_info=True)
            raise RuntimeError(f"Failed sending command for {feature_id}") from e # Re-raise

        # Wait for confirmation that the feature is enabled
        start_time = asyncio.get_event_loop().time()
        while (asyncio.get_event_loop().time() - start_time) < _FEATURE_ENABLE_TIMEOUT:
            try:
                # Process any available packets from the sensor
                await asyncio.to_thread(self.imu._process_available_packets, max_packets=10)
            except Exception as e:
                # Log errors during packet processing but continue trying
                self.logger.warning(f"Error processing packets while enabling {feature_id}: {e}")
            
            # Check if the feature is now available in the library's readings, regardless of packet processing errors
            if feature_id in self.imu._readings: 
                self.logger.info(f"Feature {feature_id} enabled successfully.")
                return # Feature is enabled

            # Log keys and sleep on every loop iteration
            await asyncio.sleep(0.01) # Small delay before checking again

        # If the loop finishes without confirmation, raise an error
        self.logger.error(f"Timeout: Failed to enable feature {feature_id} within {_FEATURE_ENABLE_TIMEOUT}s. Readings: {self.imu._readings.keys()}")
        raise RuntimeError(f"Was not able to enable feature {feature_id}")

    async def read_sensor_data(self) -> Dict[str, Any]:
        """
        Read data from the BNO085 sensor.
        
        This method reads various sensor data types from the BNO085 sensor and returns them in a dictionary.
        The data includes:
        
        Motion Vectors:
        - acceleration: Raw acceleration values (x, y, z) in m/s^2
        - linear_acceleration: Linear acceleration with gravity removed (x, y, z) in m/s^2
        - gyro: Angular velocity values (x, y, z) in radians per second
        - magnetometer: Magnetic field strength values (x, y, z) in micro Teslas (uT)
        
        Rotation Vectors:
        - rotation_vector: Absolute orientation as a quaternion (x, y, z, w)
        - geomagnetic_rotation: Low-power orientation as a quaternion (x, y, z, w)
        - game_rotation: Gaming-optimized orientation as a quaternion (x, y, z, w)
        
        Classification Reports:
        - stability: Current stability classification ("On table", "Stable", or "Motion")
        - shake: Current shake detection status
        - DISABLED: activity: Current activity classification with confidence levels
        - DISABLED: step_count: Number of steps detected
        
        System Information:
        - calibration_status: Numerical calibration status (0-3)
        - calibration_status_text: Text representation of calibration status
        
        Returns:
            Dict[str, Any]: Dictionary containing all sensor readings
        """
        try:
            if not self.imu:
                return {}
            
            import time
            read_start = time.perf_counter()
                
            # Batch read all sensor values in a single thread operation to minimize I2C overhead
            def _batch_read_sensors():
                batch_start = time.perf_counter()
                
                # Read only enabled sensors in one thread operation to reduce context switching
                result = {}
                timings = {}
                
                # Time each sensor read individually
                sensor_start = time.perf_counter()
                result['acceleration'] = self.imu.acceleration
                timings['acceleration_ms'] = (time.perf_counter() - sensor_start) * 1000
                
                sensor_start = time.perf_counter()
                result['gyro'] = self.imu.gyro
                timings['gyro_ms'] = (time.perf_counter() - sensor_start) * 1000
                
                sensor_start = time.perf_counter()
                result['linear_acceleration'] = self.imu.linear_acceleration
                timings['linear_acceleration_ms'] = (time.perf_counter() - sensor_start) * 1000
                
                sensor_start = time.perf_counter()
                result['game_quaternion'] = self.imu.game_quaternion
                timings['game_quaternion_ms'] = (time.perf_counter() - sensor_start) * 1000
                
                sensor_start = time.perf_counter()
                result['stability_classification'] = self.imu.stability_classification
                timings['stability_ms'] = (time.perf_counter() - sensor_start) * 1000
                
                sensor_start = time.perf_counter()
                result['shake'] = self.imu.shake
                timings['shake_ms'] = (time.perf_counter() - sensor_start) * 1000
                
                sensor_start = time.perf_counter()
                result['calibration_status'] = self.imu.calibration_status
                timings['calibration_ms'] = (time.perf_counter() - sensor_start) * 1000
                
                batch_end = time.perf_counter()
                result['_batch_read_time_ms'] = (batch_end - batch_start) * 1000
                result['_individual_timings'] = timings
                return result
            
            # Single batch read instead of multiple individual reads
            thread_start = time.perf_counter()
            sensor_data = await asyncio.to_thread(_batch_read_sensors)
            thread_end = time.perf_counter()
            
            # Extract timing info
            batch_read_time = sensor_data.pop('_batch_read_time_ms', 0)
            individual_timings = sensor_data.pop('_individual_timings', {})
            thread_overhead_time = (thread_end - thread_start) * 1000 - batch_read_time
            
            # Extract values from batch read
            extract_start = time.perf_counter()
            accel_x, accel_y, accel_z = sensor_data['acceleration']
            gyro_x, gyro_y, gyro_z = sensor_data['gyro']
            lin_accel_x, lin_accel_y, lin_accel_z = sensor_data['linear_acceleration']
            
            # Use game quaternion for rotation data (others disabled)
            game_quat_i, game_quat_j, game_quat_k, game_quat_real = sensor_data['game_quaternion']
            
            # Use game quaternion for all quaternion outputs (since others are disabled)
            quat_i, quat_j, quat_k, quat_real = game_quat_i, game_quat_j, game_quat_k, game_quat_real
            geomag_quat_i, geomag_quat_j, geomag_quat_k, geomag_quat_real = game_quat_i, game_quat_j, game_quat_k, game_quat_real
            
            # Set disabled sensors to default values
            mag_x, mag_y, mag_z = 0.0, 0.0, 0.0  # Magnetometer disabled
            
            stability = sensor_data['stability_classification']
            shake_detected = sensor_data['shake']
            calibration_status = sensor_data['calibration_status']
            calibration_status_text = f"{REPORT_ACCURACY_STATUS[calibration_status]} ({calibration_status})"
            
            extract_end = time.perf_counter()
            extract_time = (extract_end - extract_start) * 1000
            
            read_end = time.perf_counter()
            total_read_time = (read_end - read_start) * 1000
            
            # Track I2C performance
            self._total_reads += 1
            if total_read_time > self._slow_read_threshold:
                self._consecutive_slow_reads += 1
            else:
                self._consecutive_slow_reads = 0
            
            # Log timing details if read is slow (>50ms)
            if total_read_time > 50:
                # Find the slowest sensor
                slowest_sensor = max(individual_timings.items(), key=lambda x: x[1]) if individual_timings else ("unknown", 0)
                sensor_details = ", ".join([f"{k.replace('_ms', '')}={v:.1f}" for k, v in individual_timings.items()])
                
                # Add I2C health info
                i2c_health = f"ConsecutiveSlow={self._consecutive_slow_reads}, TotalReads={self._total_reads}"
                self.logger.warning(f"Slow sensor read: Total={total_read_time:.1f}ms, Batch={batch_read_time:.1f}ms, Thread={thread_overhead_time:.1f}ms, Extract={extract_time:.1f}ms, Slowest={slowest_sensor[0]}={slowest_sensor[1]:.1f}ms, I2C=[{i2c_health}], All=[{sensor_details}]")
                
                # Alert if we have many consecutive slow reads (possible I2C bus issue)
                if self._consecutive_slow_reads >= 5:
                    self.logger.error(f"I2C BUS ISSUE DETECTED: {self._consecutive_slow_reads} consecutive slow reads, consider reducing sensor frequencies or checking I2C bus health")
            
            result = {
                # Motion Vectors
                "acceleration": (accel_x, accel_y, accel_z),
                "linear_acceleration": (lin_accel_x, lin_accel_y, lin_accel_z),
                "gyro": (gyro_x, gyro_y, gyro_z),
                "magnetometer": (mag_x, mag_y, mag_z),
                
                # Rotation Vectors
                "rotation_vector": (quat_i, quat_j, quat_k, quat_real),
                "geomagnetic_rotation": (geomag_quat_i, geomag_quat_j, geomag_quat_k, geomag_quat_real),
                "game_rotation": (game_quat_i, game_quat_j, game_quat_k, game_quat_real),
                
                # Classification Reports
                "stability": stability,
                "shake": shake_detected,
                # "activity": activity,
                # "step_count": step_count,
                
                # System Information
                "calibration_status": calibration_status,
                "calibration_status_text": calibration_status_text,
                
                # Timing diagnostics
                "_timing": {
                    "total_read_ms": total_read_time,
                    "batch_read_ms": batch_read_time,
                    "thread_overhead_ms": thread_overhead_time,
                    "extract_ms": extract_time,
                    "individual_sensors": individual_timings
                }
            }
            
            return result
        except Exception as e:
            self.logger.error(f"Error reading sensor data: {e}", exc_info=True)
            return {}
        
    async def get_calibration_status(self) -> int:
        """
        Get the current calibration status of the sensor.
        
        Returns:
            int: Calibration status value (0-3, where 3 is best)
        """
        if self.imu:
            return await asyncio.to_thread(lambda: self.imu.calibration_status)
        return 0
        
    async def get_calibration_status_text(self) -> str:
        """
        Get the current calibration status as text.
        
        Returns:
            str: Text representation of calibration status
        """
        if not self.imu:
            return "Unknown"
        status = await asyncio.to_thread(lambda: self.imu.calibration_status)
        return f"{REPORT_ACCURACY_STATUS[status]} ({status})"
    
    async def check_and_calibrate(self) -> bool:
        """
        Check calibration status and perform calibration if needed.
        
        Returns:
            bool: True if calibration is good, False otherwise
        """
        try:
            if not self.imu:
                return False
                
            # Get current calibration status
            calibration_status = await asyncio.to_thread(lambda: self.imu.calibration_status)
            self.logger.info(f"Initial calibration status: {REPORT_ACCURACY_STATUS[calibration_status]} ({calibration_status})")
            
            # If calibration is not good (status < 2), perform calibration
            if calibration_status < 2:
                self.logger.info("Calibration needed. Starting calibration process...")
                await self._perform_calibration()
            else:
                self._calibration_good = True
                self.logger.info("Calibration already good, no calibration needed")
                
            return self._calibration_good
                
        except Exception as e:
            self.logger.error(f"Error during calibration check: {e}", exc_info=True)
            return False
            
    async def _perform_calibration(self):
        """
        Perform the calibration process for the sensor.
        
        This method starts calibration and monitors status until calibration is good.
        """
        try:
            if not self.imu:
                return
                
            # Start calibration
            await asyncio.to_thread(self.imu.begin_calibration)
            self.logger.info("Calibration started. Please move the device in a figure-8 pattern...")
            
            # Monitor calibration status
            calibration_good_at = None
            loop = asyncio.get_event_loop()
            
            while not self._calibration_good:
                current_time = loop.time()
                calibration_status = await asyncio.to_thread(lambda: self.imu.calibration_status)
                self.logger.info(f"Calibration status: {REPORT_ACCURACY_STATUS[calibration_status]} ({calibration_status})")
                
                if calibration_status >= 2 and not calibration_good_at:
                    calibration_good_at = current_time
                    self.logger.info("Calibration quality reached good level!")
                    
                if calibration_good_at and (current_time - calibration_good_at > 5.0):
                    # Save calibration data
                    await asyncio.to_thread(self.imu.save_calibration_data)
                    self._calibration_good = True
                    self.logger.info("Calibration completed and saved!")
                    break
                    
                await asyncio.sleep(0.1)  # Check every 100ms
                
        except Exception as e:
            self.logger.error(f"Error during calibration: {e}", exc_info=True) 