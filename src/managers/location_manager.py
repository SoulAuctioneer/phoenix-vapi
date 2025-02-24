import os
import time
import logging
import struct
import asyncio
import subprocess
from typing import Dict, Optional, List, Tuple, Any
from collections import defaultdict
from config import BLEConfig, PLATFORM, Distance
from bleak import BleakScanner

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
        self._empty_scan_count = 0  # Initialize empty scan counter
        self._beacon_empty_counts = defaultdict(int)  # Track empty scans per beacon
        self._is_running = False
        self._scanning_lock = asyncio.Lock()  # Add lock for scan coordination
        # Initialize RSSI smoothing
        self._rssi_ema = defaultdict(lambda: None)  # Stores EMA for each beacon
        self._consecutive_readings = defaultdict(int)
        self._last_seen_timestamps = defaultdict(float)
        self._last_location_change_time = 0.0
        self._last_strongest = None  # Tracks the last strongest beacon for hysteresis
        
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
        # if PLATFORM != "raspberry-pi":
        #     self.logger.debug("BLE scanning not available on this platform")
        #     return []
            
        try:
            # Ensure Bluetooth is powered on
            if not self._ensure_bluetooth_powered():
                return []
                
            # Create scanner if needed
            if not self._scanner:
                # Configure scanner with our settings
                # TODO: Bleak does a lot of this work for us, we're overcomplicating things here
                # ...   See /Users/ash/develop/phoenix/phoenix-vapi/.venv/lib/python3.13/site-packages/bleak/__init__.py
                # ...   and https://github.com/protobioengineering/bleak-python-examples/blob/main/continuous_ble_scanner.py
                try:
                    self.logger.debug(f"Creating BLE scanner on interface {BLEConfig.BLUETOOTH_INTERFACE}...")
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
                self.logger.debug(f"Starting beacon scan with duration {BLEConfig.SCAN_DURATION}s...")
                devices = await self._scanner.discover(
                    timeout=BLEConfig.SCAN_DURATION,
                    return_adv=True  # Get advertisement data
                )
                self.logger.debug(f"Raw scan complete, found {len(devices)} devices")
                # Log details about each device found
                # Too noisy, disable for now
                # for addr, (device, adv) in devices.items():
                #     mfg_data = "No mfg data"
                #     if adv.manufacturer_data:
                #         mfg_ids = [f"0x{id:04x}" for id in adv.manufacturer_data.keys()]
                #         mfg_data = f"Mfg IDs: {', '.join(mfg_ids)}"
                #     self.logger.debug(f"  Device {addr}: RSSI={adv.rssi}dB, {mfg_data}")
            except asyncio.TimeoutError:
                self.logger.warning("BLE scan timed out")
                return []
            except Exception as e:
                self.logger.error(f"Error during BLE scan: {e}")
                # Try to recreate scanner on next scan
                self._scanner = None
                return []
                
            smoothed_devices = []
            ibeacon_count = 0
            apple_device_count = 0
            
            for device, adv in devices.values():
                try:
                    # Get manufacturer data from advertisement data
                    if not adv.manufacturer_data:
                        continue
                        
                    # Process manufacturer data
                    for company_id, data in adv.manufacturer_data.items():
                        if company_id == 0x004C:  # Apple's company ID
                            apple_device_count += 1
                            beacon_info = self.parse_ibeacon_data(bytes([company_id & 0xFF, company_id >> 8]) + data)
                            if not beacon_info:
                                continue
                                
                            uuid, major, minor = beacon_info
                            ibeacon_count += 1
                            # self.logger.debug(f"Found iBeacon - UUID: {uuid}, Major: {major}, Minor: {minor}, RSSI: {adv.rssi}")
                            
                            # Check if this is one of our beacons
                            if uuid.lower() != BLEConfig.BEACON_UUID.lower():
                                # self.logger.debug(f"UUID mismatch - Found: {uuid}, Expected: {BLEConfig.BEACON_UUID}")
                                continue
                                
                            beacon_key = (major, minor)
                            if beacon_key in BLEConfig.BEACON_LOCATIONS:
                                smoothed_rssi = int(self._update_rssi_ema(f"{major}:{minor}", adv.rssi))
                                smoothed_devices.append((beacon_key, smoothed_rssi))
                                self.logger.debug(
                                    f"Matched beacon {major}:{minor} ({BLEConfig.BEACON_LOCATIONS[beacon_key]}): Raw RSSI={adv.rssi}, Smoothed={smoothed_rssi}"
                                )
                            else:
                                self.logger.debug(f"Unknown beacon location for Major: {major}, Minor: {minor}")
                except Exception as e:
                    self.logger.warning(f"Error processing device {device.address}: {e}")
                    continue

            # Too noisy, disable for now
            # self.logger.debug(f"Scan processing complete - Found {len(devices)} total devices, {apple_device_count} Apple devices, {ibeacon_count} iBeacons, {len(smoothed_devices)} valid beacons")
            return smoothed_devices
            
        except Exception as e:
            self.logger.error(f"Error scanning for BLE devices: {e}")
            return []
            
    async def scan_discovery(self) -> None:
        """Perform a discovery scan for all nearby BLE devices"""
        # if PLATFORM != "raspberry-pi":
        #     self.logger.info("Discovery scan not available in simulation mode")
        #     return
            
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
            # Check if a scan is already in progress
            if self._scanning_lock.locked():
                self.logger.debug("Skipping scan - another scan is in progress")
                return self._last_location
                
            # Try to get the lock with a timeout
            try:
                async with self._scanning_lock:
                    devices = await self._scan_beacons()
                    self.logger.debug(f"Beacon scan complete, found {len(devices)} location beacons. Current location: {self._last_location.get('location')}")
            except asyncio.TimeoutError:
                self.logger.debug("Skipping scan - operation timed out")
                return self._last_location
            
        except Exception as e:
            self.logger.debug(f"Skipping scan - {str(e)}")
            return self._last_location
            
        if not devices:
            # Increment empty scan counters
            self._empty_scan_count += 1
            for location in BLEConfig.BEACON_LOCATIONS.values():
                self._beacon_empty_counts[location] += 1
            
            # Check timeout before declaring unknown
            current_time = time.time()
            for location in self._last_location.get("all_beacons", {}):
                if (current_time - self._last_seen_timestamps[location]) < BLEConfig.BEACON_TIMEOUT_SEC:
                    # Keep last known state if within timeout
                    return self._last_location
            
            # Only declare unknown after minimum number of empty scans
            if self._empty_scan_count < BLEConfig.MIN_EMPTY_SCANS_FOR_UNKNOWN:
                return self._last_location
            
            self._consecutive_readings.clear()
            self._no_activity_count += 1
            return {
                "location": "unknown",
                "distance": Distance.UNKNOWN,
                "all_beacons": {}
            }
            
        # Reset empty scan counter when we get devices
        self._empty_scan_count = 0
        
        # Update last seen timestamps and reset empty counts for detected beacons
        current_time = time.time()
        seen_locations = set()
        for addr, rssi in devices:
            location = BLEConfig.BEACON_LOCATIONS[addr]
            seen_locations.add(location)
            self._last_seen_timestamps[location] = current_time
            self._beacon_empty_counts[location] = 0  # Reset empty count for this beacon
            
        # Increment empty counts for unseen beacons
        for location in BLEConfig.BEACON_LOCATIONS.values():
            if location not in seen_locations:
                self._beacon_empty_counts[location] += 1
            
        # Get strongest beacon considering consecutive readings
        strongest = self._get_strongest_beacon(devices)
        if strongest:
            addr, rssi = strongest
            location = BLEConfig.BEACON_LOCATIONS[addr]
            self._consecutive_readings[location] += 1

            self._no_activity_count = 0

            # Process all visible beacons
            all_beacons = {}
            for addr, rssi in devices:
                location = BLEConfig.BEACON_LOCATIONS[addr]
                smoothed_rssi = int(self._update_rssi_ema(f"{addr[0]}:{addr[1]}", rssi))
                distance = self._estimate_distance(smoothed_rssi)
                all_beacons[location] = {
                    "distance": distance,
                    "rssi": rssi,  # Keep raw RSSI for debugging
                    "smoothed_rssi": smoothed_rssi
                }
                self.logger.debug(f"Found beacon for {location}: RSSI={rssi}, Smoothed={smoothed_rssi}, Distance={distance}")

            # Only change location after minimum consecutive readings
            if (self._consecutive_readings[location] >= BLEConfig.MIN_READINGS_FOR_CHANGE and
                location != self._last_location.get("location")):
                self._last_location_change_time = time.time()
                self._last_location = {
                    "location": location,
                    "distance": self._estimate_distance(smoothed_rssi),
                    "all_beacons": all_beacons
                }
            else:
                # Keep previous location but update beacon data
                self._last_location = {
                    "location": self._last_location.get("location", "unknown"),
                    "distance": self._last_location.get("distance", Distance.UNKNOWN),
                    "all_beacons": all_beacons  # Use new beacon data
                }
            
            self.logger.debug(f"Scan complete - Location: {self._last_location['location']}, Beacons: {len(all_beacons)}")
            return self._last_location
        
    async def start(self) -> None:
        """Starts the location manager"""
        # if PLATFORM != "raspberry-pi":
        #     self.logger.info("Location tracking not available on this platform")
        #     return
            
        # Ensure Bluetooth is powered on before starting
        if not self._ensure_bluetooth_powered():
            self.logger.error("Failed to start location manager: Bluetooth adapter is not powered on")
            return
            
        self._is_running = True
            
        self.logger.info("Location manager started")
        
        # Start discovery scan in background
        if BLEConfig.RUN_STARTUP_SCAN:
            self.logger.info("Starting initial discovery scan in background...")
            asyncio.create_task(self._run_initial_discovery())
        
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
        elif rssi >= BLEConfig.RSSI_VERY_NEAR:
            return Distance.VERY_NEAR
        elif rssi >= BLEConfig.RSSI_NEAR:
            return Distance.NEAR
        elif rssi >= BLEConfig.RSSI_FAR:
            return Distance.FAR
        elif rssi >= BLEConfig.RSSI_VERY_FAR:
            return Distance.VERY_FAR
        else:
            return Distance.UNKNOWN
            
    def _get_strongest_beacon(self, devices: List[Tuple[Tuple[int, int], int]]) -> Optional[Tuple[Tuple[int, int], int]]:
        """Returns the strongest beacon considering hysteresis and equidistant cases"""
        if not devices:
            return None
            
        # Sort by RSSI
        sorted_devices = sorted(devices, key=lambda x: x[1], reverse=True)
        
        # Add bonus to current location if it exists
        current_location = self._last_location.get("location")
        if current_location and current_location != "unknown":
            current_addr = next(
                (addr for addr, loc in BLEConfig.BEACON_LOCATIONS.items() 
                 if loc == current_location), 
                None
            )
            if current_addr:
                sorted_devices = [(addr, rssi + (BLEConfig.CURRENT_LOCATION_RSSI_BONUS if addr == current_addr else 0))
                                for addr, rssi in sorted_devices]
                sorted_devices.sort(key=lambda x: x[1], reverse=True)
        
        # Check if top beacons are within equality threshold
        if len(sorted_devices) >= 2:
            rssi_diff = abs(sorted_devices[0][1] - sorted_devices[1][1])
            if rssi_diff <= BLEConfig.RSSI_EQUALITY_THRESHOLD:
                # If equidistant, maintain current location if it's one of them
                if current_location and current_location != "unknown":
                    current_addr = next(
                        (addr for addr, loc in BLEConfig.BEACON_LOCATIONS.items() 
                         if loc == current_location), 
                        None
                    )
                    if current_addr in [addr for addr, _ in sorted_devices[:2]]:
                        return next(
                            device for device in sorted_devices 
                            if device[0] == current_addr
                        )
                
                # Otherwise, maintain previous strongest if it's one of them
                if self._last_strongest and self._last_strongest[0] in [addr for addr, _ in sorted_devices[:2]]:
                    return next(
                        device for device in sorted_devices 
                        if device[0] == self._last_strongest[0]
                    )
        
        # Update last strongest and return
        self._last_strongest = sorted_devices[0]
        return sorted_devices[0]
        
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