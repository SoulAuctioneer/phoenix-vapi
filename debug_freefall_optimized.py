#!/usr/bin/env python3
"""
Optimized debug script for free fall detection.
Focuses on performance with minimal console output.
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
    """Optimized debug function with minimal output."""
    
    # Initialize the accelerometer manager
    accel_manager = AccelerometerManager()
    
    try:
        # Initialize the sensor
        print("Initializing accelerometer...")
        if not await accel_manager.initialize():
            print("Failed to initialize accelerometer!")
            return
        
        print("Accelerometer initialized successfully!")
        print(f"Thresholds: Accel<{accel_manager.free_fall_accel_threshold:.1f} m/s², Gyro>{accel_manager.free_fall_min_rotation:.1f} rad/s")
        print("Monitoring... (Press Ctrl+C to stop)")
        print("Output format: [Sample] Time(ms) | State | Accel(m/s²) | Gyro(rad/s) | Alerts")
        
        # Monitor loop with minimal processing
        sample_count = 0
        last_time = time.monotonic()
        last_state = "UNKNOWN"
        
        while True:
            try:
                # Read sensor data
                data = await accel_manager.read_sensor_data()
                sample_count += 1
                current_time = time.monotonic()
                ms_since_last = (current_time - last_time) * 1000
                last_time = current_time

                # Extract only essential values
                raw_accel = data.get("acceleration", (0, 0, 0))
                gyro = data.get("gyro", (0, 0, 0))
                current_state = data.get("current_state", "UNKNOWN")
                
                # Fast magnitude calculations
                raw_accel_mag = sqrt(raw_accel[0]**2 + raw_accel[1]**2 + raw_accel[2]**2)
                gyro_mag = sqrt(gyro[0]**2 + gyro[1]**2 + gyro[2]**2)
                
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
                    
                    print(f"[{sample_count:4d}] {ms_since_last:5.1f}ms | {current_state:10s} | {raw_accel_mag:5.1f} | {gyro_mag:5.2f} | {alert}")
                
                last_state = current_state
                
                # Minimal delay to prevent overwhelming the system
                if ms_since_last < 5:  # If we're going too fast, add tiny delay
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