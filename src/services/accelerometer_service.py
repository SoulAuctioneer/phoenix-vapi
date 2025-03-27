"""
This service reads data from the accelerometer and publishes it to the event bus.

The accelerometer is a BNO085 sensor, a 9-axis sensor that combines an accelerometer, gyroscope, and magnetometer, connected to the I2C bus.

This service uses the AccelerometerManager to handle low-level sensor interactions and focuses on event publishing
and higher-level application logic.

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
from typing import Dict, Any
from services.service import BaseService
from managers.accelerometer_manager import AccelerometerManager
from config import AccelerometerConfig

class AccelerometerService(BaseService):
    """
    Service for reading accelerometer data and publishing it to the event bus.
    
    This service abstracts the hardware details and focuses on:
    1. Publishing sensor data at regular intervals
    2. Processing sensor events
    3. Handling service lifecycle
    """
    def __init__(self, service_manager, update_interval=AccelerometerConfig.UPDATE_INTERVAL):
        """
        Initialize the AccelerometerService.
        
        Args:
            service_manager: Service manager instance that handles event bus
            update_interval: How often to read and publish sensor data in seconds
        """
        super().__init__(service_manager)
        self.update_interval = update_interval
        self.manager = AccelerometerManager()
        self.read_task = None
        
    async def start(self):
        """
        Start the accelerometer service.
        
        This initializes the hardware and begins the data reading loop.
        """
        await super().start()
        
        # Initialize the sensor via the manager
        if self.manager.initialize():
            # Start continuous reading
            self.read_task = asyncio.create_task(self._read_loop())
            self.logger.info("Accelerometer service started")
        else:
            self.logger.error("Failed to initialize accelerometer")
            
    async def stop(self):
        """
        Stop the accelerometer service.
        
        This cancels the reading task and deinitializes the hardware.
        """
        if self.read_task:
            self.read_task.cancel()
            try:
                await self.read_task
            except asyncio.CancelledError:
                pass
                
        # Deinitialize the sensor
        self.manager.deinitialize()
        await super().stop()
        
    async def _read_loop(self):
        """
        Continuous loop to read accelerometer data and publish events.
        """
        try:
            while True:
                # Read data from accelerometer via manager
                data = self.manager.read_sensor_data()
                
                # Print data to console for debugging
                if AccelerometerConfig.PRINT_DEBUG_DATA:
                    self.manager.print_data(data)
                
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
        """
        Handle events from other services.
        
        Args:
            event: The event to handle
        """
        # Currently no events to handle
        pass
            
    async def calibrate(self):
        """
        Perform sensor calibration.
        
        Returns:
            bool: True if calibration succeeded, False otherwise
        """
        return await self.manager.check_and_calibrate()
