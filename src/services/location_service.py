import time
import logging
import asyncio
from typing import Dict, Any, Optional, Union
from services.service import BaseService
from managers.location_manager import LocationManager
from config import BLEConfig, PLATFORM, Distance, get_filter_logger

class LocationService(BaseService):
    """Service for managing location tracking and updates"""
    def __init__(self, service_manager):
        super().__init__(service_manager)
        self.logger = get_filter_logger(__name__)
        self._location_manager = LocationManager()
        self._scanning_task: Optional[asyncio.Task] = None
        self._is_running = False
        self._last_unknown_publish = 0
        self._last_location: str = "unknown"
        self._last_distances: Dict[str, Dict[str, Union[Distance, int]]] = {}
        self._last_all_beacons_update_time: float = 0.0
        
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
                "rssi": new_info["rssi"],
                "smoothed_rssi": new_info.get("smoothed_rssi", new_info["rssi"])
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
            # Calculate current distance based on smoothed RSSI
            smoothed_rssi = beacon_info.get("smoothed_rssi", beacon_info["rssi"])
            current_distance = self._location_manager._estimate_distance(smoothed_rssi)
            beacon_info["distance"] = current_distance
            beacon_info["rssi"] = smoothed_rssi  # Use smoothed RSSI for consistency
            
            if self._distance_changed(location, beacon_info):
                await self._publish_proximity_change(location, beacon_info)
            else:
                # Even if we don't publish an event, update the stored state
                self._last_distances[location] = beacon_info.copy()
                
        # Check beacons that are no longer visible
        for location in list(self._last_distances.keys()):
            if location not in seen_beacons:
                # Only publish unknown state after minimum empty scans
                if self._location_manager._beacon_empty_counts[location] >= BLEConfig.MIN_EMPTY_SCANS_FOR_UNKNOWN:
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
                    self.logger.debug(f"Lost visibility of beacon: {location} after {self._location_manager._beacon_empty_counts[location]} empty scans")
                    del self._last_distances[location]
        
    async def _scanning_loop(self) -> None:
        """Main scanning loop that periodically checks location"""
        while self._is_running:
            try:
                # Get current scan interval based on activity
                scan_interval = self._location_manager.get_scan_interval()
                
                # Perform scan
                location_info = await self._location_manager.scan_once()
                new_location = location_info["location"]
                all_beacons = location_info["all_beacons"]
                
                # Handle location updates
                should_publish = True
                # if new_location == "unknown":
                #     current_time = time.time()
                #     if current_time - self._last_unknown_publish < BLEConfig.UNKNOWN_PUBLISH_INTERVAL:
                #         should_publish = False
                #     else:
                #         self._last_unknown_publish = current_time
                        
                if should_publish and self._location_changed(new_location):
                    await self._publish_location_change(new_location)
                    
                # Handle proximity updates for all beacons
                await self._handle_beacon_updates(all_beacons)

                # Periodically publish all beacon data
                current_time = time.time()
                if all_beacons and (current_time - self._last_all_beacons_update_time) >= BLEConfig.ALL_BEACONS_UPDATE_INTERVAL:
                    await self.publish({
                        "type": "all_beacons_update",
                        "data": { "beacons": all_beacons },
                        "producer_name": "location_service"
                    })
                    self.logger.debug(f"Published all_beacons_update with {len(all_beacons)} beacons")
                    self._last_all_beacons_update_time = current_time
                
                # Sleep until next scan
                await asyncio.sleep(scan_interval)
                
            except Exception as e:
                self.logger.error(f"Error in scanning loop: {e}")
                await asyncio.sleep(BLEConfig.ERROR_RETRY_INTERVAL)
                
    async def start(self) -> None:
        """Starts the location service"""
        if self._is_running:
            self.logger.warning("Location service is already running")
            return
            
        self._is_running = True
        await self._location_manager.start()
        
        # Start scanning loop in background task
        self._scanning_task = asyncio.create_task(self._scanning_loop())
        self.logger.info("Location service started")
        
    async def stop(self) -> None:
        """Stops the location service"""
        if not self._is_running:
            return
            
        self._is_running = False
        if self._scanning_task:
            self._scanning_task.cancel()
            try:
                await self._scanning_task
            except asyncio.CancelledError:
                pass
            self._scanning_task = None
            
        await self._location_manager.stop()
        self.logger.info("Location service stopped")
        
    def get_current_location(self) -> Dict[str, Any]:
        """Returns the current location information"""
        return self._location_manager.get_current_location()
        
    @property
    def is_running(self) -> bool:
        """Returns whether the location service is running"""
        return self._is_running
        
    async def handle_event(self, event: Dict[str, Any]):
        """Handle incoming events"""
        event_type = event.get("type")
        
        if event_type == "force_scan":
            # Force an immediate scan
            if PLATFORM == "raspberry-pi":
                try:
                    location_info = await self._location_manager.scan_once()
                    new_location = location_info["location"]
                    all_beacons = location_info["all_beacons"]
                    
                    # Only publish if there's a change
                    if self._location_changed(new_location):
                        await self._publish_location_change(new_location)
                    # Process all beacons
                    await self._handle_beacon_updates(all_beacons)
                except Exception as e:
                    self.logger.error(f"Error during forced scan: {e}")
                    # Respond with error
                    await self.publish({
                        "type": "scan_error",
                        "data": {"error": str(e)},
                        "producer_name": "location_service",
                        "request_id": event.get("request_id")
                    }) 