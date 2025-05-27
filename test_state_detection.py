#!/usr/bin/env python3
"""
Simple test script to verify the new state detection improvements.
"""

import sys
import os

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from managers.accelerometer_manager import AccelerometerManager, SimplifiedState

def test_state_thresholds():
    """Test the new state detection thresholds."""
    
    manager = AccelerometerManager()
    
    print("=== NEW STATE DETECTION THRESHOLDS ===")
    print(f"STATIONARY (STRICT):")
    print(f"  Linear Accel: < {manager.stationary_linear_accel_max:.3f} m/s²")
    print(f"  Gyro: < {manager.stationary_gyro_max:.3f} rad/s")
    print(f"  Rotation Speed: < {manager.stationary_rot_speed_max:.3f} rad/s")
    print(f"  Consistency: {manager.stationary_consistency_required} samples")
    print(f"  Max Variance: {manager.stationary_max_variance:.3f} m/s²")
    print(f"  Duration: 2.0 seconds")
    print()
    
    print(f"HELD_STILL:")
    print(f"  Linear Accel: < {manager.held_still_linear_accel_max:.2f} m/s²")
    print(f"  Gyro: < {manager.held_still_gyro_max:.2f} rad/s")
    print(f"  Rotation Speed: < {manager.held_still_rot_speed_max:.2f} rad/s")
    print()
    
    print(f"FREE_FALL (STRICT):")
    print(f"  Total Accel: < {manager.free_fall_accel_threshold:.1f} m/s²")
    print(f"  Gyro: {manager.free_fall_min_rotation:.1f} - {manager.free_fall_max_rotation:.1f} rad/s")
    print(f"  Linear Accel: < {manager.free_fall_linear_accel_max:.1f} m/s²")
    print(f"  Min Duration: {manager.free_fall_min_duration*1000:.0f}ms")
    print(f"  Consistency: {manager.free_fall_accel_consistency_samples} samples")
    print()
    
    print("=== TEST CASES ===")
    
    # Test case from user's log that was incorrectly classified as STATIONARY
    print("Test Case 1: User's example (should be HELD_STILL, not STATIONARY)")
    linear_accel = 0.050  # m/s²
    gyro = 0.035         # rad/s
    rot_speed = 0.000    # rad/s
    
    print(f"  Values: Linear={linear_accel:.3f}, Gyro={gyro:.3f}, RotSpeed={rot_speed:.3f}")
    
    # Check against new thresholds
    meets_stationary_basic = (linear_accel < manager.stationary_linear_accel_max and
                             gyro < manager.stationary_gyro_max and
                             rot_speed < manager.stationary_rot_speed_max)
    
    meets_held_still = (linear_accel < manager.held_still_linear_accel_max and
                       gyro < manager.held_still_gyro_max and
                       rot_speed < manager.held_still_rot_speed_max)
    
    print(f"  Meets STATIONARY basic criteria: {meets_stationary_basic}")
    print(f"  Meets HELD_STILL criteria: {meets_held_still}")
    print(f"  Expected classification: {'HELD_STILL' if meets_held_still and not meets_stationary_basic else 'MOVING'}")
    print()
    
    # Test case for gentle arc movement (should NOT trigger free fall)
    print("Test Case 2: Gentle arc movement (should NOT be FREE_FALL)")
    total_accel = 6.5    # m/s²
    linear_accel = 3.2   # m/s²
    gyro = 1.4          # rad/s
    
    print(f"  Values: Total={total_accel:.1f}, Linear={linear_accel:.1f}, Gyro={gyro:.1f}")
    
    meets_ff_accel = total_accel < manager.free_fall_accel_threshold
    meets_ff_gyro = (gyro > manager.free_fall_min_rotation and 
                     gyro < manager.free_fall_max_rotation)
    meets_ff_linear = linear_accel < manager.free_fall_linear_accel_max
    
    print(f"  Meets FREE_FALL total accel: {meets_ff_accel} (< {manager.free_fall_accel_threshold:.1f})")
    print(f"  Meets FREE_FALL gyro range: {meets_ff_gyro} ({manager.free_fall_min_rotation:.1f} - {manager.free_fall_max_rotation:.1f})")
    print(f"  Meets FREE_FALL linear accel: {meets_ff_linear} (< {manager.free_fall_linear_accel_max:.1f})")
    print(f"  Would trigger FREE_FALL: {meets_ff_accel and meets_ff_gyro and meets_ff_linear}")
    print()
    
    # Test case for true free fall
    print("Test Case 3: True free fall (should be FREE_FALL)")
    total_accel = 2.5    # m/s²
    linear_accel = 1.5   # m/s²
    gyro = 4.0          # rad/s
    
    print(f"  Values: Total={total_accel:.1f}, Linear={linear_accel:.1f}, Gyro={gyro:.1f}")
    
    meets_ff_accel = total_accel < manager.free_fall_accel_threshold
    meets_ff_gyro = (gyro > manager.free_fall_min_rotation and 
                     gyro < manager.free_fall_max_rotation)
    meets_ff_linear = linear_accel < manager.free_fall_linear_accel_max
    
    print(f"  Meets FREE_FALL total accel: {meets_ff_accel} (< {manager.free_fall_accel_threshold:.1f})")
    print(f"  Meets FREE_FALL gyro range: {meets_ff_gyro} ({manager.free_fall_min_rotation:.1f} - {manager.free_fall_max_rotation:.1f})")
    print(f"  Meets FREE_FALL linear accel: {meets_ff_linear} (< {manager.free_fall_linear_accel_max:.1f})")
    print(f"  Would trigger FREE_FALL: {meets_ff_accel and meets_ff_gyro and meets_ff_linear}")
    print()

if __name__ == "__main__":
    test_state_thresholds() 