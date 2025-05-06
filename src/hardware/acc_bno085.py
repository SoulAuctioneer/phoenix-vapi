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
    BNO_REPORT_STEP_COUNTER,
    BNO_REPORT_STABILITY_CLASSIFIER,
    BNO_REPORT_ACTIVITY_CLASSIFIER,
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

        # Motion Vectors 
        await _enable_feature_wrapper(BNO_REPORT_ACCELEROMETER, 5000)        # 5ms (200Hz)
        await _enable_feature_wrapper(BNO_REPORT_GYROSCOPE, 5000)           # 5ms (200Hz)
        await _enable_feature_wrapper(BNO_REPORT_LINEAR_ACCELERATION, 5000) # 5ms (200Hz)
        
        # Less critical for high frequency
        await _enable_feature_wrapper(BNO_REPORT_MAGNETOMETER, 20000)       # 20ms (50Hz)
        
        # Rotation Vectors
        await _enable_feature_wrapper(BNO_REPORT_ROTATION_VECTOR, 10000)     # 10ms (100Hz)
        await _enable_feature_wrapper(BNO_REPORT_GEOMAGNETIC_ROTATION_VECTOR, 20000) # 20ms (50Hz)
        await _enable_feature_wrapper(BNO_REPORT_GAME_ROTATION_VECTOR, 10000)  # 10ms (100Hz)
            
        # Classification Reports
        await _enable_feature_wrapper(BNO_REPORT_STEP_COUNTER, 100000)       # 100ms (10Hz) - Slower is fine
        await _enable_feature_wrapper(BNO_REPORT_STABILITY_CLASSIFIER, 50000) # 50ms (20Hz)
        await _enable_feature_wrapper(BNO_REPORT_ACTIVITY_CLASSIFIER, 50000)  # 50ms (20Hz) - Library default

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
        if feature_id == BNO_REPORT_ACTIVITY_CLASSIFIER:
            sensor_config = _ENABLED_ACTIVITIES
            self.logger.info(f"Enabling feature {feature_id} with interval {interval_us}us and config {sensor_config}")
        else:
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
        - activity: Current activity classification with confidence levels
        - step_count: Number of steps detected
        
        System Information:
        - calibration_status: Numerical calibration status (0-3)
        - calibration_status_text: Text representation of calibration status
        
        Returns:
            Dict[str, Any]: Dictionary containing all sensor readings
        """
        try:
            if not self.imu:
                return {}
                
            # Helper to run blocking property access in a thread
            async def _get_sensor_value(prop_name):
                return await asyncio.to_thread(getattr, self.imu, prop_name)

            accel_x, accel_y, accel_z = await _get_sensor_value("acceleration")
            gyro_x, gyro_y, gyro_z = await _get_sensor_value("gyro")
            mag_x, mag_y, mag_z = await _get_sensor_value("magnetic")
            lin_accel_x, lin_accel_y, lin_accel_z = await _get_sensor_value("linear_acceleration")
            
            quat_i, quat_j, quat_k, quat_real = await _get_sensor_value("quaternion")
            geomag_quat_i, geomag_quat_j, geomag_quat_k, geomag_quat_real = await _get_sensor_value("geomagnetic_quaternion")
            game_quat_i, game_quat_j, game_quat_k, game_quat_real = await _get_sensor_value("game_quaternion")
            
            stability = await _get_sensor_value("stability_classification")
            activity = await _get_sensor_value("activity_classification")
            step_count = await _get_sensor_value("steps")
            
            calibration_status = await _get_sensor_value("calibration_status")
            calibration_status_text = f"{REPORT_ACCURACY_STATUS[calibration_status]} ({calibration_status})"
            
            return {
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
                "activity": activity,
                "step_count": step_count,
                
                # System Information
                "calibration_status": calibration_status,
                "calibration_status_text": calibration_status_text
            }
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