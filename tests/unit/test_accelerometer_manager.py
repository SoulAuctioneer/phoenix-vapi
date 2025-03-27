"""
Unit tests for the AccelerometerManager.

These tests verify the functionality of the AccelerometerManager, especially
the motion pattern detection methods that were previously causing errors.
"""

import unittest
from unittest.mock import patch, MagicMock
import sys
import os
import time
from collections import deque

# Mock hardware modules before imports
sys.modules['board'] = MagicMock()
sys.modules['busio'] = MagicMock()
sys.modules['adafruit_bno08x'] = MagicMock()
sys.modules['adafruit_bno08x.i2c'] = MagicMock()

# Add src directory to path for imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../src')))

# Now import the module
with patch('hardware.acc_bno085.BNO085Interface'):
    from managers.accelerometer_manager import AccelerometerManager, MotionState, MotionPattern

class TestAccelerometerManager(unittest.TestCase):
    """Test cases for the AccelerometerManager class."""
    
    def setUp(self):
        """Set up test fixtures before each test method."""
        # Create a patch for the BNO085Interface
        self.interface_patcher = patch('managers.accelerometer_manager.BNO085Interface')
        self.mock_interface_class = self.interface_patcher.start()
        
        # Set up the mock interface instance
        self.mock_interface = MagicMock()
        self.mock_interface_class.return_value = self.mock_interface
        
        # Configure the mock interface
        self.mock_interface.initialize.return_value = True
        self.mock_interface.read_sensor_data.return_value = self._create_sample_data()
        
        # Create an accelerometer manager
        self.manager = AccelerometerManager()
        
        # Directly set up motion history with some sample data
        self.manager.motion_history = deque(maxlen=20)
        self._populate_motion_history()
    
    def tearDown(self):
        """Tear down test fixtures after each test method."""
        self.interface_patcher.stop()
    
    def _create_sample_data(self):
        """Create sample sensor data."""
        return {
            'acceleration': (0.1, 0.2, 9.8),
            'linear_acceleration': (0.1, 0.2, 0.3),
            'gyro': (0.01, 0.02, 0.03),
            'magnetometer': (10, 20, 30),
            'rotation_vector': (0.1, 0.2, 0.3, 0.9),
            'geomagnetic_rotation': (0.1, 0.2, 0.3, 0.9),
            'game_rotation': (0.1, 0.2, 0.3, 0.9),
            'stability': 'Stable',
            'activity': {'most_likely': 'Still', 'Still': 90},
            'step_count': 0,
            'calibration_status': 2,
            'calibration_status_text': 'Medium Accuracy (2)'
        }
    
    def _populate_motion_history(self):
        """Populate the motion history with sample data."""
        base_time = time.time()
        for i in range(10):
            # Create varying data to simulate motion
            data = self._create_sample_data()
            data['timestamp'] = base_time - (10 - i) * 0.1  # Sequential timestamps
            
            # Add some variation to test edge cases
            if i == 5:
                # Add invalid game_rotation
                data['game_rotation'] = "invalid"
                
            if i == 7:
                # Add invalid gyro
                data['gyro'] = None
                
            self.manager.motion_history.append(data)
    
    def test_initialization(self):
        """Test initializing the manager."""
        self.assertEqual(self.manager.motion_state, MotionState.IDLE)
        self.assertEqual(len(self.manager.detected_patterns), 0)
        
        # Check that the interface is initialized in the init method
        self.assertIsNotNone(self.manager.interface)
    
    def test_read_sensor_data(self):
        """Test reading sensor data."""
        data = self.manager.read_sensor_data()
        
        # Verify data structure
        self.assertIn('acceleration', data)
        self.assertIn('linear_acceleration', data)
        self.assertIn('gyro', data)
        self.assertIn('heading', data)  # Calculated from rotation vector
        
        # Check that motion history is updated
        self.assertTrue(len(self.manager.motion_history) > 0)
    
    def test_check_arc_swing_pattern(self):
        """Test arc swing pattern detection."""
        # This specifically tests the method that was causing errors
        result = self.manager._check_arc_swing_pattern()
        
        # We're not testing the logic, just that it doesn't crash
        self.assertIsInstance(result, bool)
    
    def test_check_rolling_pattern(self):
        """Test rolling pattern detection."""
        # First set the motion state to ROLLING to test that branch
        self.manager.motion_state = MotionState.ROLLING
        self.manager.rolling_start_time = time.time() - 1.0  # Started 1 second ago
        
        # This specifically tests the method that was causing errors
        result = self.manager._check_rolling_pattern()
        
        # We're not testing the logic, just that it doesn't crash
        self.assertIsInstance(result, bool)
    
    def test_check_throw_pattern(self):
        """Test throw pattern detection."""
        # Set the motion state to FREE_FALL to test that branch
        self.manager.motion_state = MotionState.FREE_FALL
        self.manager.free_fall_start_time = time.time() - 0.2  # Started 0.2 seconds ago
        
        # This specifically tests the method that was causing errors
        result = self.manager._check_throw_pattern()
        
        # We're not testing the logic, just that it doesn't crash
        self.assertIsInstance(result, bool)
    
    def test_check_shake_pattern(self):
        """Test shake pattern detection."""
        # This specifically tests the method that was causing errors
        result = self.manager._check_shake_pattern()
        
        # We're not testing the logic, just that it doesn't crash
        self.assertIsInstance(result, bool)
    
    def test_detect_motion_patterns_with_missing_data(self):
        """Test motion pattern detection with missing or invalid data."""
        # Create data with missing fields to test robustness
        data = {
            'linear_acceleration': (0.1, 0.2, 0.3),
            'timestamp': time.time()
        }
        
        # Should not raise an exception
        patterns = self.manager._detect_motion_patterns(data)
        
        # Verify the result
        self.assertIsInstance(patterns, list)
    
    def test_detect_motion_patterns_with_invalid_types(self):
        """Test motion pattern detection with invalid data types."""
        # Create data with invalid types for some fields
        data = {
            'linear_acceleration': "not a tuple",
            'gyro': None,
            'game_rotation': {"not": "a tuple"},
            'timestamp': time.time()
        }
        
        # Make sure we have a properly initialized motion_history that can be converted to a list
        if not hasattr(self.manager, 'motion_history') or not isinstance(self.manager.motion_history, deque):
            self.manager.motion_history = deque(maxlen=20)
        
        # Should not raise an exception
        patterns = self.manager._detect_motion_patterns(data)
        
        # Verify the result
        self.assertIsInstance(patterns, list)

if __name__ == "__main__":
    unittest.main() 