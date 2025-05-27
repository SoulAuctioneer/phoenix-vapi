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
        logger.info(f"Multi-sensor free fall detection:")
        logger.info(f"  - Max acceleration: {accel_manager.free_fall_accel_threshold} m/s²")
        logger.info(f"  - Min rotation: {accel_manager.free_fall_min_rotation} rad/s")
        logger.info(f"  - Min duration: {accel_manager.free_fall_min_duration} seconds")
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
                gyro = data.get("gyro", (0, 0, 0))
                current_state = data.get("current_state", "UNKNOWN")
                stability = data.get("stability", "Unknown")
                
                # Calculate magnitudes
                raw_accel_mag = sqrt(sum(x*x for x in raw_accel)) if isinstance(raw_accel, tuple) else 0.0
                linear_accel_mag = sqrt(sum(x*x for x in linear_accel)) if isinstance(linear_accel, tuple) else 0.0
                gyro_mag = sqrt(sum(x*x for x in gyro)) if isinstance(gyro, tuple) else 0.0
                
                # Check free fall conditions using new multi-sensor approach
                is_low_accel = raw_accel_mag < accel_manager.free_fall_accel_threshold
                has_rotation = gyro_mag > accel_manager.free_fall_min_rotation
                is_extremely_still = (raw_accel_mag > 8.0 and raw_accel_mag < 12.0 and gyro_mag < 0.02)
                
                # Print status every sample
                print(f"\nTime since last sample: {ms_since_last_sample:.2f}ms, Sample: {sample_count}")
                print(f"Raw Accel: ({raw_accel[0]:.3f}, {raw_accel[1]:.3f}, {raw_accel[2]:.3f}) m/s² | Mag: {raw_accel_mag:.3f}")
                print(f"Linear Accel: ({linear_accel[0]:.3f}, {linear_accel[1]:.3f}, {linear_accel[2]:.3f}) m/s² | Mag: {linear_accel_mag:.3f}")
                print(f"Gyro: ({gyro[0]:.3f}, {gyro[1]:.3f}, {gyro[2]:.3f}) rad/s | Mag: {gyro_mag:.3f}")
                print(f"Multi-sensor FF: LowAccel({raw_accel_mag:.3f}<{accel_manager.free_fall_accel_threshold:.1f})={is_low_accel} | HasRotation({gyro_mag:.3f}>{accel_manager.free_fall_min_rotation:.1f})={has_rotation} | ExtremelyStill={is_extremely_still}")
                print(f"State: {current_state} | Stability: {stability}")
                
                # Alert on state changes or free fall conditions
                if current_state == "FREE_FALL":
                    print(f"🚨 FREE FALL DETECTED! Multi-sensor approach confirmed")
                elif is_low_accel and has_rotation and not is_extremely_still:
                    print(f"⚠️  Free fall conditions met but not yet confirmed (duration/timing)")
                elif is_low_accel and not has_rotation:
                    print(f"ℹ️  Low acceleration but no rotation - likely stationary, not free fall")
                elif is_extremely_still:
                    print(f"📍 Device is extremely still (near 1g acceleration, minimal rotation)")
                
                # Small delay to avoid overwhelming output
                # await asyncio.sleep(0.01)  # 10ms delay
                
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