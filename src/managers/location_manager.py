import os
import time
import logging
from typing import Dict, Optional, List, Tuple, Any, Union
from collections import defaultdict
from config import BLEConfig, PLATFORM, Distance

# Only import bluepy on Raspberry Pi
if PLATFORM == "raspberry-pi":
    from bluepy.btle import Scanner, DefaultDelegate
else:
    Scanner = None
    DefaultDelegate = object

class ScanDelegate(DefaultDelegate):
    """Delegate class for handling BLE scan callbacks"""
    def __init__(self):
        DefaultDelegate.__init__(self)
        
    def handleDiscovery(self, dev, isNewDev, isNewData):
        """Called when a new device is discovered"""
        pass  # We'll handle the device data in the main scanning loop

class LocationManager:
    """Manages BLE scanning and location tracking"""
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self._scanner = None if PLATFORM != "raspberry-pi" else Scanner().withDelegate(ScanDelegate())
        self._last_location = None
        self._no_activity_count = 0
        self._is_running = False
        # Initialize RSSI smoothing
        self._rssi_ema = defaultdict(lambda: None)  # Stores EMA for each beacon
        
    def _toggle_bluetooth(self, state: bool) -> None:
        """Turns Bluetooth ON or OFF"""
        if PLATFORM != "raspberry-pi":
            return
            
        interface = BLEConfig.BLUETOOTH_INTERFACE
        action = "up" if state else "down"
        try:
            os.system(f"sudo hciconfig {interface} {action}")
            self.logger.debug(f"Bluetooth interface {interface} turned {action}")
        except Exception as e:
            self.logger.error(f"Failed to toggle Bluetooth {action}: {e}")
            
    def _update_rssi_ema(self, addr: str, rssi: int) -> float:
        """Updates and returns the exponential moving average for a beacon's RSSI"""
        current_ema = self._rssi_ema[addr]
        
        if current_ema is None:
            # First measurement for this beacon
            self._rssi_ema[addr] = float(rssi)
            return float(rssi)
            
        # Calculate new EMA
        alpha = BLEConfig.RSSI_EMA_ALPHA
        new_ema = (alpha * rssi) + ((1 - alpha) * current_ema)
        self._rssi_ema[addr] = new_ema
        return new_ema
        
    def _scan_beacons(self) -> List[Tuple[str, int]]:
        """Scans for BLE devices and returns list of (address, smoothed RSSI) tuples"""
        if PLATFORM != "raspberry-pi":
            self.logger.debug("BLE scanning not available on this platform")
            return []
            
        try:
            devices = self._scanner.scan(BLEConfig.SCAN_DURATION)
            smoothed_devices = []
            
            for dev in devices:
                addr = dev.addr.lower()
                # Only process known beacons
                if addr in BLEConfig.BEACON_LOCATIONS:
                    smoothed_rssi = int(self._update_rssi_ema(addr, dev.rssi))
                    smoothed_devices.append((addr, smoothed_rssi))
                    self.logger.debug(f"Beacon {addr}: Raw RSSI={dev.rssi}, Smoothed={smoothed_rssi}")
            
            return smoothed_devices
            
        except Exception as e:
            self.logger.error(f"Error scanning for BLE devices: {e}")
            return []
            
    def _estimate_distance(self, rssi: int) -> Distance:
        """Estimates distance category based on RSSI value"""
        if rssi >= BLEConfig.RSSI_THRESHOLD_TOUCHING:
            return Distance.TOUCHING
        elif rssi >= BLEConfig.RSSI_THRESHOLD_NEAR:
            return Distance.NEAR
        elif rssi >= BLEConfig.RSSI_THRESHOLD_MEDIUM:
            return Distance.MEDIUM
        else:
            return Distance.FAR
            
    def _get_strongest_beacon(self, devices: List[Tuple[str, int]]) -> Optional[Tuple[str, int]]:
        """Returns the known beacon with strongest smoothed signal"""
        if not devices:
            return None
            
        # Add hysteresis to prevent rapid switching
        current_location = self._last_location.get("location") if self._last_location else None
        
        if current_location:
            # Find current beacon's address
            current_addr = next(
                (addr for addr, loc in BLEConfig.BEACON_LOCATIONS.items() 
                 if loc == current_location), 
                None
            )
            
            if current_addr:
                # Find current beacon in devices
                current_beacon = next(
                    ((addr, rssi) for addr, rssi in devices if addr == current_addr),
                    None
                )
                
                if current_beacon:
                    # Check all other beacons
                    for addr, rssi in devices:
                        if addr != current_addr:
                            # Only switch if another beacon is significantly stronger
                            if rssi > (current_beacon[1] + BLEConfig.RSSI_HYSTERESIS):
                                return max(devices, key=lambda x: x[1])
                    # If no significantly stronger beacon found, stick with current
                    return current_beacon
        
        # If no current location or current beacon not found, simply return strongest
        return max(devices, key=lambda x: x[1])
        
    def get_current_location(self) -> Dict[str, Union[str, Distance]]:
        """Returns the current location information"""
        if not self._last_location:
            return {"location": "unknown", "distance": Distance.UNKNOWN}
        return self._last_location
        
    def scan_once(self) -> Dict[str, Any]:
        """Performs a single scan cycle and returns location info"""
        self._toggle_bluetooth(True)
        devices = self._scan_beacons()
        self._toggle_bluetooth(False)
        
        if not devices:
            self._no_activity_count += 1
            return {
                "location": "unknown",
                "distance": Distance.UNKNOWN,
                "all_beacons": {}
            }
            
        strongest_beacon = self._get_strongest_beacon(devices)
        if not strongest_beacon:
            self._no_activity_count += 1
            return {
                "location": "unknown",
                "distance": Distance.UNKNOWN,
                "all_beacons": {}
            }
            
        # Process all visible beacons
        all_beacons = {}
        for addr, rssi in devices:
            location = BLEConfig.BEACON_LOCATIONS[addr]
            distance = self._estimate_distance(rssi)
            all_beacons[location] = {
                "distance": distance,
                "rssi": rssi
            }
            
        # Get primary location from strongest beacon
        addr, rssi = strongest_beacon
        location = BLEConfig.BEACON_LOCATIONS[addr]
        distance = self._estimate_distance(rssi)
        
        self._no_activity_count = 0
        self._last_location = {
            "location": location,
            "distance": distance,
            "all_beacons": all_beacons
        }
        
        return self._last_location
        
    def get_scan_interval(self) -> int:
        """Returns the current scan interval based on activity"""
        return (BLEConfig.LOW_POWER_SCAN_INTERVAL 
                if self._no_activity_count >= BLEConfig.NO_ACTIVITY_THRESHOLD 
                else BLEConfig.SCAN_INTERVAL)
        
    def start(self) -> None:
        """Starts the location manager"""
        if PLATFORM != "raspberry-pi":
            self.logger.info("Location tracking not available on this platform")
            return
            
        self._is_running = True
        self.logger.info("Location manager started")
        
    def stop(self) -> None:
        """Stops the location manager"""
        self._is_running = False
        self._toggle_bluetooth(False)
        # Clear RSSI history
        self._rssi_ema.clear()
        self.logger.info("Location manager stopped")
        
    @property
    def is_running(self) -> bool:
        """Returns whether the location manager is running"""
        return self._is_running 