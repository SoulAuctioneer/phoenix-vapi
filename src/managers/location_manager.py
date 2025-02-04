import os
import time
import logging
import struct
from typing import Dict, Optional, List, Tuple, Any, Union
from collections import defaultdict
from config import BLEConfig, PLATFORM, Distance

# Only import bluepy on Raspberry Pi
if PLATFORM == "raspberry-pi":
    from bluepy.btle import Scanner, DefaultDelegate, ScanEntry
else:
    Scanner = None
    DefaultDelegate = object
    ScanEntry = object

class ScanDelegate(DefaultDelegate):
    """Delegate class for handling BLE scan callbacks"""
    def __init__(self):
        DefaultDelegate.__init__(self)
        
    def handleDiscovery(self, dev, isNewDev, isNewData):
        """Called when a new device is discovered"""
        pass  # We'll handle the device data in the main scanning loop

def parse_ibeacon_data(mfg_data: bytes) -> Optional[Tuple[str, int, int]]:
    """Parse manufacturer data to extract iBeacon information"""
    try:
        # iBeacon format:
        # bytes 0-1: Company ID (0x004C for Apple)
        # byte 2: iBeacon type (0x02)
        # byte 3: iBeacon length (0x15)
        # bytes 4-19: UUID (16 bytes)
        # bytes 20-21: Major (2 bytes)
        # bytes 22-23: Minor (2 bytes)
        # byte 24: Tx Power
        
        if len(mfg_data) < 25:
            return None
            
        company_id = struct.unpack("<H", mfg_data[0:2])[0]
        ibeacon_type = mfg_data[2]
        ibeacon_length = mfg_data[3]
        
        if company_id != 0x004C or ibeacon_type != 0x02 or ibeacon_length != 0x15:
            return None
            
        uuid_bytes = mfg_data[4:20]
        uuid = "-".join([
            uuid_bytes[0:4].hex(),
            uuid_bytes[4:6].hex(),
            uuid_bytes[6:8].hex(),
            uuid_bytes[8:10].hex(),
            uuid_bytes[10:16].hex()
        ])
        
        major = struct.unpack(">H", mfg_data[20:22])[0]
        minor = struct.unpack(">H", mfg_data[22:24])[0]
        
        return uuid, major, minor
    except Exception:
        return None

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
        
    def _scan_beacons(self) -> List[Tuple[Tuple[int, int], int]]:
        """Scans for BLE devices and returns list of ((major, minor), smoothed RSSI) tuples"""
        if PLATFORM != "raspberry-pi":
            self.logger.debug("BLE scanning not available on this platform")
            return []
            
        try:
            devices = self._scanner.scan(BLEConfig.SCAN_DURATION)
            smoothed_devices = []
            
            for dev in devices:
                # Get manufacturer specific data
                mfg_data = dev.getValueText(ScanEntry.MANUFACTURER) or ""
                if not mfg_data:
                    continue
                    
                # Convert hex string to bytes
                mfg_bytes = bytes.fromhex(mfg_data)
                beacon_info = parse_ibeacon_data(mfg_bytes)
                
                if not beacon_info:
                    continue
                    
                uuid, major, minor = beacon_info
                
                # Check if this is one of our beacons
                if uuid != BLEConfig.BEACON_UUID:
                    continue
                    
                beacon_key = (major, minor)
                if beacon_key in BLEConfig.BEACON_LOCATIONS:
                    smoothed_rssi = int(self._update_rssi_ema(f"{major}:{minor}", dev.rssi))
                    smoothed_devices.append((beacon_key, smoothed_rssi))
                    self.logger.debug(
                        f"Beacon {major}:{minor}: Raw RSSI={dev.rssi}, Smoothed={smoothed_rssi}"
                    )
            
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
            
    def _get_strongest_beacon(self, devices: List[Tuple[Tuple[int, int], int]]) -> Optional[Tuple[Tuple[int, int], int]]:
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
        
    def scan_discovery(self) -> None:
        """Perform a discovery scan for all nearby BLE devices"""
        if PLATFORM != "raspberry-pi":
            self.logger.info("Discovery scan not available in simulation mode")
            return
            
        try:
            self._toggle_bluetooth(True)
            
            # Perform a longer scan to discover all devices
            self.logger.info("Starting discovery scan for all BLE devices...")
            devices = self._scanner.scan(5.0)  # 5 second scan
            
            self.logger.info(f"\nFound {len(devices)} BLE devices:")
            for dev in devices:
                # Basic device info
                self.logger.info(f"\nDevice: {dev.addr}")
                self.logger.info(f"  RSSI: {dev.rssi} dB")
                
                # Get all available names
                complete_name = dev.getValueText(ScanEntry.COMPLETE_LOCAL_NAME)
                short_name = dev.getValueText(ScanEntry.SHORTENED_LOCAL_NAME)
                if complete_name:
                    self.logger.info(f"  Complete Name: {complete_name}")
                if short_name:
                    self.logger.info(f"  Short Name: {short_name}")
                    
                # Service Data
                for adtype in range(0, 255):
                    value = dev.getValueText(adtype)
                    if value:
                        self.logger.info(f"  AD Type 0x{adtype:02x}: {value}")
                
                # Manufacturer Data
                mfg_data = dev.getValueText(ScanEntry.MANUFACTURER)
                if mfg_data:
                    self.logger.info(f"  Manufacturer Data (hex): {mfg_data}")
                    try:
                        mfg_bytes = bytes.fromhex(mfg_data)
                        
                        # Try parsing as iBeacon
                        ibeacon_info = parse_ibeacon_data(mfg_bytes)
                        if ibeacon_info:
                            uuid, major, minor = ibeacon_info
                            self.logger.info(
                                f"  iBeacon Data:"
                                f"\n    UUID: {uuid}"
                                f"\n    Major: {major}"
                                f"\n    Minor: {minor}"
                                f"\n    Matches our UUID: {'Yes' if uuid == BLEConfig.BEACON_UUID else 'No'}"
                            )
                            
                        # Could add other beacon format parsing here
                        # Example: Eddystone, AltBeacon, etc.
                        
                    except Exception as e:
                        self.logger.debug(f"  Could not parse manufacturer data: {e}")
                
                # Service UUIDs
                service_uuids = []
                if dev.getValueText(ScanEntry.COMPLETE_16B_SERVICES):
                    service_uuids.extend(dev.getValueText(ScanEntry.COMPLETE_16B_SERVICES).split(','))
                if dev.getValueText(ScanEntry.COMPLETE_32B_SERVICES):
                    service_uuids.extend(dev.getValueText(ScanEntry.COMPLETE_32B_SERVICES).split(','))
                if dev.getValueText(ScanEntry.COMPLETE_128B_SERVICES):
                    service_uuids.extend(dev.getValueText(ScanEntry.COMPLETE_128B_SERVICES).split(','))
                    
                if service_uuids:
                    self.logger.info("  Service UUIDs:")
                    for uuid in service_uuids:
                        self.logger.info(f"    {uuid}")
                        
                # TX Power Level
                tx_power = dev.getValueText(ScanEntry.TX_POWER)
                if tx_power:
                    self.logger.info(f"  TX Power Level: {tx_power} dBm")
                
        except Exception as e:
            self.logger.error(f"Error during discovery scan: {e}")
        finally:
            self._toggle_bluetooth(False)
            
    def start(self) -> None:
        """Starts the location manager"""
        if PLATFORM != "raspberry-pi":
            self.logger.info("Location tracking not available on this platform")
            return
            
        self._is_running = True
        
        # Do an initial discovery scan
        self.scan_discovery()
        
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