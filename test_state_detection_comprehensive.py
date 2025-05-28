#!/usr/bin/env python3
"""
Comprehensive test script for state detection logic.
"""

import sys
import os
import time
import asyncio
import statistics

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from managers.accelerometer_manager import AccelerometerManager, SimplifiedState

async def test_state_detection_comprehensive():
    """Comprehensive test of state detection logic."""
    
    manager = AccelerometerManager()
    
    print("=== Comprehensive State Detection Test ===")
    print(f"STATIONARY thresholds:")
    print(f"  Linear: < {manager.stationary_linear_accel_max:.3f} m/s²")
    print(f"  Gyro: < {manager.stationary_gyro_max:.3f} rad/s")
    print(f"  Exit hysteresis: {manager.stationary_exit_hysteresis}x")
    print(f"HELD_STILL thresholds:")
    print(f"  Linear: < {manager.held_still_linear_accel_max:.3f} m/s²")
    print(f"  Gyro: < {manager.held_still_gyro_max:.3f} rad/s")
    print(f"  Exit hysteresis: {manager.hysteresis_factor}x")
    print()
    
    # Initialize the manager
    if not await manager.initialize():
        print("Failed to initialize accelerometer")
        return
    
    print("Starting test - try different movements...")
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
                    print(f"\n[{elapsed:6.1f}s] State change: {last_state.name} → {current_state.name} (was in {last_state.name} for {duration:.1f}s)")
                else:
                    print(f"[{elapsed:6.1f}s] Initial state: {current_state.name}")
                
                last_state = current_state
                state_start_time = current_time
            
            # Show detailed info every 0.5 seconds
            if int(elapsed * 20) % 10 == 0:  # Every 0.5s
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
                
                # Calculate thresholds based on current state
                if current_state == SimplifiedState.STATIONARY:
                    stat_linear_thresh = manager.stationary_linear_accel_max * manager.stationary_exit_hysteresis
                    stat_gyro_thresh = manager.stationary_gyro_max * manager.stationary_exit_hysteresis
                elif current_state == SimplifiedState.HELD_STILL:
                    stat_linear_thresh = manager.stationary_linear_accel_max
                    stat_gyro_thresh = manager.stationary_gyro_max
                else:
                    stat_linear_thresh = manager.stationary_linear_accel_max
                    stat_gyro_thresh = manager.stationary_gyro_max
                
                # Check if we meet basic STATIONARY criteria
                meets_stationary = (linear_mag < stat_linear_thresh and gyro_mag < stat_gyro_thresh)
                
                # Build status string
                status = f"[{elapsed:6.1f}s] {current_state.name}: L={linear_mag:.3f}"
                if linear_mag >= stat_linear_thresh:
                    status += f"(>{stat_linear_thresh:.3f})"
                status += f", G={gyro_mag:.3f}"
                if gyro_mag >= stat_gyro_thresh:
                    status += f"(>{stat_gyro_thresh:.3f})"
                
                # Show candidate tracking
                if manager.stationary_candidate_start is not None:
                    candidate_duration = current_time - manager.stationary_candidate_start
                    status += f", STAT cand: {candidate_duration:.1f}s"
                    
                    # Show readings count
                    readings_count = len(manager.stationary_candidate_readings)
                    status += f" ({readings_count} readings)"
                    
                    # Calculate variance if possible
                    if readings_count >= 3:
                        recent = list(manager.stationary_candidate_readings)[-4:]
                        if len(recent) >= 3:
                            try:
                                var = statistics.variance(recent)
                                status += f", Var: {var:.4f}"
                            except:
                                pass
                elif meets_stationary:
                    status += " (meets STAT but no candidate)"
                
                print(status)
            
            # Small delay to not overwhelm the system
            await asyncio.sleep(0.05)
            
    except KeyboardInterrupt:
        print("\nTest stopped by user")
    finally:
        manager.deinitialize()
        print("Test complete")

if __name__ == "__main__":
    asyncio.run(test_state_detection_comprehensive()) 