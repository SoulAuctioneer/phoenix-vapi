import logging
import asyncio
import board
import busio
import adafruit_mpu6050
from typing import Dict, Any
from services.service import BaseService

class AccelerometerService(BaseService):
    """Service for reading accelerometer data"""
    def __init__(self, manager, update_interval=0.1):
        super().__init__(manager)
        self.update_interval = update_interval
        self.i2c = None
        self.mpu = None
        self.read_task = None
        
    async def start(self):
        """Start the accelerometer service"""
        await super().start()
        try:
            # Initialize I2C and MPU6050
            self.i2c = busio.I2C(board.SCL, board.SDA)
            self.mpu = adafruit_mpu6050.MPU6050(self.i2c)
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
                acceleration = self.mpu.acceleration
                gyro = self.mpu.gyro
                temperature = self.mpu.temperature
                
                # Publish sensor data event
                await self.publish({
                    "type": "sensor_data",
                    "sensor": "accelerometer",
                    "data": {
                        "acceleration": acceleration,
                        "gyro": gyro,
                        "temperature": temperature
                    }
                })
                
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
        if self.mpu:
            return self.mpu.acceleration
        return (0.0, 0.0, 0.0)
        
    async def get_gyro(self) -> Tuple[float, float, float]:
        """Get current gyroscope values (x, y, z)"""
        if self.mpu:
            return self.mpu.gyro
        return (0.0, 0.0, 0.0)
        
    async def get_temperature(self) -> float:
        """Get current temperature in Celsius"""
        if self.mpu:
            return self.mpu.temperature
        return 0.0 