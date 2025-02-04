import os
import time
import logging
import struct
import asyncio
import subprocess
from typing import Dict, Optional, List, Tuple, Any, Union
from collections import defaultdict
from config import BLEConfig, PLATFORM, Distance
from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

class LocationManager:
    """Manages BLE scanning and location tracking"""
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self._scanner = None
        self._last_location = {
            "location": "unknown",
            "distance": Distance.UNKNOWN,
            "all_beacons": {}
        }
        self._no_activity_count = 0
        self._is_running = False
        self._scanning_lock = asyncio.Lock()  # Add lock for scan coordination
        # Initialize RSSI smoothing
        self._rssi_ema = defaultdict(lambda: None)  # Stores EMA for each beacon
        
    def _ensure_bluetooth_powered(self) -> bool:
        """Ensures Bluetooth adapter is powered on
        
        Returns:
            bool: True if adapter is powered on, False otherwise
        """
        if PLATFORM != "raspberry-pi":
            return True
            
        try:
            # Check adapter status
            result = subprocess.run(
                ['hciconfig', BLEConfig.BLUETOOTH_INTERFACE], 
                capture_output=True, 
                text=True
            )
            
            if "UP RUNNING" not in result.stdout:
                self.logger.info("Bluetooth adapter is down, attempting to power on...")
                # Try to power on the adapter
                subprocess.run(
                    ['sudo', 'hciconfig', BLEConfig.BLUETOOTH_INTERFACE, 'up'],
                    check=True
                )
                # Wait a moment for the adapter to initialize
                time.sleep(1)
                
                # Check again
                result = subprocess.run(
                    ['hciconfig', BLEConfig.BLUETOOTH_INTERFACE], 
                    capture_output=True, 
                    text=True
                )
                if "UP RUNNING" not in result.stdout:
                    self.logger.error("Failed to power on Bluetooth adapter")
                    return False
                    
                self.logger.info("Successfully powered on Bluetooth adapter")
            return True
            
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Error managing Bluetooth adapter: {e}")
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error managing Bluetooth adapter: {e}")
            return False
            
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
        
    def parse_ibeacon_data(self, mfg_data: bytes) -> Optional[Tuple[str, int, int]]:
        """Parse manufacturer data to extract iBeacon information"""
        try:
            if len(mfg_data) < 25:
                return None
                
            company_id = int.from_bytes(mfg_data[0:2], byteorder='little')
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
            
            major = int.from_bytes(mfg_data[20:22], byteorder='big')
            minor = int.from_bytes(mfg_data[22:24], byteorder='big')
            
            return uuid, major, minor
        except Exception:
            return None
            
    async def _scan_beacons(self) -> List[Tuple[Tuple[int, int], int]]:
        """Scans for BLE devices and returns list of ((major, minor), smoothed RSSI) tuples"""
        if PLATFORM != "raspberry-pi":
            self.logger.debug("BLE scanning not available on this platform")
            return []
            
        try:
            # Ensure Bluetooth is powered on
            if not self._ensure_bluetooth_powered():
                return []
                
            # Create scanner if needed
            if not self._scanner:
                # Configure scanner with our settings
                try:
                    self._scanner = BleakScanner(
                        adapter=BLEConfig.BLUETOOTH_INTERFACE,  # Use configured interface
                        detection_callback=None,  # We'll process devices after scan
                        scanning_mode="active"  # Active scanning to get more data
                    )
                except Exception as e:
                    self.logger.error(f"Failed to create BLE scanner: {e}")
                    return []
            
            # Scan for devices
            try:
                async with self._scanning_lock:  # Use lock to prevent concurrent scans
                    devices = await self._scanner.discover(
                        timeout=BLEConfig.SCAN_DURATION,
                        return_adv=True  # Get advertisement data
                    )
            except asyncio.TimeoutError:
                self.logger.warning("BLE scan timed out")
                return []
            except Exception as e:
                self.logger.error(f"Error during BLE scan: {e}")
                # Try to recreate scanner on next scan
                self._scanner = None
                return []
                
            smoothed_devices = []
            
            for device, adv in devices.values():
                try:
                    # Get manufacturer data from advertisement data
                    if not adv.manufacturer_data:
                        continue
                        
                    # Process manufacturer data
                    for company_id, data in adv.manufacturer_data.items():
                        if company_id != 0x004C:  # Apple's company ID
                            continue
                            
                        beacon_info = self.parse_ibeacon_data(bytes([company_id & 0xFF, company_id >> 8]) + data)
                        if not beacon_info:
                            continue
                            
                        uuid, major, minor = beacon_info
                        
                        # Check if this is one of our beacons
                        if uuid.lower() != BLEConfig.BEACON_UUID.lower():
                            continue
                            
                        beacon_key = (major, minor)
                        if beacon_key in BLEConfig.BEACON_LOCATIONS:
                            smoothed_rssi = int(self._update_rssi_ema(f"{major}:{minor}", adv.rssi))
                            smoothed_devices.append((beacon_key, smoothed_rssi))
                            self.logger.debug(
                                f"Beacon {major}:{minor}: Raw RSSI={adv.rssi}, Smoothed={smoothed_rssi}"
                            )
                except Exception as e:
                    self.logger.warning(f"Error processing device {device.address}: {e}")
                    continue
            
            return smoothed_devices
            
        except Exception as e:
            self.logger.error(f"Error scanning for BLE devices: {e}")
            return []
            
    async def scan_discovery(self) -> None:
        """Perform a discovery scan for all nearby BLE devices"""
        if PLATFORM != "raspberry-pi":
            self.logger.info("Discovery scan not available in simulation mode")
            return
            
        try:
            # Ensure Bluetooth is powered on
            if not self._ensure_bluetooth_powered():
                self.logger.error("Cannot perform discovery scan: Bluetooth adapter is not powered on")
                return
                
            # Create scanner if needed
            if not self._scanner:
                try:
                    self.logger.info(f"Creating BLE scanner on interface {BLEConfig.BLUETOOTH_INTERFACE}...")
                    self._scanner = BleakScanner(
                        adapter=BLEConfig.BLUETOOTH_INTERFACE,
                        detection_callback=None,
                        scanning_mode="active"
                    )
                except Exception as e:
                    self.logger.error(f"Failed to create BLE scanner for discovery: {e}")
                    return
            
            self.logger.info("Starting discovery scan for all BLE devices (10 second scan)...")
            try:
                async with self._scanning_lock:  # Use lock to prevent concurrent scans
                    devices = await self._scanner.discover(
                        timeout=10.0,
                        return_adv=True  # Get advertisement data
                    )
            except asyncio.TimeoutError:
                self.logger.warning("Discovery scan timed out")
                return
            except Exception as e:
                self.logger.error(f"Error during discovery scan: {e}")
                self._scanner = None
                return
            
            if not devices:
                self.logger.info("No BLE devices found during discovery scan")
                return
                
            self.logger.info(f"\nFound {len(devices)} BLE devices:")
            ibeacon_count = 0
            
            for device, adv in devices.values():
                try:
                    # Basic device info
                    self.logger.info(f"\nDevice: {device.address}")
                    self.logger.info(f"  Name: {device.name or adv.local_name or 'Unknown'}")
                    self.logger.info(f"  RSSI: {adv.rssi} dB")
                    
                    # Connection info if available
                    if hasattr(adv, 'connectable'):
                        self.logger.info(f"  Connectable: {adv.connectable}")
                    
                    # Manufacturer Data
                    if adv.manufacturer_data:
                        for company_id, data in adv.manufacturer_data.items():
                            self.logger.info(f"  Manufacturer 0x{company_id:04x}: {data.hex()}")
                            
                            # Try parsing as iBeacon if it's Apple's company ID
                            if company_id == 0x004C:
                                beacon_info = self.parse_ibeacon_data(
                                    bytes([company_id & 0xFF, company_id >> 8]) + data
                                )
                                if beacon_info:
                                    uuid, major, minor = beacon_info
                                    ibeacon_count += 1
                                    self.logger.info(
                                        f"  iBeacon Data:"
                                        f"\n    UUID: {uuid}"
                                        f"\n    Major: {major}"
                                        f"\n    Minor: {minor}"
                                        f"\n    Matches our UUID: {'Yes' if uuid.lower() == BLEConfig.BEACON_UUID.lower() else 'No'}"
                                        f"\n    Location Name: {BLEConfig.BEACON_LOCATIONS.get((major, minor), 'Unknown')}"
                                    )
                    
                    # Service Data
                    if adv.service_data:
                        self.logger.info("  Service Data:")
                        for uuid, data in adv.service_data.items():
                            self.logger.info(f"    {uuid}: {data.hex()}")
                    
                    # Service UUIDs
                    if adv.service_uuids:
                        self.logger.info("  Service UUIDs:")
                        for uuid in adv.service_uuids:
                            self.logger.info(f"    {uuid}")
                            
                    # TX Power Level if available
                    if adv.tx_power is not None:
                        self.logger.info(f"  TX Power: {adv.tx_power} dBm")
                        
                except Exception as e:
                    self.logger.warning(f"Error processing device {device.address}: {e}")
                    continue
                    
            # Summary
            self.logger.info(f"\nDiscovery scan summary:")
            self.logger.info(f"  Total devices found: {len(devices)}")
            self.logger.info(f"  iBeacons found: {ibeacon_count}")
            if ibeacon_count > 0:
                self.logger.info(f"  Our configured locations: {list(BLEConfig.BEACON_LOCATIONS.values())}")
                    
        except Exception as e:
            self.logger.error(f"Error during discovery scan: {e}")
            self._scanner = None
            
    async def scan_once(self) -> Dict[str, Any]:
        """Performs a single scan cycle and returns location info"""
        try:
            # Try to get the lock, but don't wait too long
            async with asyncio.timeout(0.1):  # 100ms timeout
                if self._scanning_lock.locked():
                    self.logger.debug("Skipping scan - another scan is in progress")
                    return self._last_location
                    
                devices = await self._scan_beacons()
        except asyncio.TimeoutError:
            self.logger.debug("Skipping scan - could not acquire lock")
            return self._last_location
            
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
        
    async def start(self) -> None:
        """Starts the location manager"""
        if PLATFORM != "raspberry-pi":
            self.logger.info("Location tracking not available on this platform")
            return
            
        # Ensure Bluetooth is powered on before starting
        if not self._ensure_bluetooth_powered():
            self.logger.error("Failed to start location manager: Bluetooth adapter is not powered on")
            return
            
        self._is_running = True
        
        # Start discovery scan in background
        self.logger.info("Starting initial discovery scan in background...")
        asyncio.create_task(self._run_initial_discovery())
            
        self.logger.info("Location manager started")
        
    async def _run_initial_discovery(self) -> None:
        """Runs the initial discovery scan in the background"""
        try:
            await self.scan_discovery()
            self.logger.info("Initial discovery scan complete")
        except Exception as e:
            self.logger.error(f"Error during initial discovery scan: {e}")
            # Continue anyway as this is not critical
        
    async def stop(self) -> None:
        """Stops the location manager"""
        self._is_running = False
        if self._scanner:
            try:
                # Stop any ongoing scan
                await self._scanner.stop()
            except Exception as e:
                self.logger.error(f"Error stopping scanner: {e}")
            finally:
                self._scanner = None
                
        # Clear RSSI history
        self._rssi_ema.clear()
        self.logger.info("Location manager stopped")
        
    @property
    def is_running(self) -> bool:
        """Returns whether the location manager is running"""
        return self._is_running 

    def _estimate_distance(self, rssi: int) -> Distance:
        """Estimates distance category based on RSSI value"""
        if rssi >= BLEConfig.RSSI_IMMEDIATE:
            return Distance.IMMEDIATE
        elif rssi >= BLEConfig.RSSI_NEAR:
            return Distance.NEAR
        elif rssi >= BLEConfig.RSSI_FAR:
            return Distance.FAR
        else:
            return Distance.UNKNOWN
            
    def _get_strongest_beacon(self, devices: List[Tuple[Tuple[int, int], int]]) -> Optional[Tuple[Tuple[int, int], int]]:
        """Returns the known beacon with strongest smoothed signal
        
        Args:
            devices: List of ((major, minor), rssi) tuples
            
        Returns:
            Optional tuple of ((major, minor), rssi) for the strongest beacon,
            considering hysteresis if there's a current location
        """
        if not devices:
            return None
            
        # Add hysteresis to prevent rapid switching
        current_location = self._last_location.get("location") if self._last_location else None
        
        if current_location and current_location != "unknown":
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
        
    def get_current_location(self) -> Dict[str, Any]:
        """Returns the current location information"""
        if not self._last_location:
            return {
                "location": "unknown",
                "distance": Distance.UNKNOWN,
                "all_beacons": {}
            }
        return self._last_location
        
    def get_scan_interval(self) -> int:
        """Returns the current scan interval based on activity"""
        return (BLEConfig.LOW_POWER_SCAN_INTERVAL 
                if self._no_activity_count >= BLEConfig.NO_ACTIVITY_THRESHOLD 
                else BLEConfig.SCAN_INTERVAL) 