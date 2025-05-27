#!/usr/bin/env python3
"""
Ultra-optimized debug script for free fall detection.
Uses only essential sensors (acceleration, linear_acceleration, gyro) for maximum performance.
"""

import asyncio
import sys
import os
import logging
import time

# Add the src directory to the path so we can import our modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from managers.accelerometer_manager import AccelerometerManager, SimplifiedState
from math import sqrt

# Set up minimal logging
logging.basicConfig(level=logging.WARNING, format='%(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Enable logging for the hardware interface to see timing warnings
hardware_logger = logging.getLogger('hardware.acc_bno085')
hardware_logger.setLevel(logging.WARNING)

# Enable debug logging for the accelerometer manager to see state transitions
accel_logger = logging.getLogger('managers.accelerometer_manager')
accel_logger.setLevel(logging.DEBUG)

async def debug_freefall_ultra_optimized():
    """Ultra-optimized debug function with only essential sensors."""
    
    # Initialize the accelerometer manager
    accel_manager = AccelerometerManager()
    
    try:
        # Initialize the sensor
        print("Initializing accelerometer with ultra-optimized configuration...")
        init_start = time.perf_counter()
        if not await accel_manager.initialize():
            print("Failed to initialize accelerometer!")
            return
        init_time = time.perf_counter() - init_start
        
        print(f"Accelerometer initialized successfully! (took {init_time*1000:.1f}ms)")
        print("ULTRA-OPTIMIZED MODE: Only 3 essential sensors enabled")
        print("- Raw acceleration (for total magnitude)")
        print("- Linear acceleration (motion without gravity)")  
        print("- Gyroscope (rotation detection)")
        print()
        print(f"Free Fall Thresholds: Accel<{accel_manager.free_fall_accel_threshold:.1f} m/s², Gyro>{accel_manager.free_fall_min_rotation:.1f}-{accel_manager.free_fall_max_rotation:.1f} rad/s, Linear<{accel_manager.free_fall_linear_accel_max:.1f} m/s²")
        print(f"Free Fall Duration: Min={accel_manager.free_fall_min_duration*1000:.0f}ms, Consistency={accel_manager.free_fall_accel_consistency_samples} samples")
        print(f"State Thresholds (ANTI-OSCILLATION):")
        print(f"  STATIONARY: Linear<{accel_manager.stationary_linear_accel_max:.2f} m/s², Gyro<{accel_manager.stationary_gyro_max:.2f} rad/s")
        print(f"  HELD_STILL: Linear<{accel_manager.held_still_linear_accel_max:.2f} m/s², Gyro<{accel_manager.held_still_gyro_max:.2f} rad/s")
        print(f"  Hysteresis Factor: {accel_manager.hysteresis_factor:.1f}x (stronger separation)")
        print(f"  Min State Duration: {accel_manager.min_state_duration:.1f}s (2x longer for STAT↔HELD transitions)")
        print("  Note: STATIONARY thresholds adjusted for observed sensor noise when completely still")
        print("Monitoring... (Press Ctrl+C to stop)")
        print("Output format: [Sample] Time(ms) | State      | Raw(m/s²) | Linear(m/s²) | Gyro(rad/s) | Read(ms) | Calc(ms) | Total(ms) | Alerts")
        
        # Monitor loop with timing diagnostics
        sample_count = 0
        last_time = time.perf_counter()
        last_state = "UNKNOWN"
        
        # Timing accumulators for averages
        read_times = []
        calc_times = []
        total_times = []
        
        # Performance tracking
        min_read_time = float('inf')
        max_read_time = 0
        
        while True:
            try:
                loop_start = time.perf_counter()
                
                # Time the sensor data reading
                read_start = time.perf_counter()
                data = await accel_manager.read_sensor_data()
                read_end = time.perf_counter()
                read_time_ms = (read_end - read_start) * 1000
                
                # Track min/max read times
                min_read_time = min(min_read_time, read_time_ms)
                max_read_time = max(max_read_time, read_time_ms)
                
                # Time the calculations (already done in read_sensor_data, but measure other processing)
                calc_start = time.perf_counter()
                sample_count += 1
                current_time = time.perf_counter()
                ms_since_last = (current_time - last_time) * 1000
                last_time = current_time

                # Extract only essential values
                raw_accel = data.get("acceleration", (0, 0, 0))
                linear_accel = data.get("linear_acceleration", (0, 0, 0))
                gyro = data.get("gyro", (0, 0, 0))
                current_state = data.get("current_state", "UNKNOWN")
                
                # Fast magnitude calculations
                raw_accel_mag = sqrt(raw_accel[0]**2 + raw_accel[1]**2 + raw_accel[2]**2)
                linear_accel_mag = sqrt(linear_accel[0]**2 + linear_accel[1]**2 + linear_accel[2]**2)
                gyro_mag = sqrt(gyro[0]**2 + gyro[1]**2 + gyro[2]**2)
                
                calc_end = time.perf_counter()
                calc_time_ms = (calc_end - calc_start) * 1000
                
                loop_end = time.perf_counter()
                total_time_ms = (loop_end - loop_start) * 1000
                
                # Store timing data for averages
                read_times.append(read_time_ms)
                calc_times.append(calc_time_ms)
                total_times.append(total_time_ms)
                
                # Keep only last 100 samples for rolling average
                if len(read_times) > 100:
                    read_times.pop(0)
                    calc_times.pop(0)
                    total_times.pop(0)
                
                # Only print on state changes or every 50 samples or alerts
                should_print = (
                    current_state != last_state or 
                    current_state == "FREE_FALL" or
                    sample_count % 1000 == 0  # Performance summary every 1000 samples
                )
                
                # Also print diagnostic info for potential false positives
                # (movements that might be confused with free fall)
                is_potential_false_positive = (
                    current_state == "MOVING" and
                    raw_accel_mag < 8.0 and  # Low-ish acceleration
                    gyro_mag > 1.0 and       # Some rotation
                    linear_accel_mag > 1.0   # But significant linear motion
                )
                
                if should_print or is_potential_false_positive:
                    alert = ""
                    if current_state == "FREE_FALL":
                        alert = "🚨 FREE_FALL!"
                    elif current_state != last_state:
                        alert = f"State: {last_state} → {current_state}"
                    elif sample_count % 1000 == 0:
                        # Performance summary
                        avg_read = sum(read_times) / len(read_times) if read_times else 0
                        alert = f"PERF: Min={min_read_time:.1f}ms, Max={max_read_time:.1f}ms, Avg={avg_read:.1f}ms"
                    elif is_potential_false_positive:
                        # Show why this movement doesn't trigger free fall
                        meets_accel = raw_accel_mag < accel_manager.free_fall_accel_threshold
                        meets_gyro = (gyro_mag > accel_manager.free_fall_min_rotation and 
                                     gyro_mag < accel_manager.free_fall_max_rotation)
                        meets_linear = linear_accel_mag < accel_manager.free_fall_linear_accel_max
                        alert = f"NOT FREE_FALL: Accel={meets_accel}, Gyro={meets_gyro}, Linear={meets_linear}"
                    
                    # Calculate average timings
                    avg_read = sum(read_times) / len(read_times) if read_times else 0
                    avg_calc = sum(calc_times) / len(calc_times) if calc_times else 0
                    avg_total = sum(total_times) / len(total_times) if total_times else 0
                    
                    print(f"               [{sample_count:4d}]    {ms_since_last:5.1f}ms | {current_state:10s} |     {raw_accel_mag:5.1f} |        {linear_accel_mag:5.2f} |       {gyro_mag:5.2f} |     {avg_read:4.1f} |     {avg_calc:4.1f} |      {avg_total:4.1f} | {alert}")
                    
                    # Show detailed timing breakdown for optimized version
                    # if '_timing' in data:
                    #     timing = data['_timing']
                    #     print(f"                      OPTIMIZED TIMING: Batch={timing.get('batch_read_ms', 0):.1f}ms, Thread={timing.get('thread_overhead_ms', 0):.1f}ms, Extract={timing.get('extract_ms', 0):.1f}ms")
                        
                    #     # Show individual sensor timings if available
                    #     individual = timing.get('individual_sensors', {})
                    #     if individual:
                    #         sensor_times = ", ".join([f"{k.replace('_ms', '')}={v:.1f}" for k, v in individual.items()])
                    #         print(f"                      SENSOR TIMINGS (3 only): {sensor_times}")
                    
                    # Show state diagnostics for oscillating states (when device should be stationary)
                    if current_state != last_state and linear_accel_mag < 0.1 and gyro_mag < 0.1:
                        rot_speed = data.get("rot_speed", 0.0)
                        print(f"                      STATE DEBUG: Linear={linear_accel_mag:.3f} (thresh: STAT={accel_manager.stationary_linear_accel_max:.2f}, HELD={accel_manager.held_still_linear_accel_max:.2f})")
                        print(f"                                   Gyro={gyro_mag:.3f} (thresh: STAT={accel_manager.stationary_gyro_max:.2f}, HELD={accel_manager.held_still_gyro_max:.2f})")
                        print(f"                                   RotSpeed={rot_speed:.3f} (thresh: STAT={accel_manager.stationary_rot_speed_max:.2f}, HELD={accel_manager.held_still_rot_speed_max:.2f})")
                        print(f"                                   MinStateDuration={accel_manager.min_state_duration:.1f}s, Hysteresis={accel_manager.hysteresis_factor:.1f}x")
                
                last_state = current_state
                
                # Minimal delay to prevent overwhelming the system
                if total_time_ms < 5:  # If we're going too fast, add tiny delay
                    await asyncio.sleep(0.001)
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(0.1)
                
    except Exception as e:
        logger.error(f"Error in debug function: {e}")
    finally:
        # Clean up and show final performance stats
        print("\nCleaning up...")
        if read_times:
            avg_read = sum(read_times) / len(read_times)
            print(f"Final Performance Stats:")
            print(f"  Samples: {sample_count}")
            print(f"  Read Time - Min: {min_read_time:.1f}ms, Max: {max_read_time:.1f}ms, Avg: {avg_read:.1f}ms")
            print(f"  Performance improvement vs 20ms target: {((20 - avg_read) / 20 * 100):.1f}%")
        accel_manager.deinitialize()

if __name__ == "__main__":
    try:
        asyncio.run(debug_freefall_ultra_optimized())
    except KeyboardInterrupt:
        print("\nStopped by user")
    except Exception as e:
        logger.error(f"Unexpected error: {e}") 