#!/usr/bin/env python3
"""
BNO085 Sensor Calibration Script

This script performs calibration of the BNO085 sensor according to the manufacturer's
recommendations from the datasheet. It should be run separately from the main
application to ensure proper calibration.

Calibration Procedure (from BNO085 datasheet):
- Accelerometer: Move device into 4-6 unique orientations, hold each for ~1 second
- Gyroscope: Place device on stationary surface for 2-3 seconds  
- Magnetometer: Rotate device 180° and back in each axis (roll, pitch, yaw), ~2 seconds per axis

The script will guide you through each step and monitor calibration status.
"""

import asyncio
import sys
import os
import logging
import time

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from hardware.acc_bno085 import BNO085Interface, REPORT_ACCURACY_STATUS

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class BNO085Calibrator:
    """Handles BNO085 sensor calibration process."""
    
    def __init__(self):
        self.interface = BNO085Interface()
        
    async def run_calibration(self):
        """Run the complete calibration process."""
        print("=" * 60)
        print("BNO085 Sensor Calibration Tool")
        print("=" * 60)
        print()
        
        # Initialize sensor
        print("Initializing BNO085 sensor...")
        if not await self.interface.initialize():
            print("❌ Failed to initialize sensor!")
            return False
            
        print("✅ Sensor initialized successfully!")
        print()
        
        # Check initial calibration status
        await self._display_calibration_status()
        print()
        
        # Ask user if they want to proceed with calibration
        response = input("Do you want to start calibration? (y/n): ").lower().strip()
        if response != 'y':
            print("Calibration cancelled.")
            return False
            
        print()
        print("Starting calibration process...")
        print("Follow the instructions carefully for best results.")
        print()
        
        # Start calibration
        try:
            await asyncio.to_thread(self.interface.imu.begin_calibration)
            print("✅ Calibration mode enabled")
        except Exception as e:
            print(f"❌ Failed to start calibration: {e}")
            return False
            
        # Guide through calibration steps
        await self._guide_accelerometer_calibration()
        await self._guide_gyroscope_calibration()
        await self._guide_magnetometer_calibration()
        
        # Monitor final calibration status
        await self._monitor_final_calibration()
        
        return True
        
    async def _display_calibration_status(self):
        """Display current calibration status."""
        try:
            status = await self.interface.get_calibration_status()
            status_text = await self.interface.get_calibration_status_text()
            
            print(f"Current calibration status: {status_text}")
            
            if status >= 3:
                print("✅ Calibration is already excellent!")
            elif status >= 2:
                print("✅ Calibration is good")
            elif status >= 1:
                print("⚠️  Calibration is low - calibration recommended")
            else:
                print("❌ Calibration is unreliable - calibration required")
                
        except Exception as e:
            print(f"❌ Could not read calibration status: {e}")
            
    async def _guide_accelerometer_calibration(self):
        """Guide user through accelerometer calibration."""
        print("📱 ACCELEROMETER CALIBRATION")
        print("-" * 30)
        print("Move the device into 4-6 different orientations:")
        print("1. Flat on table (Z-axis up)")
        print("2. On its side (X-axis up)")  
        print("3. On its other side (X-axis down)")
        print("4. Upside down (Z-axis down)")
        print("5. Standing up (Y-axis up)")
        print("6. Leaning back (Y-axis down)")
        print()
        print("Hold each position steady for about 2 seconds.")
        print("Press Enter when ready to start...")
        input()
        
        positions = [
            "Position 1: Place device flat on table (Z-axis up)",
            "Position 2: Place device on its side (X-axis up)", 
            "Position 3: Place device on other side (X-axis down)",
            "Position 4: Place device upside down (Z-axis down)",
            "Position 5: Stand device up (Y-axis up)",
            "Position 6: Lean device back (Y-axis down)"
        ]
        
        for i, position in enumerate(positions, 1):
            print(f"\n{position}")
            print("Hold steady for 2 seconds...")
            
            # Monitor for 3 seconds to ensure position is held
            for second in range(3):
                await asyncio.sleep(1)
                print(f"  {second + 1}/3 seconds...")
                
            print("✅ Position complete!")
            
            if i < len(positions):
                input("Press Enter for next position...")
                
        print("\n✅ Accelerometer calibration sequence complete!")
        
    async def _guide_gyroscope_calibration(self):
        """Guide user through gyroscope calibration."""
        print("\n🔄 GYROSCOPE CALIBRATION")
        print("-" * 25)
        print("Place the device on a stable, stationary surface.")
        print("Do NOT move or touch the device during this step.")
        print("This will calibrate the gyroscope zero-rate offset.")
        print()
        input("Press Enter when device is on stable surface...")
        
        print("\nCalibrating gyroscope... DO NOT MOVE THE DEVICE!")
        
        # Monitor for 5 seconds of stillness
        for second in range(5):
            await asyncio.sleep(1)
            print(f"  {second + 1}/5 seconds... (keep device still)")
            
        print("✅ Gyroscope calibration complete!")
        
    async def _guide_magnetometer_calibration(self):
        """Guide user through magnetometer calibration."""
        print("\n🧭 MAGNETOMETER CALIBRATION")
        print("-" * 27)
        print("Rotate the device to calibrate for magnetic interference.")
        print("Perform these rotations slowly and smoothly:")
        print("1. Roll: Rotate 180° around X-axis and back")
        print("2. Pitch: Rotate 180° around Y-axis and back") 
        print("3. Yaw: Rotate 180° around Z-axis and back")
        print()
        print("Take about 2 seconds for each rotation.")
        input("Press Enter when ready to start...")
        
        rotations = [
            ("Roll (around X-axis)", "Rotate device left/right 180° and back"),
            ("Pitch (around Y-axis)", "Tilt device forward/back 180° and back"),
            ("Yaw (around Z-axis)", "Turn device left/right 180° and back")
        ]
        
        for rotation_name, instruction in rotations:
            print(f"\n{rotation_name}:")
            print(f"  {instruction}")
            print("  Take about 4 seconds total...")
            
            # Give time for rotation
            for second in range(4):
                await asyncio.sleep(1)
                print(f"    {second + 1}/4 seconds...")
                
            print("✅ Rotation complete!")
            
            if rotation_name != rotations[-1][0]:
                input("Press Enter for next rotation...")
                
        print("\n✅ Magnetometer calibration sequence complete!")
        
    async def _monitor_final_calibration(self):
        """Monitor calibration status and save when good."""
        print("\n📊 MONITORING CALIBRATION STATUS")
        print("-" * 32)
        print("Waiting for calibration to stabilize...")
        print("This may take 10-30 seconds.")
        print()
        
        start_time = time.time()
        good_calibration_start = None
        max_wait_time = 60  # Maximum 60 seconds
        
        while time.time() - start_time < max_wait_time:
            try:
                status = await self.interface.get_calibration_status()
                status_text = await self.interface.get_calibration_status_text()
                
                elapsed = int(time.time() - start_time)
                print(f"[{elapsed:2d}s] Calibration status: {status_text}")
                
                if status >= 2:  # Good calibration
                    if good_calibration_start is None:
                        good_calibration_start = time.time()
                        print("✅ Good calibration achieved! Waiting for stability...")
                        
                    # Wait 5 seconds of good calibration before saving
                    if time.time() - good_calibration_start >= 5:
                        print("\n💾 Saving calibration data...")
                        try:
                            await asyncio.to_thread(self.interface.imu.save_calibration_data)
                            print("✅ Calibration data saved successfully!")
                            print()
                            print("🎉 CALIBRATION COMPLETE!")
                            print("The sensor is now calibrated and ready for use.")
                            return True
                        except Exception as e:
                            print(f"❌ Failed to save calibration: {e}")
                            return False
                else:
                    # Reset good calibration timer if status drops
                    good_calibration_start = None
                    
                await asyncio.sleep(1)
                
            except Exception as e:
                print(f"❌ Error reading calibration status: {e}")
                await asyncio.sleep(1)
                
        print(f"\n⚠️  Calibration did not reach good status within {max_wait_time} seconds.")
        print("You may need to repeat the calibration process.")
        return False
        
    def cleanup(self):
        """Clean up resources."""
        self.interface.deinitialize()

async def main():
    """Main calibration function."""
    calibrator = BNO085Calibrator()
    
    try:
        success = await calibrator.run_calibration()
        
        if success:
            print("\n" + "=" * 60)
            print("Calibration completed successfully!")
            print("You can now run your main application.")
            print("=" * 60)
        else:
            print("\n" + "=" * 60)
            print("Calibration was not completed successfully.")
            print("Please try running this script again.")
            print("=" * 60)
            
    except KeyboardInterrupt:
        print("\n\nCalibration interrupted by user.")
    except Exception as e:
        print(f"\n❌ Unexpected error during calibration: {e}")
    finally:
        calibrator.cleanup()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting...") 