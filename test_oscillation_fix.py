#!/usr/bin/env python3
"""
Test script to verify the accelerometer state oscillation fix.

This script simulates the sensor readings from the logs to verify that
the enhanced hysteresis and dead zone logic prevents rapid oscillations
between STATIONARY and HELD_STILL states.
"""

import sys
import os
import time
import asyncio
import logging

# Add the src directory to the path so we can import the manager
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from managers.accelerometer_manager import AccelerometerManager, SimplifiedState

# Configure logging to see debug messages
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

class MockBNO085Interface:
    """Mock interface that simulates the sensor readings from the logs."""
    
    def __init__(self):
        self.reading_index = 0
        # Simulate the readings from the logs that caused oscillation
        # Format: (linear_accel_mag, gyro_mag, raw_accel_mag)
        self.test_readings = [
            # Initial readings - should establish STATIONARY
            (0.03, 0.00, 9.5),  # Should be STATIONARY
            (0.03, 0.00, 9.5),  # Should stay STATIONARY
            (0.03, 0.00, 9.5),  # Should stay STATIONARY
            
            # Tiny jolt - should NOT cause immediate transition with new logic
            (0.20, 0.01, 9.5),  # This used to cause STATIONARY → HELD_STILL
            (0.15, 0.01, 9.5),  # Brief spike
            (0.05, 0.00, 9.5),  # Back to low
            (0.03, 0.00, 9.5),  # Back to stationary levels
            
            # Another tiny jolt
            (0.26, 0.03, 9.5),  # Another spike
            (0.10, 0.01, 9.5),  # Settling
            (0.04, 0.00, 9.5),  # Back to stationary
            
            # Sustained higher motion - should eventually transition
            (0.35, 0.05, 9.5),  # Sustained higher motion
            (0.40, 0.06, 9.5),  # Sustained higher motion
            (0.38, 0.05, 9.5),  # Sustained higher motion
            (0.42, 0.07, 9.5),  # Sustained higher motion
            (0.39, 0.06, 9.5),  # Sustained higher motion
        ]
    
    async def initialize(self):
        return True
    
    def deinitialize(self):
        pass
    
    async def read_sensor_data_optimized(self):
        """Return mock sensor data based on the test readings."""
        if self.reading_index >= len(self.test_readings):
            # Repeat the last reading
            linear_mag, gyro_mag, raw_mag = self.test_readings[-1]
        else:
            linear_mag, gyro_mag, raw_mag = self.test_readings[self.reading_index]
            self.reading_index += 1
        
        # Convert magnitudes back to 3D vectors (simplified)
        linear_accel = (linear_mag, 0.0, 0.0)
        gyro = (gyro_mag, 0.0, 0.0)
        raw_accel = (raw_mag, 0.0, 0.0)
        
        return {
            'linear_acceleration': linear_accel,
            'gyro': gyro,
            'acceleration': raw_accel,
        }

async def test_oscillation_fix():
    """Test the oscillation fix with simulated sensor data."""
    print("Testing accelerometer state oscillation fix...")
    print("=" * 60)
    
    # Create manager with mock interface
    manager = AccelerometerManager()
    manager.interface = MockBNO085Interface()
    
    # Initialize
    await manager.initialize()
    
    # Track state changes
    previous_state = None
    state_changes = []
    
    # Run test for multiple readings
    for i in range(20):
        print(f"\n--- Reading {i+1} ---")
        
        # Read sensor data
        data = await manager.read_sensor_data()
        
        current_state = data['current_state']
        linear_accel = data.get('linear_acceleration', (0, 0, 0))
        linear_mag = (linear_accel[0]**2 + linear_accel[1]**2 + linear_accel[2]**2)**0.5
        
        print(f"Linear accel: {linear_mag:.3f} m/s²")
        print(f"Current state: {current_state}")
        
        # Track state changes
        if previous_state is not None and current_state != previous_state:
            change = f"{previous_state} → {current_state}"
            state_changes.append(change)
            print(f"*** STATE CHANGE: {change} ***")
        
        previous_state = current_state
        
        # Small delay to simulate real timing
        await asyncio.sleep(0.02)  # 20ms like real sensor
    
    print("\n" + "=" * 60)
    print("TEST RESULTS:")
    print(f"Total state changes: {len(state_changes)}")
    
    if len(state_changes) == 0:
        print("✅ EXCELLENT: No state changes detected (very stable)")
    elif len(state_changes) <= 2:
        print("✅ GOOD: Minimal state changes (acceptable stability)")
        for change in state_changes:
            print(f"  - {change}")
    elif len(state_changes) <= 5:
        print("⚠️  MODERATE: Some state changes (could be improved)")
        for change in state_changes:
            print(f"  - {change}")
    else:
        print("❌ POOR: Too many state changes (oscillation still present)")
        for change in state_changes:
            print(f"  - {change}")
    
    print("\nExpected behavior:")
    print("- Should start in UNKNOWN, quickly move to STATIONARY")
    print("- Should NOT oscillate between STATIONARY and HELD_STILL due to tiny jolts")
    print("- Should only transition after sustained higher motion")
    
    manager.deinitialize()

if __name__ == "__main__":
    asyncio.run(test_oscillation_fix()) 