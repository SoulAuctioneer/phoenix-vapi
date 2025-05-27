#!/usr/bin/env python3
"""
Optimized debug script for free fall detection.
Focuses on performance with minimal console output and timing diagnostics.
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

async def debug_freefall_optimized():
    """Optimized debug function with minimal output and timing diagnostics."""
    
    # Initialize the accelerometer manager
    accel_manager = AccelerometerManager()
    
    try:
        # Initialize the sensor
        print("Initializing accelerometer...")
        init_start = time.perf_counter()
        if not await accel_manager.initialize():
            print("Failed to initialize accelerometer!")
            return
        init_time = time.perf_counter() - init_start
        
        print(f"Accelerometer initialized successfully! (took {init_time*1000:.1f}ms)")
        print(f"Free Fall Thresholds: Accel<{accel_manager.free_fall_accel_threshold:.1f} m/s², Gyro>{accel_manager.free_fall_min_rotation:.1f} rad/s")
        print(f"State Thresholds:")
        print(f"  STATIONARY: Linear<{accel_manager.stationary_linear_accel_max:.2f} m/s², Gyro<{accel_manager.stationary_gyro_max:.2f} rad/s")
        print(f"  HELD_STILL: Linear<{accel_manager.held_still_linear_accel_max:.2f} m/s², Gyro<{accel_manager.held_still_gyro_max:.2f} rad/s")
        print(f"  Hysteresis Factor: {accel_manager.hysteresis_factor:.1f}x")
        print("Monitoring... (Press Ctrl+C to stop)")
        print("Output format: [Sample] Time(ms) | State     | Raw(m/s²) | Linear(m/s²) | Gyro(rad/s) | Read(ms) | Calc(ms) | Total(ms) | Alerts")
        
        # Monitor loop with timing diagnostics
        sample_count = 0
        last_time = time.perf_counter()
        last_state = "UNKNOWN"
        
        # Timing accumulators for averages
        read_times = []
        calc_times = []
        total_times = []
        
        while True:
            try:
                loop_start = time.perf_counter()
                
                # Time the sensor data reading
                read_start = time.perf_counter()
                data = await accel_manager.read_sensor_data()
                read_end = time.perf_counter()
                read_time_ms = (read_end - read_start) * 1000
                
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
                    sample_count % 50 == 0 or
                    current_state == "FREE_FALL"
                )
                
                if should_print:
                    alert = ""
                    if current_state == "FREE_FALL":
                        alert = "🚨 FREE_FALL!"
                    elif current_state != last_state:
                        alert = f"State: {last_state} → {current_state}"
                    
                    # Calculate average timings
                    avg_read = sum(read_times) / len(read_times) if read_times else 0
                    avg_calc = sum(calc_times) / len(calc_times) if calc_times else 0
                    avg_total = sum(total_times) / len(total_times) if total_times else 0
                    
                    print(f"               [{sample_count:4d}]  {ms_since_last:5.1f}ms | {current_state:10s} | {raw_accel_mag:5.1f} | {linear_accel_mag:5.2f} | {gyro_mag:5.2f} | {avg_read:4.1f} | {avg_calc:4.1f} | {avg_total:4.1f} | {alert}")
                
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
        # Clean up
        print("Cleaning up...")
        accel_manager.deinitialize()

if __name__ == "__main__":
    try:
        asyncio.run(debug_freefall_optimized())
    except KeyboardInterrupt:
        print("\nStopped by user")
    except Exception as e:
        logger.error(f"Unexpected error: {e}") 