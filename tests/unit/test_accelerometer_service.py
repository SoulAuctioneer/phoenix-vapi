"""
Unit tests for the AccelerometerService.

These tests mock hardware dependencies to test the service functionality
without requiring physical hardware.
"""

import unittest
from unittest.mock import patch, MagicMock, AsyncMock
import asyncio
import sys
import os

# Mock hardware modules before imports
sys.modules['board'] = MagicMock()
sys.modules['busio'] = MagicMock()
sys.modules['adafruit_bno08x'] = MagicMock()
sys.modules['adafruit_bno08x.i2c'] = MagicMock()

# Add src directory to path for imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../src')))

# Now import with hardware mocked
with patch('hardware.acc_bno085.BNO085Interface'):
    from services.accelerometer_service import AccelerometerService
    from managers.accelerometer_manager import AccelerometerManager
    from config import AccelerometerConfig

class TestAccelerometerService(unittest.TestCase):
    """Test cases for the AccelerometerService class."""
    
    def setUp(self):
        """Set up test fixtures before each test method."""
        # Create a mock for the service manager (event bus)
        self.mock_service_manager = MagicMock()
        self.mock_service_manager.publish = AsyncMock()
        
        # Create a patch for the AccelerometerManager
        self.manager_patcher = patch('services.accelerometer_service.AccelerometerManager')
        self.mock_manager_class = self.manager_patcher.start()
        
        # Set up the mock manager instance that will be created by the service
        self.mock_manager = MagicMock()
        self.mock_manager_class.return_value = self.mock_manager
        
        # Configure the mock manager's methods
        self.mock_manager.initialize.return_value = True
        self.mock_manager.read_sensor_data.return_value = {
            'acceleration': (0.1, 0.2, 9.8),
            'linear_acceleration': (0.1, 0.2, 0.3),
            'gyro': (0.01, 0.02, 0.03),
            'magnetometer': (10, 20, 30),
            'rotation_vector': (0.1, 0.2, 0.3, 0.9),
            'game_rotation': (0.1, 0.2, 0.3, 0.9),
            'heading': 45.0,
            'energy': 0.2,
            'timestamp': 12345.6789
        }
        
        # Create an accelerometer service with test config
        self.update_interval = 0.01  # Fast interval for tests
        self.service = AccelerometerService(
            self.mock_service_manager,
            update_interval=self.update_interval
        )
    
    def tearDown(self):
        """Tear down test fixtures after each test method."""
        self.manager_patcher.stop()
    
    async def test_start_stop(self):
        """Test starting and stopping the service."""
        # Start the service
        await self.service.start()
        
        # Check that the manager was initialized
        self.mock_manager.initialize.assert_called_once()
        
        # Wait a bit to allow the service to read data a few times
        await asyncio.sleep(self.update_interval * 3)
        
        # Stop the service
        await self.service.stop()
        
        # Check that the manager was deinitialized
        self.mock_manager.deinitialize.assert_called_once()
    
    async def test_read_and_publish(self):
        """Test that the service reads and publishes data correctly."""
        # Start the service with a read task
        await self.service.start()
        
        # Wait a bit to allow the service to read and publish data
        await asyncio.sleep(self.update_interval * 3)
        
        # Check that read_sensor_data was called
        self.mock_manager.read_sensor_data.assert_called()
        
        # Check that data was published to the event bus
        self.mock_service_manager.publish.assert_called()
        
        # Get the first event that was published
        first_event = self.mock_service_manager.publish.call_args_list[0][0][0]
        
        # Verify event structure
        self.assertEqual(first_event['type'], 'sensor_data')
        self.assertEqual(first_event['sensor'], 'accelerometer')
        self.assertIn('data', first_event)
        
        # Stop the service
        await self.service.stop()
    
    async def test_calibrate(self):
        """Test the calibration functionality."""
        # Set up the mock to return a successful calibration
        self.mock_manager.check_and_calibrate = AsyncMock(return_value=True)
        
        # Call the calibrate method
        result = await self.service.calibrate()
        
        # Verify the result
        self.assertTrue(result)
        self.mock_manager.check_and_calibrate.assert_called_once()

def run_tests():
    """Run the tests asynchronously."""
    async def run_async_tests():
        # Get all test methods from TestAccelerometerService
        test_methods = [m for m in dir(TestAccelerometerService) if m.startswith('test_')]
        
        # Create an instance of the test class
        test_instance = TestAccelerometerService()
        
        # Run setUp, test, and tearDown for each test method
        for method_name in test_methods:
            try:
                test_instance.setUp()
                test_method = getattr(test_instance, method_name)
                if asyncio.iscoroutinefunction(test_method):
                    await test_method()
                else:
                    test_method()
                print(f"✅ {method_name} passed")
            except Exception as e:
                print(f"❌ {method_name} failed: {e}")
            finally:
                test_instance.tearDown()
    
    # Run the async tests
    asyncio.run(run_async_tests())

if __name__ == "__main__":
    run_tests() 