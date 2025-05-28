#!/usr/bin/env python3
"""
Test script to verify HELD_STILL to STATIONARY transition fix.
This script monitors the accelerometer state and provides detailed logging
to verify that the device can properly transition from HELD_STILL to STATIONARY
when placed on a stable surface.
"""

import asyncio
import time
import logging
from src.managers.accelerometer_manager import AccelerometerManager

# Configure logging to show debug messages
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def test_stationary_transition():
    """Test the HELD_STILL to STATIONARY transition"""
    manager = AccelerometerManager()
    
    # Initialize the accelerometer
    if not await manager.initialize():
        print("Failed to initialize accelerometer")
        return
    
    print("Accelerometer initialized successfully")
    print("\nTest Instructions:")
    print("1. Start with device on table (should detect STATIONARY)")
    print("2. Pick up and hold the device (should detect HELD_STILL)")
    print("3. Move it around a bit (should detect MOVING)")
    print("4. Hold it still again (should detect HELD_STILL)")
    print("5. Place it back on the table (should detect STATIONARY)")
    print("\nStarting test - press Ctrl+C to stop\n")
    
    start_time = time.time()
    last_state = None
    state_start_time = start_time
    
    try:
        while True:
            # Read sensor data
            data = await manager.read_sensor_data()
            current_time = time.time()
            elapsed = current_time - start_time
            
            # Extract key information
            current_state = data.get("current_state", "UNKNOWN")
            linear_accel = data.get("linear_acceleration", (0, 0, 0))
            gyro = data.get("gyro", (0, 0, 0))
            
            # Calculate magnitudes
            linear_mag = (sum(x*x for x in linear_accel) ** 0.5) if isinstance(linear_accel, tuple) else 0
            gyro_mag = (sum(x*x for x in gyro) ** 0.5) if isinstance(gyro, tuple) else 0
            
            # Check if state changed
            if current_state != last_state:
                if last_state is not None:
                    duration = current_time - state_start_time
                    print(f"\n[{elapsed:6.1f}s] State change: {last_state} → {current_state} (was in {last_state} for {duration:.1f}s)")
                else:
                    print(f"[{elapsed:6.1f}s] Initial state: {current_state}")
                last_state = current_state
                state_start_time = current_time
            
            # Show detailed info for stable states
            if current_state in ["STATIONARY", "HELD_STILL"]:
                # Get stationary tracking info
                stat_start = manager.stationary_candidate_start
                stat_readings = len(manager.stationary_candidate_readings)
                
                if stat_start:
                    stat_duration = current_time - stat_start
                    print(f"[{elapsed:6.1f}s] {current_state}: L={linear_mag:.3f}, G={gyro_mag:.3f}, "
                          f"STAT cand: {stat_duration:.1f}s ({stat_readings} readings)", end="")
                    
                    # Show variance if we have enough readings
                    if stat_readings >= 3:
                        import statistics
                        recent_readings = list(manager.stationary_candidate_readings)[-manager.stationary_consistency_required:]
                        if len(recent_readings) >= 3:
                            try:
                                variance = statistics.variance(recent_readings)
                                print(f", Var: {variance:.4f}")
                            except:
                                print()
                    else:
                        print()
                else:
                    # Show why we're not tracking stationary
                    meets_basic = (linear_mag < manager.stationary_linear_accel_max and
                                 gyro_mag < manager.stationary_gyro_max)
                    print(f"[{elapsed:6.1f}s] {current_state}: L={linear_mag:.3f}, G={gyro_mag:.3f} "
                          f"(meets STAT but no candidate)" if meets_basic else 
                          f"[{elapsed:6.1f}s] {current_state}: L={linear_mag:.3f}(>{manager.stationary_linear_accel_max:.3f}), "
                          f"G={gyro_mag:.3f}(>{manager.stationary_gyro_max:.3f})")
            
            # Show movement info
            elif current_state == "MOVING":
                # Show which thresholds are exceeded
                stat_linear_exceeded = linear_mag > manager.stationary_linear_accel_max
                stat_gyro_exceeded = gyro_mag > manager.stationary_gyro_max
                held_linear_exceeded = linear_mag > manager.held_still_linear_accel_max
                held_gyro_exceeded = gyro_mag > manager.held_still_gyro_max
                
                exceeded_info = []
                if held_linear_exceeded:
                    exceeded_info.append(f"L={linear_mag:.3f}(>{manager.held_still_linear_accel_max:.3f})")
                else:
                    exceeded_info.append(f"L={linear_mag:.3f}")
                    
                if held_gyro_exceeded:
                    exceeded_info.append(f"G={gyro_mag:.3f}(>{manager.held_still_gyro_max:.3f})")
                else:
                    exceeded_info.append(f"G={gyro_mag:.3f}")
                
                print(f"[{elapsed:6.1f}s] {current_state}: {', '.join(exceeded_info)}")
            
            # Small delay to avoid overwhelming the output
            await asyncio.sleep(0.5)
            
    except KeyboardInterrupt:
        print("\n\nTest stopped by user")
    finally:
        manager.deinitialize()
        print("Accelerometer deinitialized")

if __name__ == "__main__":
    asyncio.run(test_stationary_transition()) 