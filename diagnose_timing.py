#!/usr/bin/env python3
"""
Diagnostic script to investigate timing issues with BNO085 sensor readings.
This will help identify why we're getting such long delays between samples.
"""

import asyncio
import sys
import os
import logging
import time
from collections import deque

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from hardware.acc_bno085 import BNO085Interface
from math import sqrt

# Set up logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def diagnose_timing():
    """Diagnose timing issues with the BNO085 sensor."""
    
    # Initialize the sensor interface directly
    interface = BNO085Interface()
    
    try:
        logger.info("Initializing BNO085 sensor...")
        if not await interface.initialize():
            logger.error("Failed to initialize sensor!")
            return
        
        logger.info("Sensor initialized successfully!")
        logger.info("Starting timing diagnostics...")
        logger.info("Try moving the device rapidly to see timing behavior")
        
        # Timing statistics
        timing_stats = deque(maxlen=1000)  # Keep last 1000 samples
        sample_count = 0
        last_read_time = time.perf_counter()
        
        # Monitor for 30 seconds
        start_time = time.perf_counter()
        while (time.perf_counter() - start_time) < 30:
            try:
                # Time the sensor read operation
                read_start = time.perf_counter()
                data = await interface.read_sensor_data()
                read_end = time.perf_counter()
                
                sample_count += 1
                
                # Calculate timing metrics
                time_since_last = (read_start - last_read_time) * 1000  # ms
                read_duration = (read_end - read_start) * 1000  # ms
                last_read_time = read_start
                
                # Get acceleration data
                raw_accel = data.get("acceleration", (0, 0, 0))
                if isinstance(raw_accel, tuple) and len(raw_accel) == 3:
                    accel_mag = sqrt(sum(x*x for x in raw_accel))
                else:
                    accel_mag = 0.0
                
                # Store timing data
                timing_stats.append({
                    'sample': sample_count,
                    'interval_ms': time_since_last,
                    'read_ms': read_duration,
                    'accel_mag': accel_mag
                })
                
                # Print detailed timing for samples with long intervals
                if time_since_last > 100:  # More than 100ms
                    print(f"\n⚠️  LONG INTERVAL DETECTED!")
                    print(f"Sample {sample_count}: Interval={time_since_last:.1f}ms, Read={read_duration:.1f}ms")
                    print(f"Acceleration magnitude: {accel_mag:.2f} m/s²")
                    print(f"Raw accel: {raw_accel}")
                
                # Regular status every 100 samples
                if sample_count % 100 == 0:
                    recent_intervals = [s['interval_ms'] for s in list(timing_stats)[-100:]]
                    avg_interval = sum(recent_intervals) / len(recent_intervals)
                    max_interval = max(recent_intervals)
                    min_interval = min(recent_intervals)
                    
                    print(f"\n--- Sample {sample_count} Statistics ---")
                    print(f"Last 100 samples:")
                    print(f"  Avg interval: {avg_interval:.1f}ms")
                    print(f"  Min interval: {min_interval:.1f}ms") 
                    print(f"  Max interval: {max_interval:.1f}ms")
                    print(f"  Current accel: {accel_mag:.2f} m/s²")
                
                # Minimal delay to yield control
                await asyncio.sleep(0.001)  # 1ms
                
            except Exception as e:
                logger.error(f"Error reading sensor: {e}")
                await asyncio.sleep(0.1)
        
        # Final statistics
        print("\n\n=== FINAL TIMING STATISTICS ===")
        all_intervals = [s['interval_ms'] for s in timing_stats]
        print(f"Total samples: {len(timing_stats)}")
        print(f"Average interval: {sum(all_intervals)/len(all_intervals):.1f}ms")
        print(f"Min interval: {min(all_intervals):.1f}ms")
        print(f"Max interval: {max(all_intervals):.1f}ms")
        
        # Find correlation between acceleration and timing
        high_accel_intervals = []
        low_accel_intervals = []
        
        for stat in timing_stats:
            if stat['accel_mag'] > 20.0:  # High acceleration
                high_accel_intervals.append(stat['interval_ms'])
            elif stat['accel_mag'] < 15.0:  # Low acceleration
                low_accel_intervals.append(stat['interval_ms'])
        
        if high_accel_intervals:
            print(f"\nHigh acceleration (>20 m/s²) intervals:")
            print(f"  Average: {sum(high_accel_intervals)/len(high_accel_intervals):.1f}ms")
            print(f"  Count: {len(high_accel_intervals)}")
        
        if low_accel_intervals:
            print(f"\nLow acceleration (<15 m/s²) intervals:")
            print(f"  Average: {sum(low_accel_intervals)/len(low_accel_intervals):.1f}ms")
            print(f"  Count: {len(low_accel_intervals)}")
                
    except Exception as e:
        logger.error(f"Error in diagnostic: {e}", exc_info=True)
    finally:
        logger.info("Cleaning up...")
        interface.deinitialize()

if __name__ == "__main__":
    try:
        asyncio.run(diagnose_timing())
    except KeyboardInterrupt:
        print("\nStopped by user")
    except Exception as e:
        logger.error(f"Unexpected error: {e}") 