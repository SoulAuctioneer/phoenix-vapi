"""
This service reads data from the accelerometer and publishes it to the event bus.

The accelerometer is a BNO085 sensor, a 9-axis sensor that combines an accelerometer, gyroscope, and magnetometer, connected to the I2C bus.

Motion Vectors:
These reports return calibrated X, Y, and Z axis measurements for the given sensor measurement type.
- Acceleration Vector / Accelerometer: Three axes of acceleration from gravity and linear motion, in m/s^2
- Angular Velocity Vector / Gyro: Three axes of rotational speed in radians per second
- Magnetic Field Strength Vector / Magnetometer: Three axes of magnetic field sensing in micro Teslas (uT)
- Linear Acceleration Vector: Three axes of linear acceleration data with the acceleration from gravity, in m/s^2

Rotation Vectors:
These reports are generated by the BNO085's sensor fusion firmware based on the combination of multiple three-axis motion vectors and are each optimized for different use cases.
- Absolute Orientation / Rotation Vector (Quaternion): Optimized for accuracy and referenced to magnetic north and gravity from accelerometer, gyro, and magnetometer data. The data is presented as a four point quaternion output for accurate data manipulation.
- Geomagnetic Rotation Vector (Quaternion): Optimized for low power by fusing the accelerometer and magnetometer only, at the cost of responsiveness and accuracy.
- Game Rotation Vector (Quaternion): Optimized for a smoother gaming experience, fused from the accelerometer and gyro without the magnetometer to avoid sudden jumps in the output from magnetometer based corrections.

Classification Reports:
Using its sensor fusion products, the BNO085 can attempt to classify and detect different types of motion it measures.
- Stability Classification: Uses the accelerometer and gyro to classify the detected motion as "On table", "Stable", or "Motion"
- Step Counter: Based on the data from the step detector, the sensor tracks the number of steps taken, possibly reclassifying previous events based on the patterns detected.
- Activity Classification: Classifies the detected motion as one of several activity types, providing a most likely classification along with confidence levels for the most likely and other motion types: Unknown, In-Vehicle, On-Bicycle, On-Foot, Still, Tilting, Walking, Running, OnStairs
- Shake Detector: Detects if the sensor has been shaken

Other Motion Reports (not currently used):
The BNO085 also provides raw ADC readings as well as uncorrected measurements for the accelerometer, gyro, and magnetometer.
- Raw Accelerometer: Unscaled direct ADC readings
- Uncalibrated Gyroscope: Angular velocity without bias compensation, with bias separated
- Raw Gyroscope: Unscaled direct ADC readings
- Uncalibrated Magnetometer: Magnetic field measurements without hard iron offset, offset supplied separately
- Raw Magnetometer: Unscaled direct ADC readings

Reports the BNO085 sensor can provide that the Adafruit library does not currently support:
- Gravity Vector
- AR/VR stabilized Rotation Vector
- AR/VR stabilized Game rotation vector
- Gyro rotation Vector
- Gyro rotation Vector Prediction
- Significant Motion Detector
- Stability Detection
- Tap Detector
- Step Detector

Docs:
https://learn.adafruit.com/adafruit-9-dof-orientation-imu-fusion-breakout-bno085/report-types
https://github.com/adafruit/Adafruit_CircuitPython_BNO08x/tree/main/examples
https://docs.circuitpython.org/projects/bno08x/en/latest/api.html

"""

import asyncio
import board
import busio
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
from typing import Dict, Any, Tuple
from services.service import BaseService
from math import atan2, sqrt, pi
from config import AccelerometerConfig

