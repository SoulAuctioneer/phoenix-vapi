#!/usr/bin/env python3
"""
Debug test script to show variance calculations for HELD_STILL to STATIONARY transitions.
"""

import sys
import os
import time
import asyncio
import statistics

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from managers.accelerometer_manager import AccelerometerManager, SimplifiedState

async def test_held_still_to_stationary_debug():
    """Test the transition from HELD_STILL to STATIONARY state with debug info."""
    
    manager = AccelerometerManager()
    
    print("=== HELD_STILL to STATIONARY Debug Test ===")
    print(f"STATIONARY thresholds:")
    print(f"  Linear: < {manager.stationary_linear_accel_max:.3f} m/s²")
    print(f"  Gyro: < {manager.stationary_gyro_max:.3f} rad/s")
    print(f"  Min duration: {manager.stationary_min_duration:.1f}s")
    print(f"  Required consistency: {manager.stationary_consistency_required} samples")
    print(f"  Max variance: {manager.stationary_max_variance:.3f}")
    print(f"  Variance timeout: 8.0s")
    print()
    
    # Initialize the manager
    if not await manager.initialize():
        print("Failed to initialize accelerometer")
        return
    
    print("Starting test - hold device still, then place on table...")
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
            
            # Show detailed info every 1 second
            if int(elapsed * 10) % 10 == 0:
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
                
                # Check stationary candidate tracking and variance
                candidate_info = ""
                variance_info = ""
                if manager.stationary_candidate_start is not None:
                    candidate_duration = current_time - manager.stationary_candidate_start
                    candidate_info = f", STAT candidate: {candidate_duration:.1f}s"
                    
                    # Calculate variance if we have enough readings
                    if len(manager.stationary_candidate_readings) >= 3:
                        recent_readings = list(manager.stationary_candidate_readings)[-manager.stationary_consistency_required:]
                        if len(recent_readings) >= 3:
                            try:
                                variance = statistics.variance(recent_readings)
                                variance_info = f", Variance: {variance:.4f}"
                                
                                # Show if variance would cause rejection
                                if variance > manager.stationary_max_variance:
                                    if candidate_duration > 8.0:
                                        variance_info += " (WILL REJECT!)"
                                    else:
                                        variance_info += f" (high, but only {candidate_duration:.1f}s)"
                            except:
                                pass
                
                print(f"[{elapsed:6.1f}s] {current_state.name}: Linear={linear_mag:.3f}, Gyro={gyro_mag:.3f}, "
                      f"Meets STAT={meets_stationary}{candidate_info}{variance_info}")
                
                # Show the actual readings in the buffer
                if manager.stationary_candidate_readings and len(manager.stationary_candidate_readings) >= 3:
                    recent = list(manager.stationary_candidate_readings)[-5:]
                    readings_str = ", ".join([f"{r:.3f}" for r in recent])
                    print(f"          Recent readings: [{readings_str}]")
            
            # Small delay to not overwhelm the system
            await asyncio.sleep(0.05)
            
    except KeyboardInterrupt:
        print("\nTest stopped by user")
    finally:
        manager.deinitialize()
        print("Test complete")

if __name__ == "__main__":
    asyncio.run(test_held_still_to_stationary_debug()) 