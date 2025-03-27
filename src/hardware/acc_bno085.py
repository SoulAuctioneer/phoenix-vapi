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
)
from adafruit_bno08x.i2c import BNO08X_I2C
from typing import Dict, Any, Tuple, Optional
import asyncio


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
        
    def initialize(self) -> bool:
        """
        Initialize the BNO085 sensor connection.
        
        Returns:
            bool: True if initialization was successful, False otherwise
        """
        try:
            # Initialize I2C and BNO085
            self.i2c = busio.I2C(board.SCL, board.SDA)
            self.imu = BNO08X_I2C(self.i2c)
            
            # Enable features
            self._enable_sensor_reports()
            
            return True
        except Exception as e:
            self.logger.error(f"Failed to initialize BNO085 sensor: {e}")
            return False
            
    def deinitialize(self):
        """
        Deinitialize the sensor and clean up resources.
        """
        if self.i2c:
            try:
                self.i2c.deinit()
            except Exception as e:
                self.logger.error(f"Error deinitializing I2C: {e}")
    
    def _enable_sensor_reports(self):
        """
        Enable all required sensor reports from the BNO085 sensor.
        """
        if self.imu:
            # Motion Vectors
            self.imu.enable_feature(BNO_REPORT_ACCELEROMETER)
            self.imu.enable_feature(BNO_REPORT_GYROSCOPE)
            self.imu.enable_feature(BNO_REPORT_MAGNETOMETER)
            self.imu.enable_feature(BNO_REPORT_LINEAR_ACCELERATION)
            
            # Rotation Vectors
            self.imu.enable_feature(BNO_REPORT_ROTATION_VECTOR)
            self.imu.enable_feature(BNO_REPORT_GEOMAGNETIC_ROTATION_VECTOR)
            self.imu.enable_feature(BNO_REPORT_GAME_ROTATION_VECTOR)
            
            # Classification Reports
            self.imu.enable_feature(BNO_REPORT_STEP_COUNTER)
            self.imu.enable_feature(BNO_REPORT_STABILITY_CLASSIFIER)
            self.imu.enable_feature(BNO_REPORT_ACTIVITY_CLASSIFIER)
            
            # Other Reports - not used
            # self.imu.enable_feature(BNO_REPORT_RAW_ACCELEROMETER)
            # self.imu.enable_feature(BNO_REPORT_RAW_GYROSCOPE)
            # self.imu.enable_feature(BNO_REPORT_RAW_MAGNETOMETER)
            # self.imu.enable_feature(BNO_REPORT_UNCALIBRATED_GYROSCOPE)
            # self.imu.enable_feature(BNO_REPORT_UNCALIBRATED_MAGNETOMETER)
            
    def read_sensor_data(self) -> Dict[str, Any]:
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
                
            # Motion Vectors
            accel_x, accel_y, accel_z = self.imu.acceleration  # m/s^2
            gyro_x, gyro_y, gyro_z = self.imu.gyro  # rad/s
            mag_x, mag_y, mag_z = self.imu.magnetic  # uT
            lin_accel_x, lin_accel_y, lin_accel_z = self.imu.linear_acceleration  # m/s^2
            
            # Rotation Vectors - Access quaternion data directly
            quat_i, quat_j, quat_k, quat_real = self.imu.quaternion  # rotation vector
            geomag_quat_i, geomag_quat_j, geomag_quat_k, geomag_quat_real = self.imu.geomagnetic_quaternion  # geomagnetic rotation
            game_quat_i, game_quat_j, game_quat_k, game_quat_real = self.imu.game_quaternion  # game rotation
            
            # Classification Reports
            stability = self.imu.stability_classification
            activity = self.imu.activity_classification
            step_count = self.imu.steps
            
            # System Information
            calibration_status = self.imu.calibration_status
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
            self.logger.error(f"Error reading sensor data: {e}")
            return {}
        
    def get_calibration_status(self) -> int:
        """
        Get the current calibration status of the sensor.
        
        Returns:
            int: Calibration status value (0-3, where 3 is best)
        """
        if self.imu:
            return self.imu.calibration_status
        return 0
        
    def get_calibration_status_text(self) -> str:
        """
        Get the current calibration status as text.
        
        Returns:
            str: Text representation of calibration status
        """
        if not self.imu:
            return "Unknown"
        status = self.imu.calibration_status
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
            calibration_status = self.imu.calibration_status
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
            self.logger.error(f"Error during calibration check: {e}")
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
            self.imu.begin_calibration()
            self.logger.info("Calibration started. Please move the device in a figure-8 pattern...")
            
            # Monitor calibration status
            calibration_good_at = None
            while not self._calibration_good:
                calibration_status = self.imu.calibration_status
                self.logger.info(f"Calibration status: {REPORT_ACCURACY_STATUS[calibration_status]} ({calibration_status})")
                
                if calibration_status >= 2 and not calibration_good_at:
                    calibration_good_at = asyncio.get_event_loop().time()
                    self.logger.info("Calibration quality reached good level!")
                    
                if calibration_good_at and (asyncio.get_event_loop().time() - calibration_good_at > 5.0):
                    # Save calibration data
                    self.imu.save_calibration_data()
                    self._calibration_good = True
                    self.logger.info("Calibration completed and saved!")
                    break
                    
                await asyncio.sleep(0.1)  # Check every 100ms
                
        except Exception as e:
            self.logger.error(f"Error during calibration: {e}") 