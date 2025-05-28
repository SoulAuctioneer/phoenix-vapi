#!/usr/bin/env python3
"""
Verbose debug script for state detection to understand why transitions are blocked.
"""

import sys
import os
import time
import asyncio
import statistics
import logging

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from managers.accelerometer_manager import AccelerometerManager, SimplifiedState

# Enable debug logging
logging.basicConfig(level=logging.DEBUG, format='%(levelname)s - %(message)s')

async def test_state_detection_debug_verbose():
    """Debug test with verbose output."""
    
    manager = AccelerometerManager()
    
    print("=== Verbose State Detection Debug ===")
    print(f"Key parameters:")
    print(f"  stationary_min_duration: {manager.stationary_min_duration}s")
    print(f"  min_state_duration: {manager.min_state_duration}s") 
    print(f"  HELD_STILL→STATIONARY transition time: 0.8s")
    print()
    
    # Initialize the manager
    if not await manager.initialize():
        print("Failed to initialize accelerometer")
        return
    
    print("Starting test...")
    print("Press Ctrl+C to stop\n")
    
    start_time = time.time()
    last_state = None
    state_start_time = None
    last_candidate = None
    candidate_start_time = None
    
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
            
            # Show info every 0.5 seconds
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
                
                # Check what candidate state would be
                candidate_state = manager._determine_stable_state(
                    linear_mag, gyro_mag, 0.0, current_state
                )
                
                # Track candidate changes
                if candidate_state != last_candidate:
                    if last_candidate is not None:
                        print(f"  → Candidate changed: {last_candidate.name} → {candidate_state.name}")
                    last_candidate = candidate_state
                    candidate_start_time = current_time
                
                # Build status
                status = f"[{elapsed:6.1f}s] {current_state.name}: L={linear_mag:.3f}, G={gyro_mag:.3f}"
                
                # Show candidate info
                if candidate_state != current_state:
                    if candidate_start_time:
                        cand_duration = current_time - candidate_start_time
                        status += f" | Want: {candidate_state.name} ({cand_duration:.1f}s)"
                    else:
                        status += f" | Want: {candidate_state.name}"
                
                # Show stationary tracking
                if manager.stationary_candidate_start is not None:
                    stat_duration = current_time - manager.stationary_candidate_start
                    readings_count = len(manager.stationary_candidate_readings)
                    status += f" | STAT: {stat_duration:.1f}s, {readings_count} readings"
                    
                    if readings_count >= 3:
                        recent = list(manager.stationary_candidate_readings)[-4:]
                        if len(recent) >= 3:
                            try:
                                var = statistics.variance(recent)
                                status += f", Var={var:.4f}"
                            except:
                                pass
                
                # Show time in current state
                if state_start_time:
                    state_duration = current_time - state_start_time
                    status += f" | In state: {state_duration:.1f}s"
                
                print(status)
            
            # Small delay
            await asyncio.sleep(0.05)
            
    except KeyboardInterrupt:
        print("\nTest stopped by user")
    finally:
        manager.deinitialize()
        print("Test complete")

if __name__ == "__main__":
    asyncio.run(test_state_detection_debug_verbose()) 