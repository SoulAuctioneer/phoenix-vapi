#!/usr/bin/env python3
"""
Test script for free fall priority over shake detection.
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

def test_freefall_priority():
    """Test that FREE_FALL has priority over SHAKE detection."""
    
    # Create manager instance
    manager = AccelerometerManager()
    
    # Override the interface with our mock
    manager.interface = MockBNO085Interface()
    
    print("Testing FREE_FALL priority over SHAKE...")
    print("=" * 50)
    
    # Scenario: Device in SHAKE state, then thrown (should detect FREE_FALL)
    print("\nScenario: Device shaking, then thrown in air")
    
    # Step 1: Put device in SHAKE state
    shake_data = {
        'acceleration': (15.0, 12.0, 8.0),     # High raw acceleration
        'linear_acceleration': (8.0, 6.0, 4.0), # High linear acceleration (shake)
        'gyro': (2.0, 1.5, 1.0),               # Moderate rotation
        'rot_speed': 1.2,                       # Moderate quaternion rotation
        'shake': True,                          # BNO reports shake
        'timestamp': time.time()
    }
    
    # Build up shake history
    for i in range(35):  # More than shake_history_size (30)
        manager._update_motion_history(shake_data)
        state = manager._determine_current_state(shake_data)
        if i == 0 or i == 34:
            print(f"Shake reading {i+1}: {state.name}")
        shake_data['timestamp'] += 0.01
    
    # Step 2: Throw device (should detect FREE_FALL despite being in SHAKE)
    freefall_data = {
        'acceleration': (1.5, 1.2, 0.8),       # Very low raw acceleration (weightless)
        'linear_acceleration': (0.8, 0.6, 0.4), # Low linear acceleration
        'gyro': (5.0, 4.0, 3.0),               # High rotation (tumbling)
        'rot_speed': 4.5,                       # High quaternion rotation
        'shake': False,                         # No shake reported
        'timestamp': time.time()
    }
    
    print(f"\nThrowing device (FREE_FALL conditions):")
    for i in range(10):
        manager._update_motion_history(freefall_data)
        state = manager._determine_current_state(freefall_data)
        print(f"Throw reading {i+1}: {state.name} (Raw: {sqrt(sum(x*x for x in freefall_data['acceleration'])):.1f} m/s², Gyro: {sqrt(sum(x*x for x in freefall_data['gyro'])):.1f} rad/s)")
        freefall_data['timestamp'] += 0.01
        time.sleep(0.01)
    
    # Step 3: Impact
    impact_data = {
        'acceleration': (25.0, 20.0, 15.0),    # Very high raw acceleration
        'linear_acceleration': (18.0, 15.0, 12.0), # Very high linear acceleration
        'gyro': (1.0, 0.8, 0.6),               # Lower rotation after impact
        'rot_speed': 0.8,                       # Lower quaternion rotation
        'shake': False,
        'timestamp': time.time()
    }
    
    print(f"\nImpact:")
    manager._update_motion_history(impact_data)
    state = manager._determine_current_state(impact_data)
    print(f"Impact reading: {state.name} (Linear: {sqrt(sum(x*x for x in impact_data['linear_acceleration'])):.1f} m/s²)")
    
    # Step 4: Test second throw (should work even after first throw)
    print(f"\nSecond throw (should also detect FREE_FALL):")
    freefall_data['timestamp'] = time.time()
    
    for i in range(10):
        manager._update_motion_history(freefall_data)
        state = manager._determine_current_state(freefall_data)
        print(f"Second throw reading {i+1}: {state.name}")
        freefall_data['timestamp'] += 0.01
        time.sleep(0.01)
    
    print("\n" + "=" * 50)
    print("Priority test completed!")

if __name__ == "__main__":
    test_freefall_priority() 