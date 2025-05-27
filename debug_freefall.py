#!/usr/bin/env python3
"""
Debug script for free fall detection.
This script will continuously monitor the accelerometer and show:
1. Raw acceleration magnitude
2. Current detected state
3. Free fall threshold comparison
4. Other relevant sensor data
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

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def debug_freefall():
    """Main debug function to monitor free fall detection."""
    
    # Initialize the accelerometer manager
    accel_manager = AccelerometerManager()
    
    try:
        # Initialize the sensor
        logger.info("Initializing accelerometer...")
        if not await accel_manager.initialize():
            logger.error("Failed to initialize accelerometer!")
            return
        
        logger.info("Accelerometer initialized successfully!")
        logger.info(f"Free fall threshold: {accel_manager.free_fall_threshold} m/s²")
        logger.info("Starting monitoring... (Press Ctrl+C to stop)")
        logger.info("Try dropping or throwing the device to test free fall detection!")
        
        # Monitor loop
        sample_count = 0
        last_logged_timer = time.monotonic()
        while True:
            try:
                # Read sensor data
                data = await accel_manager.read_sensor_data()
                sample_count += 1
                ms_since_last_sample = (time.monotonic() - last_logged_timer) * 1000
                last_logged_timer = time.monotonic()

                # Extract key values
                raw_accel = data.get("acceleration", (0, 0, 0))
                linear_accel = data.get("linear_acceleration", (0, 0, 0))
                current_state = data.get("current_state", "UNKNOWN")
                stability = data.get("stability", "Unknown")
                
                # Calculate magnitudes
                raw_accel_mag = sqrt(sum(x*x for x in raw_accel)) if isinstance(raw_accel, tuple) else 0.0
                linear_accel_mag = sqrt(sum(x*x for x in linear_accel)) if isinstance(linear_accel, tuple) else 0.0
                
                # Check if we're in free fall according to our threshold
                is_freefall_by_threshold = raw_accel_mag < accel_manager.free_fall_threshold
                
                # Print status every sample
                print(f"\nTime since last sample: {ms_since_last_sample:.2f}ms, Sample: {sample_count}, Raw Accel: ({raw_accel[0]:.3f}, {raw_accel[1]:.3f}, {raw_accel[2]:.3f}) m/s² | Raw Accel Magnitude: {raw_accel_mag:.3f} m/s² | Linear Accel Magnitude: {linear_accel_mag:.3f} m/s² | Free Fall Threshold: {accel_manager.free_fall_threshold:.3f} m/s² | Below Threshold: {is_freefall_by_threshold} | Detected State: {current_state} | Stability: {stability}")
                
                # Alert on state changes or free fall conditions
                if current_state == "FREE_FALL":
                    print(f"🚨 FREE FALL DETECTED! Raw accel mag: {raw_accel_mag:.3f} m/s²")
                elif is_freefall_by_threshold and current_state != "FREE_FALL":
                    print(f"⚠️  Raw accel below threshold ({raw_accel_mag:.3f} < {accel_manager.free_fall_threshold:.3f}) but state is {current_state}")
                
                # Small delay to avoid overwhelming output
                await asyncio.sleep(0.01)  # 10ms delay
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(0.1)
                
    except Exception as e:
        logger.error(f"Error in debug function: {e}")
    finally:
        # Clean up
        logger.info("Cleaning up...")
        accel_manager.deinitialize()

if __name__ == "__main__":
    try:
        asyncio.run(debug_freefall())
    except KeyboardInterrupt:
        print("\nStopped by user")
    except Exception as e:
        logger.error(f"Unexpected error: {e}") 