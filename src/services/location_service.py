import asyncio
import logging
from typing import Dict, Any, Optional, Union
from services.service import BaseService
from managers.location_manager import LocationManager
from config import BLEConfig, PLATFORM, Distance

class LocationService(BaseService):
    """Service for tracking location using BLE beacons"""
    def __init__(self, manager):
        super().__init__(manager)
        self.location_manager = LocationManager()
        self._scan_task = None
        self._last_location: Optional[str] = None
        self._last_distances: Dict[str, Dict[str, Union[Distance, int]]] = {}
        
    def _location_changed(self, new_location: str) -> bool:
        """Check if location has changed"""
        return new_location != self._last_location
        
    def _distance_changed(self, location: str, new_info: Dict[str, Any]) -> bool:
        """Check if distance to a location has changed"""
        if location not in self._last_distances:
            return True
            
        return self._last_distances[location]["distance"] != new_info["distance"]
        
    async def _publish_location_change(self, new_location: str):
        """Publish a location change event"""
        await self.publish({
            "type": "location_changed",
            "data": {
                "location": new_location,
                "previous_location": self._last_location
            },
            "producer_name": "location_service"
        })
        self.logger.debug(f"Location changed: {self._last_location} -> {new_location}")
        self._last_location = new_location
        
    async def _publish_proximity_change(self, location: str, new_info: Dict[str, Any]):
        """Publish a proximity change event"""
        previous = self._last_distances.get(location, {})
        await self.publish({
            "type": "proximity_changed",
            "data": {
                "location": location,
                "distance": new_info["distance"],
                "previous_distance": previous.get("distance"),
                "rssi": new_info["rssi"]
            },
            "producer_name": "location_service"
        })
        self.logger.debug(
            f"Proximity changed for {location}: {previous.get('distance')} -> {new_info['distance']} "
            f"(RSSI: {new_info['rssi']})"
        )
        self._last_distances[location] = new_info
        
    async def _handle_beacon_updates(self, all_beacons: Dict[str, Dict[str, Any]]):
        """Process updates for all visible beacons"""
        # Track which beacons we've seen this scan
        seen_beacons = set()
        
        # Process visible beacons
        for location, beacon_info in all_beacons.items():
            seen_beacons.add(location)
            if self._distance_changed(location, beacon_info):
                await self._publish_proximity_change(location, beacon_info)
                
        # Clear state for beacons that are no longer visible
        for location in list(self._last_distances.keys()):
            if location not in seen_beacons:
                previous = self._last_distances[location]
                await self.publish({
                    "type": "proximity_changed",
                    "data": {
                        "location": location,
                        "distance": Distance.UNKNOWN,
                        "previous_distance": previous["distance"],
                        "rssi": None
                    },
                    "producer_name": "location_service"
                })
                self.logger.debug(f"Lost visibility of beacon: {location}")
                del self._last_distances[location]
        
    async def start(self):
        """Start the location service"""
        await super().start()
        self.location_manager.start()
        
        if PLATFORM == "raspberry-pi":
            # Start the scanning loop
            self._scan_task = asyncio.create_task(self._scanning_loop())
            self.logger.info("Location service started")
        else:
            self.logger.info("Location service started in simulation mode")
            
    async def stop(self):
        """Stop the location service"""
        if self._scan_task:
            self._scan_task.cancel()
            try:
                await self._scan_task
            except asyncio.CancelledError:
                pass
                
        self.location_manager.stop()
        await super().stop()
        self.logger.info("Location service stopped")
        
    async def _scanning_loop(self):
        """Main scanning loop that runs continuously"""
        last_unknown_publish = 0  # Track last time we published an unknown location
        
        while True:
            try:
                # Perform a scan
                location_info = self.location_manager.scan_once()
                current_time = asyncio.get_event_loop().time()
                
                new_location = location_info["location"]
                all_beacons = location_info["all_beacons"]
                
                # Handle location updates
                if new_location == "unknown":
                    # Only publish unknown location if:
                    # 1. We had a known location before (actual change to unknown)
                    # 2. Or it's been a while since our last unknown publish AND our last location wasn't unknown
                    should_publish = (
                        (self._last_location is not None and self._last_location != "unknown") or
                        (current_time - last_unknown_publish >= BLEConfig.LOW_POWER_SCAN_INTERVAL and
                         self._last_location != "unknown")
                    )
                    
                    if should_publish:
                        await self._publish_location_change(new_location)
                        last_unknown_publish = current_time
                        
                elif self._location_changed(new_location):
                    # Publish location change for known locations
                    await self._publish_location_change(new_location)
                
                # Handle proximity updates for all beacons
                await self._handle_beacon_updates(all_beacons)
                
                # Get adaptive scan interval
                scan_interval = self.location_manager.get_scan_interval()
                await asyncio.sleep(scan_interval)
                
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.logger.error(f"Error in scanning loop: {e}", exc_info=True)
                await asyncio.sleep(BLEConfig.SCAN_INTERVAL)
                
    async def handle_event(self, event: Dict[str, Any]):
        """Handle incoming events"""
        event_type = event.get("type")
        
        if event_type == "get_location":
            # Respond with current location and all beacon information
            response = {
                "current_location": self._last_location or "unknown",
                "beacons": self._last_distances.copy()
            }
            await self.publish({
                "type": "location_response",
                "data": response,
                "producer_name": "location_service",
                "request_id": event.get("request_id")
            })
            
        elif event_type == "force_scan":
            # Force an immediate scan
            if PLATFORM == "raspberry-pi":
                location_info = self.location_manager.scan_once()
                new_location = location_info["location"]
                all_beacons = location_info["all_beacons"]
                
                # Publish location change
                await self._publish_location_change(new_location)
                # Process all beacons
                await self._handle_beacon_updates(all_beacons) 