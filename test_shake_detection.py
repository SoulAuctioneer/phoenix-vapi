#!/usr/bin/env python3
"""
Test script for shake detection logic without hardware dependencies.
"""

import sys
import os
from math import sqrt
import statistics
from typing import List

# Mock the hardware module to avoid import errors
class MockBNO085Interface:
    def __init__(self):
        pass
    
    async def initialize(self):
        return True
    
    def deinitialize(self):
        pass
    
    async def read_sensor_data_optimized(self):
        return {}

# Mock the config module
class MockMoveActivityConfig:
    ACCEL_WEIGHT = 0.7
    GYRO_WEIGHT = 0.2
    ROT_WEIGHT = 0.1

# Patch the imports before importing our module
sys.modules['hardware.acc_bno085'] = type('MockModule', (), {'BNO085Interface': MockBNO085Interface})()
sys.modules['config'] = type('MockModule', (), {'MoveActivityConfig': MockMoveActivityConfig})()

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

# Now import our module
from managers.accelerometer_manager import AccelerometerManager

def test_acceleration_reversals():
    """Test the acceleration reversal detection logic."""
    
    manager = AccelerometerManager()
    
    # Test case 1: No reversals (steady increase)
    steady_increase = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    reversals = manager._count_acceleration_reversals(steady_increase)
    print(f"Test 1 - Steady increase: {reversals} reversals (expected: 0)")
    
    # Test case 2: One clear reversal (up then down)
    one_reversal = [1.0, 2.0, 4.0, 6.0, 4.0, 2.0, 1.0]
    reversals = manager._count_acceleration_reversals(one_reversal)
    print(f"Test 2 - One reversal: {reversals} reversals (expected: 1)")
    
    # Test case 3: Multiple reversals (shake-like pattern)
    shake_pattern = [2.0, 5.0, 8.0, 4.0, 1.0, 6.0, 9.0, 3.0, 1.0, 7.0]
    reversals = manager._count_acceleration_reversals(shake_pattern)
    print(f"Test 3 - Shake pattern: {reversals} reversals (expected: 3-4)")
    
    # Test case 4: Small fluctuations (should not count as reversals)
    small_fluctuations = [3.0, 3.2, 2.8, 3.1, 2.9, 3.0, 3.3, 2.7]
    reversals = manager._count_acceleration_reversals(small_fluctuations)
    print(f"Test 4 - Small fluctuations: {reversals} reversals (expected: 0)")
    
    # Test case 5: Large shake with many reversals
    large_shake = [1.0, 8.0, 2.0, 9.0, 1.5, 7.0, 3.0, 10.0, 2.0, 6.0, 1.0]
    reversals = manager._count_acceleration_reversals(large_shake)
    print(f"Test 5 - Large shake: {reversals} reversals (expected: 5-6)")

def test_shake_detection_thresholds():
    """Test the shake detection with different threshold values."""
    
    manager = AccelerometerManager()
    
    print(f"\nCurrent shake detection thresholds:")
    print(f"  shake_history_size: {manager.shake_history_size}")
    print(f"  peak_magnitude_for_shake: {manager.peak_magnitude_for_shake} m/s²")
    print(f"  min_magnitude_for_shake: {manager.min_magnitude_for_shake} m/s²")
    print(f"  min_accel_reversals_for_shake: {manager.min_accel_reversals_for_shake}")
    
    # Create mock motion history with different patterns
    
    # Pattern 1: High peak, high average, many reversals (should detect shake)
    strong_shake_data = []
    for i in range(manager.shake_history_size):
        if i % 4 == 0:
            accel = (12.0, 0.0, 0.0)  # High peak
        elif i % 4 == 2:
            accel = (2.0, 0.0, 0.0)   # Low valley
        else:
            accel = (6.0, 0.0, 0.0)   # Medium
        strong_shake_data.append({"linear_acceleration": accel})
    
    manager.motion_history.clear()
    manager.motion_history.extend(strong_shake_data)
    result1 = manager._check_shake()
    print(f"\nPattern 1 - Strong shake: {result1} (expected: True)")
    
    # Pattern 2: Low peak (should not detect shake)
    weak_shake_data = []
    for i in range(manager.shake_history_size):
        if i % 4 == 0:
            accel = (5.0, 0.0, 0.0)   # Below peak threshold
        elif i % 4 == 2:
            accel = (1.0, 0.0, 0.0)   # Low valley
        else:
            accel = (3.0, 0.0, 0.0)   # Medium
        weak_shake_data.append({"linear_acceleration": accel})
    
    manager.motion_history.clear()
    manager.motion_history.extend(weak_shake_data)
    result2 = manager._check_shake()
    print(f"Pattern 2 - Weak shake: {result2} (expected: False)")
    
    # Pattern 3: High peak but no reversals (should not detect shake)
    no_reversal_data = []
    for i in range(manager.shake_history_size):
        accel = (15.0, 0.0, 0.0)  # High but constant
        no_reversal_data.append({"linear_acceleration": accel})
    
    manager.motion_history.clear()
    manager.motion_history.extend(no_reversal_data)
    result3 = manager._check_shake()
    print(f"Pattern 3 - High but constant: {result3} (expected: False)")
    
    # Pattern 4: High peak, good average, but few reversals
    few_reversals_data = []
    for i in range(manager.shake_history_size):
        if i < 5:
            accel = (15.0, 0.0, 0.0)  # High start
        elif i < 10:
            accel = (2.0, 0.0, 0.0)   # One drop
        else:
            accel = (8.0, 0.0, 0.0)   # Medium rest
        few_reversals_data.append({"linear_acceleration": accel})
    
    manager.motion_history.clear()
    manager.motion_history.extend(few_reversals_data)
    result4 = manager._check_shake()
    print(f"Pattern 4 - Few reversals: {result4} (expected: False)")

if __name__ == "__main__":
    print("Testing shake detection with acceleration reversals...")
    print("=" * 60)
    
    test_acceleration_reversals()
    test_shake_detection_thresholds()
    
    print("\n" + "=" * 60)
    print("Test completed!") 