#!/usr/bin/env python3
"""
Test script to verify HELD_STILL to STATIONARY transition issue.
"""

import sys
import os
import time
import asyncio

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from managers.accelerometer_manager import AccelerometerManager, SimplifiedState

async def test_held_still_to_stationary():
    """Test the transition from HELD_STILL to STATIONARY state."""
    
    manager = AccelerometerManager()
    
    print("=== HELD_STILL to STATIONARY Transition Test ===")
    print(f"STATIONARY thresholds:")
    print(f"  Linear: < {manager.stationary_linear_accel_max:.3f} m/s²")
    print(f"  Gyro: < {manager.stationary_gyro_max:.3f} rad/s")
    print(f"  Min duration: {manager.stationary_min_duration:.1f}s")
    print(f"  Required consistency: {manager.stationary_consistency_required} samples")
    print()
    
    # Initialize the manager
    if not await manager.initialize():
        print("Failed to initialize accelerometer")
        return
    
    print("Starting test - place device on table and keep it perfectly still...")
    print("Press Ctrl+C to stop\n")
    
    start_time = time.time()
    last_state = None
    state_start_time = None
    
    try:
        while True:
            # Read sensor data
            data = await manager.read_sensor_data()
            
            current_state = manager.current_state
            current_time = time.time()
            elapsed = current_time - start_time
            
            # Track state changes
            if current_state != last_state:
                if last_state is not None:
                    duration = current_time - state_start_time
                    print(f"[{elapsed:6.1f}s] State change: {last_state.name} → {current_state.name} (was in {last_state.name} for {duration:.1f}s)")
                else:
                    print(f"[{elapsed:6.1f}s] Initial state: {current_state.name}")
                
                last_state = current_state
                state_start_time = current_time
            
            # Show detailed info every 2 seconds
            if int(elapsed) % 2 == 0 and int(elapsed * 10) % 10 == 0:
                linear_accel = data.get("linear_acceleration", (0, 0, 0))
                gyro = data.get("gyro", (0, 0, 0))
                
                if isinstance(linear_accel, tuple) and len(linear_accel) == 3:
                    linear_mag = (sum(x*x for x in linear_accel)) ** 0.5
                else:
                    linear_mag = 0.0
                    
                if isinstance(gyro, tuple) and len(gyro) == 3:
                    gyro_mag = (sum(x*x for x in gyro)) ** 0.5
                else:
                    gyro_mag = 0.0
                
                # Check if we meet basic STATIONARY criteria
                meets_stationary = (linear_mag < manager.stationary_linear_accel_max and
                                  gyro_mag < manager.stationary_gyro_max)
                
                # Check stationary candidate tracking
                candidate_info = ""
                if manager.stationary_candidate_start is not None:
                    candidate_duration = current_time - manager.stationary_candidate_start
                    candidate_info = f", STAT candidate: {candidate_duration:.1f}s"
                
                print(f"[{elapsed:6.1f}s] {current_state.name}: Linear={linear_mag:.3f}, Gyro={gyro_mag:.3f}, "
                      f"Meets STAT={meets_stationary}{candidate_info}")
            
            # Small delay to not overwhelm the system
            await asyncio.sleep(0.05)
            
    except KeyboardInterrupt:
        print("\nTest stopped by user")
    finally:
        manager.deinitialize()
        print("Test complete")

if __name__ == "__main__":
    asyncio.run(test_held_still_to_stationary()) 