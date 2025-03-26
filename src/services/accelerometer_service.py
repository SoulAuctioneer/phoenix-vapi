"""
This service reads data from the accelerometer and publishes it to the event bus.

The accelerometer is a BNO085 sensor, a 9-axis sensor that combines an accelerometer, gyroscope, and magnetometer, connected to the I2C bus.
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
    BNO_REPORT_GRAVITY_VECTOR,
    BNO_REPORT_TAP_DETECTOR,
    BNO_REPORT_STEP_COUNTER,
    BNO_REPORT_SIGNIFICANT_MOTION,
    BNO_REPORT_STABILITY_CLASSIFIER,
    BNO_REPORT_ACTIVITY_CLASSIFIER,
    REPORT_ACCURACY_STATUS,
)
from adafruit_bno08x.i2c import BNO08X_I2C
from typing import Dict, Any, Tuple
from services.service import BaseService

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
        try:
            # Initialize I2C and MPU6050
            self.i2c = busio.I2C(board.SCL, board.SDA, frequency=800000)
            self.imu = BNO08X_I2C(self.i2c)
            
            # Check and perform calibration if needed
            await self._check_and_calibrate()
            
            # Enable features
            self.imu.enable_feature(BNO_REPORT_ACCELEROMETER)
            self.imu.enable_feature(BNO_REPORT_GYROSCOPE)
            self.imu.enable_feature(BNO_REPORT_MAGNETOMETER)
            self.imu.enable_feature(BNO_REPORT_ROTATION_VECTOR)
            self.imu.enable_feature(BNO_REPORT_LINEAR_ACCELERATION)
            self.imu.enable_feature(BNO_REPORT_GRAVITY_VECTOR)
            self.imu.enable_feature(BNO_REPORT_TAP_DETECTOR)
            self.imu.enable_feature(BNO_REPORT_STEP_COUNTER)
            self.imu.enable_feature(BNO_REPORT_SIGNIFICANT_MOTION)
            self.imu.enable_feature(BNO_REPORT_STABILITY_CLASSIFIER)
            self.imu.enable_feature(BNO_REPORT_ACTIVITY_CLASSIFIER)
            
            # Start continuous reading
            self.read_task = asyncio.create_task(self._read_loop())
            self.logger.info("Accelerometer service started")
        except Exception as e:
            self.logger.error(f"Failed to initialize accelerometer: {e}")
            raise
            
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
                acceleration = self.get_acceleration()
                gyro = self.get_gyro()
                magnetic = self.get_magnetic()
                rotation_vector = self.get_rotation_vector()
                linear_accel = self.get_linear_acceleration()
                gravity = self.get_gravity_vector()
                tap_detected = self.get_tap_detected()
                steps = self.get_step_count()
                significant_motion = self.get_significant_motion()
                stability = self.get_stability_classifier()
                activity = self.get_activity_classifier()

                # Print data to console for debugging
                self.print_data(acceleration, gyro, magnetic, rotation_vector, linear_accel, gravity, 
                              tap_detected, steps, significant_motion, stability, activity)
                
                # Publish sensor data event
                await self.publish({
                    "type": "sensor_data",
                    "sensor": "accelerometer",
                    "data": {
                        "acceleration": acceleration,
                        "gyro": gyro,
                        "magnetic": magnetic,
                        "rotation_vector": rotation_vector,
                        "linear_acceleration": linear_accel,
                        "gravity": gravity,
                        "tap_detected": tap_detected,
                        "steps": steps,
                        "significant_motion": significant_motion,
                        "stability": stability,
                        "activity": activity,
                        "calibration_status": self.imu.calibration_status if self.imu else 0
                    }
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

    async def get_acceleration(self) -> Tuple[float, float, float]:
        """Get current acceleration values (x, y, z) in m/s^2"""
        if self.imu:
            return self.imu.acceleration
        return (0.0, 0.0, 0.0)
        
    async def get_gyro(self) -> Tuple[float, float, float]:
        """Get current gyroscope values (x, y, z) in rad/s"""
        if self.imu:
            return self.imu.gyro
        return (0.0, 0.0, 0.0)
    
    async def get_magnetic(self) -> Tuple[float, float, float]:
        """Get current magnetic values (x, y, z) in uT"""
        if self.imu:
            return self.imu.magnetic
        return (0.0, 0.0, 0.0)
    
    async def get_rotation_vector(self) -> Tuple[float, float, float, float]:
        """Get current rotation vector values (i, j, k, real) as quaternion"""
        if self.imu:
            return self.imu.quaternion
        return (0.0, 0.0, 0.0, 0.0)

    async def get_linear_acceleration(self) -> Tuple[float, float, float]:
        """Get linear acceleration values (x, y, z) in m/s^2, with gravity removed"""
        if self.imu:
            return self.imu.linear_acceleration
        return (0.0, 0.0, 0.0)

    async def get_gravity_vector(self) -> Tuple[float, float, float]:
        """Get gravity vector values (x, y, z) in m/s^2"""
        if self.imu:
            return self.imu.gravity
        return (0.0, 0.0, 0.0)

    async def get_tap_detected(self) -> bool:
        """Get whether a tap was detected"""
        if self.imu:
            return self.imu.tap_detected
        return False

    async def get_step_count(self) -> int:
        """Get current step count"""
        if self.imu:
            return self.imu.steps
        return 0

    async def get_significant_motion(self) -> bool:
        """Get whether significant motion was detected"""
        if self.imu:
            return self.imu.significant_motion
        return False

    async def get_stability_classifier(self) -> str:
        """Get current stability classification"""
        if self.imu:
            return self.imu.stability_classifier
        return "unknown"

    async def get_activity_classifier(self) -> str:
        """Get current activity classification"""
        if self.imu:
            return self.imu.activity_classifier
        return "unknown"
 
    async def print_data(self, acceleration, gyro, magnetic, rotation_vector, linear_accel, gravity,
                        tap_detected, steps, significant_motion, stability, activity):
        """Print data to console for debugging"""
        print("Acceleration:")
        print("X: %0.6f  Y: %0.6f Z: %0.6f  m/s^2" % (acceleration[0], acceleration[1], acceleration[2]))
        print("")
        print("Gyro:")
        print("X: %0.6f  Y: %0.6f Z: %0.6f rads/s" % (gyro[0], gyro[1], gyro[2]))
        print("")
        print("Magnetometer:")
        print("X: %0.6f  Y: %0.6f Z: %0.6f uT" % (magnetic[0], magnetic[1], magnetic[2]))
        print("")
        print("Rotation Vector Quaternion:")
        print(
            "I: %0.6f  J: %0.6f K: %0.6f  Real: %0.6f" % (rotation_vector[0], rotation_vector[1], rotation_vector[2], rotation_vector[3])
        )
        print("")
        print("Linear Acceleration:")
        print("X: %0.6f  Y: %0.6f Z: %0.6f  m/s^2" % (linear_accel[0], linear_accel[1], linear_accel[2]))
        print("")
        print("Gravity Vector:")
        print("X: %0.6f  Y: %0.6f Z: %0.6f  m/s^2" % (gravity[0], gravity[1], gravity[2]))
        print("")
        print("Tap Detected: %s" % tap_detected)
        print("Step Count: %d" % steps)
        print("Significant Motion: %s" % significant_motion)
        print("Stability Classifier: %s" % stability)
        print("Activity Classifier: %s" % activity)
        if self.imu:
            print("Calibration Status: %s (%d)" % (REPORT_ACCURACY_STATUS[self.imu.calibration_status], self.imu.calibration_status))
        print("")
        
    
        