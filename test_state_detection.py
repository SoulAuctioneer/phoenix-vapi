#!/usr/bin/env python3
"""
Test script for state detection logic without hardware dependencies.
"""

import sys
import os
import time
from math import sqrt

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

# Mock the hardware module to avoid import errors
class MockBNO085Interface:
    async def initialize(self):
        return True
    
    def deinitialize(self):
        pass
    
    async def read_sensor_data(self):
        return {}

# Replace the hardware import
sys.modules['hardware.acc_bno085'] = type('MockModule', (), {'BNO085Interface': MockBNO085Interface})()

from managers.accelerometer_manager import AccelerometerManager, SimplifiedState

def test_state_detection():
    """Test the state detection logic with simulated data."""
    
    # Create manager instance
    manager = AccelerometerManager()
    
    # Override the interface with our mock
    manager.interface = MockBNO085Interface()
    
    print("Testing state detection logic...")
    print("=" * 50)
    
    # Test case 1: Device sitting still on table
    print("\nTest 1: Device sitting still on table")
    test_data = {
        'acceleration': (0.1, 0.2, 9.8),      # Raw accel with gravity
        'linear_acceleration': (0.05, 0.03, 0.02),  # Very low linear accel
        'gyro': (0.01, 0.02, 0.01),           # Very low rotation
        'rot_speed': 0.02,                     # Very low quaternion rotation
        'timestamp': time.time()
    }
    
    # Simulate multiple readings
    for i in range(10):
        manager._update_motion_history(test_data)
        state = manager._determine_current_state(test_data)
        print(f"Reading {i+1}: {state.name}")
        test_data['timestamp'] += 0.05  # 50ms intervals
        time.sleep(0.01)  # Small delay to simulate real timing
    
    # Test case 2: Device with slight hand tremor
    print("\nTest 2: Device held with slight hand tremor")
    test_data = {
        'acceleration': (0.5, 0.6, 9.4),      # Raw accel with gravity + slight movement
        'linear_acceleration': (0.3, 0.25, 0.2),  # Higher linear accel (above STATIONARY threshold)
        'gyro': (0.09, 0.11, 0.08),           # Slightly higher rotation
        'rot_speed': 0.10,                     # Slightly higher quaternion rotation
        'timestamp': time.time()
    }
    
    for i in range(10):
        manager._update_motion_history(test_data)
        state = manager._determine_current_state(test_data)
        print(f"Reading {i+1}: {state.name}")
        test_data['timestamp'] += 0.05
        time.sleep(0.01)
    
    # Test case 3: Device in motion
    print("\nTest 3: Device in motion")
    test_data = {
        'acceleration': (2.0, 3.0, 8.0),      # Raw accel with significant movement
        'linear_acceleration': (1.5, 2.0, 1.0),  # High linear accel
        'gyro': (0.5, 0.8, 0.3),              # Significant rotation
        'rot_speed': 0.6,                      # Significant quaternion rotation
        'timestamp': time.time()
    }
    
    for i in range(10):
        manager._update_motion_history(test_data)
        state = manager._determine_current_state(test_data)
        print(f"Reading {i+1}: {state.name}")
        test_data['timestamp'] += 0.05
        time.sleep(0.01)
    
    print("\n" + "=" * 50)
    print("Test completed!")

if __name__ == "__main__":
    test_state_detection() 