class AccelerometerService(BaseService):
    """Service for reading accelerometer data"""
    def __init__(self, manager, update_interval=0.5):
        super().__init__(manager)
        self.update_interval = update_interval
        self.i2c = None
        self.imu = None
        self.read_task = None
        self._calibration_good = False
        
    async def start(self):
        """Start the accelerometer service"""
        await super().start()
        # try:
        # Initialize I2C and MPU6050
        self.i2c = busio.I2C(board.SCL, board.SDA)
        self.imu = BNO08X_I2C(self.i2c)
        
        # Enable features
        self._enable_sensor_reports()
        
        # Check and perform calibration if needed
        # await self._check_and_calibrate()
        
        # Start continuous reading
        self.read_task = asyncio.create_task(self._read_loop())
        self.logger.info("Accelerometer service started")
        # except Exception as e:
        #     self.logger.error(f"Failed to initialize accelerometer: {e}")
        #     raise
            
    async def stop(self):
        """Stop the accelerometer service"""
        if self.read_task:
            self.read_task.cancel()
            try:
                await self.read_task
            except asyncio.CancelledError:
                pass
        if self.i2c:
            self.i2c.deinit()
        await super().stop()
        
    async def _read_loop(self):
        """Continuous loop to read accelerometer data"""
        try:
            while True:
                # Read data from accelerometer
                data = self._read_sensor_data()
                
                # Print data to console for debugging
                if AccelerometerConfig.PRINT_DEBUG_DATA:
                    self._print_data(data)
                
                # Publish sensor data event
                await self.publish({
                    "type": "sensor_data",
                    "sensor": "accelerometer",
                    "data": data
                })
                
                # Wait for the update interval
                await asyncio.sleep(self.update_interval)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.logger.error(f"Error reading accelerometer: {e}")
            raise
            
    async def handle_event(self, event: Dict[str, Any]):
        """Handle events from other services"""
        # Currently no events to handle
        pass

    def _find_heading(self, dqw: float, dqx: float, dqy: float, dqz: float) -> float:
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

    def _read_sensor_data(self) -> Dict[str, Any]:
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
        
        Heading:
        - heading: Absolute heading in degrees (0-360 clockwise) calculated using rotation vector
        
        Classification Reports:
        - stability: Current stability classification ("On table", "Stable", or "Motion")
        - activity: Current activity classification with confidence levels
        - step_count: Number of steps detected
        
        Returns:
            Dict[str, Any]: Dictionary containing all sensor readings
        """
        try:
            # Motion Vectors
            accel_x, accel_y, accel_z = self.imu.acceleration  # m/s^2
            gyro_x, gyro_y, gyro_z = self.imu.gyro  # rad/s
            mag_x, mag_y, mag_z = self.imu.magnetic  # uT
            lin_accel_x, lin_accel_y, lin_accel_z = self.imu.linear_acceleration  # m/s^2
            
            # Rotation Vectors - Access quaternion data directly
            quat_i, quat_j, quat_k, quat_real = self.imu.quaternion  # rotation vector
            geomag_quat_i, geomag_quat_j, geomag_quat_k, geomag_quat_real = self.imu.geomagnetic_quaternion  # geomagnetic rotation
            game_quat_i, game_quat_j, game_quat_k, game_quat_real = self.imu.game_quaternion  # game rotation
            
            # Calculate heading
            heading = self._find_heading(quat_real, quat_i, quat_j, quat_k)
            
            # Classification Reports
            stability = self.imu.stability_classification
            activity = self.imu.activity_classification
            step_count = self.imu.steps
            
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
                
                # Heading
                "heading": heading,
                
                # Classification Reports
                "stability": stability,
                "activity": activity,
                "step_count": step_count            }
        except Exception as e:
            self.logger.error(f"Error reading sensor data: {e}")
            return {}

    async def _check_and_calibrate(self):
        """Check calibration status and perform calibration if needed"""
        try:
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
                
        except Exception as e:
            self.logger.error(f"Error during calibration check: {e}")
            raise
            
    async def _perform_calibration(self):
        """Perform the calibration process"""
        try:
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
            raise
            
    def _print_data(self, data):
        """Print data to console for debugging"""
        for key, value in data.items():
            if isinstance(value, tuple):
                print(f"{key}:")
                for i, val in enumerate(value):
                    print(f"{i}: {val}")
            else:
                print(f"{key}: {value}")
        if self.imu:
            print("Calibration Status: %s (%d)" % (REPORT_ACCURACY_STATUS[self.imu.calibration_status], self.imu.calibration_status))
        print("")
        
    def _enable_sensor_reports(self):
        """Enable all sensor reports from the BNO085 sensor"""
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
