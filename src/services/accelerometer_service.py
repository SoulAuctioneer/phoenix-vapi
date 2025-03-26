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
        
    async def start(self):
        """Start the accelerometer service"""
        await super().start()
        try:
            # Initialize I2C and MPU6050
            self.i2c = busio.I2C(board.SCL, board.SDA, frequency=800000)
            self.imu = BNO08X_I2C(self.i2c)
            # Enable features
            self.imu.enable_feature(BNO_REPORT_ACCELEROMETER)
            self.imu.enable_feature(BNO_REPORT_GYROSCOPE)
            self.imu.enable_feature(BNO_REPORT_MAGNETOMETER)
            self.imu.enable_feature(BNO_REPORT_ROTATION_VECTOR)
            # Start continuous reading
            self.read_task = asyncio.create_task(self._read_loop())
            self.logger.info("Accelerometer service started")
        except Exception as e:
            self.logger.error(f"Failed to initialize accelerometer: {e}")
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

                # Print data to console for debugging
                self.print_data(acceleration, gyro, magnetic, rotation_vector)
                
                # Publish sensor data event
                await self.publish({
                    "type": "sensor_data",
                    "sensor": "accelerometer",
                    "data": { acceleration, gyro, magnetic, rotation_vector }
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
        """Get current acceleration values (x, y, z)"""
        if self.imu:
            return self.imu.acceleration
        return (0.0, 0.0, 0.0)
        
    async def get_gyro(self) -> Tuple[float, float, float]:
        """Get current gyroscope values (x, y, z)"""
        if self.imu:
            return self.imu.gyro
        return (0.0, 0.0, 0.0)
    
    async def get_magnetic(self) -> Tuple[float, float, float]:
        """Get current magnetic values (x, y, z)"""
        if self.imu:
            return self.imu.magnetic
        return (0.0, 0.0, 0.0)
    
    async def get_rotation_vector(self) -> Tuple[float, float, float, float]:
        """Get current rotation vector values (i, j, k, real)"""
        if self.imu:
            return self.imu.quaternion
        return (0.0, 0.0, 0.0, 0.0)
 
    async def print_data(self, acceleration, gyro, magnetic, rotation_vector):
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
        
    
        