"""
Service for monitoring battery status using the MAX17048 LiPoly/LiIon fuel gauge.
Provides battery voltage, charge percentage and various battery-related alerts.
"""

import logging
import asyncio
from typing import Dict, Any, Optional
import board
import adafruit_max1704x
from services.service import BaseService, ServiceManager
from config import BatteryConfig

class BatteryService(BaseService):
    """
    Service for monitoring battery status using MAX17048.
    Provides battery voltage, charge percentage, and battery alerts.
    Publishes battery status updates and alert events to the system.
    
    Features:
    - Adaptive monitoring intervals based on battery state
    - Hysteresis for alert prevention
    - Configurable thresholds and check intervals
    - Power saving with hibernation mode
    - Activity-based wake-up thresholds
    
    Notes:
    - Quick start feature allows instant auto-calibration but should not be used
      when the battery is first plugged in or under heavy load
    - Hibernation mode reduces ADC reading frequency for power saving
    - Activity threshold determines voltage change needed to exit hibernation
    - Analog comparator can be disabled if battery removal detection isn't needed
    - Service will continue running in a dormant state if no battery monitor is detected
    """
    
    def __init__(self, service_manager: ServiceManager):
        super().__init__(service_manager)
        self.max17: Optional[adafruit_max1704x.MAX17048] = None
        self._monitor_task: Optional[asyncio.Task] = None
        self._last_voltage: float = 0.0
        self._last_charge: float = 0.0
        self._last_hibernating: bool = False
        self._is_charging: bool = False
        self._last_charging_check_voltage: float = 0.0
        # Add tracking for time estimates
        self._last_charge_time: Optional[float] = None
        self._charge_rate: Optional[float] = None  # Percent per hour
        
    async def start(self):
        """Initialize and start the battery monitoring service"""
        await super().start()
        
        try:
            # Initialize I2C and MAX17048
            i2c = board.I2C()  # uses board.SCL and board.SDA
            self.max17 = adafruit_max1704x.MAX17048(i2c)
            
            # Log device info
            self.logger.info(
                f"Found MAX1704x with chip version {hex(self.max17.chip_version)} "
                f"and id {hex(self.max17.chip_id)}"
            )
            
            # Configure power saving features
            if BatteryConfig.DISABLE_ANALOG_COMPARATOR:
                self.max17.comparator_disabled = True
                self.logger.info("Disabled analog comparator for power saving")
            else:
                self.logger.info("Analog comparator enabled for battery removal detection")
                
            # Configure reset voltage
            self.max17.reset_voltage = BatteryConfig.RESET_VOLTAGE
            self.logger.info(
                f"Reset voltage = {self.max17.reset_voltage:.1f}V "
                "(threshold for battery removal detection)"
            )
            
            # Configure hibernation thresholds
            self.max17.activity_threshold = BatteryConfig.ACTIVITY_THRESHOLD
            self.max17.hibernation_threshold = BatteryConfig.HIBERNATION_THRESHOLD
            self.logger.info(
                f"Hibernation config: activity threshold={self.max17.activity_threshold:.2f}V, "
                f"hibernation threshold={self.max17.hibernation_threshold:.1f}%"
            )
            
            # Configure alert thresholds
            self.max17.voltage_alert_min = BatteryConfig.VOLTAGE_ALERT_MIN
            self.max17.voltage_alert_max = BatteryConfig.VOLTAGE_ALERT_MAX
            self.logger.info(
                f"Voltage alerts: min={self.max17.voltage_alert_min:.2f}V, "
                f"max={self.max17.voltage_alert_max:.2f}V"
            )
            
            # Optional quick start for calibration
            if BatteryConfig.ENABLE_QUICK_START:
                self.logger.warning(
                    "Performing quick start calibration. Note: This should not be used "
                    "when battery is first connected or under heavy load."
                )
                self.max17.quick_start = True
            
            # Initialize last known values
            if self.max17:
                self._last_voltage = self.max17.cell_voltage
                self._last_charge = self.max17.cell_percent
                self._last_hibernating = self.max17.hibernating
                self._last_charging_check_voltage = self._last_voltage  # Initialize with actual voltage
                self.logger.info(
                    f"Initial state: voltage={self._last_voltage:.2f}V, "
                    f"charge={self._last_charge:.1f}%, "
                    f"hibernating={self._last_hibernating}"
                )
            
            # Start monitoring task
            self._monitor_task = asyncio.create_task(self._battery_monitor_loop())
            
            self.logger.info("BatteryService started successfully with active monitoring")
            
        except (OSError, ValueError) as e:
            self.logger.warning(
                f"Battery monitor not detected ({str(e)}). "
                "Service will continue in dormant state."
            )
            # Don't raise the exception - let the service continue without active monitoring
            
        except Exception as e:
            self.logger.error(f"Unexpected error initializing battery monitor: {str(e)}")
            # Only raise for unexpected errors
            raise
        
    async def stop(self):
        """Stop the battery monitoring service"""
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None
            
        # Wake up from hibernation before stopping if we have a device
        if self.max17 and self.max17.hibernating:
            self.logger.info("Waking from hibernation before shutdown")
            self.max17.wake()
            
        await super().stop()
        self.logger.info("BatteryService stopped")
        
    def _update_charging_state(self, voltage: float) -> None:
        """Update charging state based on voltage changes
        
        Args:
            voltage: Current battery voltage
        """
        # Use different thresholds for detecting start vs end of charging
        if voltage > self._last_charging_check_voltage + BatteryConfig.CHARGING_START_HYSTERESIS:
            if not self._is_charging:
                self.logger.info(
                    f"Charging detected: voltage increased from {self._last_charging_check_voltage:.3f}V "
                    f"to {voltage:.3f}V (+{voltage - self._last_charging_check_voltage:.3f}V)"
                )
                self._is_charging = True
        elif voltage < self._last_charging_check_voltage - BatteryConfig.CHARGING_STOP_HYSTERESIS:
            if self._is_charging:
                self.logger.info(
                    f"Charging stopped: voltage decreased from {self._last_charging_check_voltage:.3f}V "
                    f"to {voltage:.3f}V (-{self._last_charging_check_voltage - voltage:.3f}V)"
                )
                self._is_charging = False
                
        # Always update last voltage to track small changes
        self._last_charging_check_voltage = voltage
        
    def _update_charge_rate(self, current_charge: float, current_time: float) -> None:
        """Update charge/discharge rate calculation
        
        Args:
            current_charge: Current battery charge percentage
            current_time: Current time in seconds
        """
        if self._last_charge_time is None:
            self._last_charge_time = current_time
            return
            
        # Calculate time difference in hours
        time_diff = (current_time - self._last_charge_time) / 3600.0
        if time_diff < 0.1:  # Require at least 6 minutes between measurements
            return
            
        # Calculate charge rate in percent per hour
        charge_diff = current_charge - self._last_charge
        rate = charge_diff / time_diff
        
        # Update or initialize moving average of charge rate
        if self._charge_rate is None:
            self._charge_rate = rate
        else:
            # Use exponential moving average
            alpha = 0.3  # Weight for new values
            self._charge_rate = (alpha * rate) + ((1 - alpha) * self._charge_rate)
            
        self._last_charge_time = current_time
        
        # Log significant rate changes
        if abs(self._charge_rate) > 0.1:  # More than 0.1% per hour
            direction = "charging" if self._charge_rate > 0 else "discharging"
            self.logger.debug(
                f"Battery {direction} at {abs(self._charge_rate):.1f}% per hour "
                f"(current charge: {current_charge:.1f}%)"
            )
            
    def _estimate_time_remaining(self, current_charge: float) -> Optional[float]:
        """Estimate time remaining until empty/full in hours
        
        Args:
            current_charge: Current battery charge percentage
            
        Returns:
            float: Estimated hours remaining until empty/full, or None if cannot estimate
        """
        if self._charge_rate is None or abs(self._charge_rate) < 0.1:
            return None
            
        if self._is_charging:
            if current_charge >= 100:
                return 0
            return (100 - current_charge) / self._charge_rate
        else:
            if current_charge <= 0:
                return 0
            return current_charge / -self._charge_rate
            
    def _determine_check_interval(self, charge_percent: float, voltage: float) -> float:
        """Determine the appropriate check interval based on battery state
        
        Args:
            charge_percent: Current battery charge percentage
            voltage: Current battery voltage
            
        Returns:
            float: The appropriate check interval in seconds
        """
        # Use longer interval if no device or hibernating
        if not self.max17:
            return BatteryConfig.NORMAL_CHECK_INTERVAL * 4
        if self.max17.hibernating:
            return BatteryConfig.NORMAL_CHECK_INTERVAL * 2
            
        # Use shorter interval when charging
        if self._is_charging:
            return BatteryConfig.CHARGING_CHECK_INTERVAL
            
        # Use shorter interval for low battery states
        if charge_percent <= BatteryConfig.CRITICAL_BATTERY_THRESHOLD:
            return BatteryConfig.LOW_BATTERY_CHECK_INTERVAL
        elif charge_percent <= BatteryConfig.LOW_BATTERY_THRESHOLD:
            return BatteryConfig.LOW_BATTERY_CHECK_INTERVAL
            
        # Default to normal interval
        return BatteryConfig.NORMAL_CHECK_INTERVAL
        
    def _should_publish_update(self, voltage: float, charge_percent: float) -> bool:
        """Determine if we should publish a status update based on changes
        
        Args:
            voltage: Current battery voltage
            charge_percent: Current battery charge percentage
            
        Returns:
            bool: True if we should publish an update
        """
        # Always publish if charging state changed
        if self._is_charging != (voltage > self._last_voltage + BatteryConfig.VOLTAGE_HYSTERESIS):
            return True
            
        # Always publish if hibernation state changed
        if self.max17.hibernating != self._last_hibernating:
            self._last_hibernating = self.max17.hibernating
            return True
            
        # Publish if voltage changed significantly
        if abs(voltage - self._last_voltage) >= BatteryConfig.VOLTAGE_HYSTERESIS:
            return True
            
        # Publish if charge changed significantly
        if abs(charge_percent - self._last_charge) >= BatteryConfig.CHARGE_HYSTERESIS:
            return True
            
        return False
        
    async def _battery_monitor_loop(self):
        """Main monitoring loop that checks battery status and publishes updates"""
        try:
            while True:
                if not self.max17:
                    await asyncio.sleep(BatteryConfig.NORMAL_CHECK_INTERVAL)
                    continue
                    
                # Get current battery status
                voltage = self.max17.cell_voltage
                charge_percent = self.max17.cell_percent
                current_time = asyncio.get_event_loop().time()
                
                # Update charging state and charge rate
                self._update_charging_state(voltage)
                self._update_charge_rate(charge_percent, current_time)
                
                # Calculate time estimate
                time_remaining = self._estimate_time_remaining(charge_percent)
                
                # Always publish if charging state changes
                should_publish = self._should_publish_update(voltage, charge_percent)
                
                # Determine if we should publish an update
                if should_publish:
                    # Build status update with time estimates
                    status_update = {
                        "type": "battery_status_update",
                        "voltage": voltage,
                        "charge_percent": charge_percent,
                        "hibernating": self.max17.hibernating,
                        "is_charging": self._is_charging,
                    }
                    
                    # Add rate and time estimates if available
                    if self._charge_rate is not None:
                        status_update["charge_rate"] = self._charge_rate  # Percent per hour
                    if time_remaining is not None:
                        status_update["time_remaining"] = time_remaining  # Hours
                        
                    # Publish update
                    await self.publish(status_update)
                    
                    # Update last known values
                    self._last_voltage = voltage
                    self._last_charge = charge_percent
                
                # Check and publish alerts if active
                if self.max17.active_alert:
                    alerts = []
                    
                    if self.max17.reset_alert:
                        alerts.append("reset")
                        self.max17.reset_alert = False
                        
                    if self.max17.voltage_high_alert:
                        alerts.append("voltage_high")
                        self.max17.voltage_high_alert = False
                        
                    if self.max17.voltage_low_alert:
                        alerts.append("voltage_low")
                        self.max17.voltage_low_alert = False
                        
                    if self.max17.voltage_reset_alert:
                        alerts.append("voltage_reset")
                        self.max17.voltage_reset_alert = False
                        
                    if self.max17.SOC_low_alert:
                        alerts.append("charge_low")
                        self.max17.SOC_low_alert = False
                        
                    if self.max17.SOC_change_alert:
                        alerts.append("charge_changed")
                        self.max17.SOC_change_alert = False
                    
                    if alerts:  # Only publish if we have alerts
                        await self.publish({
                            "type": "battery_alert",
                            "alerts": alerts,
                            "voltage": voltage,
                            "charge_percent": charge_percent
                        })
                
                # Determine next check interval
                check_interval = self._determine_check_interval(charge_percent, voltage)
                await asyncio.sleep(check_interval)
                
        except asyncio.CancelledError:
            self.logger.info("Battery monitoring task cancelled")
            raise
        except Exception as e:
            self.logger.error(f"Error in battery monitoring loop: {str(e)}")
            raise
            
    async def handle_event(self, event: Dict[str, Any]):
        """Handle incoming events from other services
        
        Currently no events are handled, but could be extended to handle
        configuration changes or monitoring control events.
        """
        pass  # No events handled currently 