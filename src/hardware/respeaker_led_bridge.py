"""
ReSpeaker LED Bridge for LEDManager.

This module provides a high-performance bridge to augment an existing `LEDManager`
(which controls NeoPixel rings) with support for the ReSpeaker 4-Mic Array's
onboard LEDs. It enables a unified, dual-LED system where both LED types work
in concert.

Architecture:
The bridge uses an efficient, event-driven "push" model that is optimized for
resource-constrained devices like the Raspberry Pi Zero 2 W.
- It hooks into the `LEDManager`'s `pixels.show()` method.
- It only consumes CPU and power when the NeoPixel LEDs are actually updated.
- It has zero idle cost, which is critical for battery-powered devices.
- Updates for both LED systems are perfectly synchronized.

Primary Interface:
The main entry point is the `augment_led_manager()` function, which takes an
instance of `LEDManager` and seamlessly adds ReSpeaker support to it.
"""

import usb.core
import usb.util
import threading
import queue
import time
from typing import List, Tuple
from enum import Enum, auto
from config import LEDConfig


class MappingMode(Enum):
    """How to map LEDManager frames to ReSpeaker LEDs"""
    MIRROR_OUTER = auto()      # Mirror the outer NeoPixel ring
    MIRROR_INNER = auto()      # Mirror the inner NeoPixel ring
    SAMPLE_BOTH = auto()       # Sample from both rings
    AVERAGE_BOTH = auto()      # Average colors from both rings
    COMPLEMENT = auto()        # Show complementary patterns
    HIGHLIGHT = auto()         # Highlight/accent the main effect


class ReSpeakerLEDBridge:
    """
    Manages the connection and command dispatch to the ReSpeaker USB device.

    This class is the core worker of the bridge. It handles:
    - Low-level USB communication in a dedicated, non-blocking thread.
    - A command queue for sending frames and brightness updates.
    - Sampling and mapping pixel data from the `LEDManager`.
    - Graceful handling of USB connection errors and device presence.

    This class is not typically instantiated directly. Instead, the
    `augment_led_manager()` function should be used.
    """
    
    RESPEAKER_LEDS = 12
    USB_VID = 0x2886
    USB_PID = 0x0018
    TIMEOUT = 8000
    
    # USB Commands
    CMD_SHOW = 6
    CMD_SET_BRIGHTNESS = 0x20
    
    def __init__(self, led_manager, mapping_mode: MappingMode = MappingMode.MIRROR_OUTER):
        self.led_manager = led_manager
        self.mapping_mode = mapping_mode
        self.enabled = True
        self.dev = None
        self._last_brightness = -1.0 # Initialize to an invalid value to force first update
        
        self._command_queue = queue.Queue()
        self._running = True
        
        self._connect()
        
        # Start a single worker thread for non-blocking USB communication
        self._usb_thread = threading.Thread(target=self._usb_worker)
        self._usb_thread.daemon = True
        self._usb_thread.start()
    
    def _connect(self):
        """Connect to ReSpeaker device, disabling if not found."""
        if not self.enabled: return
        try:
            self.dev = usb.core.find(idVendor=self.USB_VID, idProduct=self.USB_PID)
            if self.dev:
                print("ReSpeaker LED Bridge: Connected to ReSpeaker 4-Mic Array.")
            else:
                print("ReSpeaker LED Bridge: ReSpeaker not found, bridge is disabled.")
                self.enabled = False
        except Exception as e:
            print(f"ReSpeaker LED Bridge: USB connection error: {e}. Bridge is disabled.")
            self.enabled = False
            self.dev = None
    
    def _usb_worker(self):
        """Worker thread for processing the USB command queue."""
        while self._running:
            try:
                cmd, data = self._command_queue.get(timeout=1)
                if self.dev and self.enabled:
                    self.dev.ctrl_transfer(
                        usb.util.CTRL_OUT | usb.util.CTRL_TYPE_VENDOR | usb.util.CTRL_RECIPIENT_DEVICE,
                        0, cmd, 0x1C, data, self.TIMEOUT
                    )
            except queue.Empty:
                continue
            except usb.core.USBError as e:
                print(f"ReSpeaker LED Bridge: USB error: {e}. Attempting to reconnect.")
                self._connect()
                # Give it a moment before continuing
                time.sleep(5)
            except Exception as e:
                print(f"ReSpeaker LED Bridge: Unhandled error in USB worker: {e}")
                self.enabled = False # Disable on unknown error
                
    def update(self):
        """
        Public method called to trigger a frame update on the ReSpeaker.
        This should be called from the wrapped `show()` method in LEDManager.
        """
        if not self.enabled or not hasattr(self.led_manager, 'pixels'):
            return
            
        # Set the hardware brightness on the ReSpeaker, if it has changed
        self._set_hardware_brightness()
            
        frame = self._sample_leds()
        self._send_frame(frame)
    
    def _set_hardware_brightness(self):
        """Checks for brightness changes and sends a hardware command if needed."""
        # Get the effective brightness from the LEDManager
        base_brightness = self.led_manager.pixels.brightness if hasattr(self.led_manager.pixels, 'brightness') else 1.0
        
        # Apply the boost and clamp the value between 0.0 and 1.0
        boosted_brightness = min(1.0, max(0.0, base_brightness * LEDConfig.RESPEAKER_BRIGHTNESS_BOOST))
        
        # Use a small tolerance for float comparison to avoid unnecessary USB commands
        if abs(boosted_brightness - self._last_brightness) > 0.01:
            # The ReSpeaker v2 hardware brightness is controlled by a value from 0-255
            brightness_val = int(boosted_brightness * 255)
            self._command_queue.put((self.CMD_SET_BRIGHTNESS, [brightness_val]))
            self._last_brightness = boosted_brightness

    def _sample_leds(self) -> List[Tuple[int, int, int]]:
        """Sample LEDManager pixels based on the current mapping mode."""
        pixels = self.led_manager.pixels
        
        if hasattr(self.led_manager, 'ring1_pixels'):
            num_outer = len(self.led_manager.ring1_pixels)
            num_inner = len(self.led_manager.ring2_pixels)
            has_dual_rings = True
        else:
            num_outer = len(pixels.n) if hasattr(pixels, 'n') else 0
            num_inner = 0
            has_dual_rings = False
        
        # Select mapping function
        mapping_functions = {
            MappingMode.MIRROR_OUTER: lambda: self._mirror_ring(pixels, 0, num_outer),
            MappingMode.MIRROR_INNER: lambda: self._mirror_ring(pixels, num_outer, num_inner) if has_dual_rings else [],
            MappingMode.SAMPLE_BOTH: lambda: self._sample_both(pixels, num_outer, num_inner) if has_dual_rings else [],
            MappingMode.AVERAGE_BOTH: lambda: self._average_both(pixels, num_outer, num_inner) if has_dual_rings else [],
            MappingMode.COMPLEMENT: lambda: self._complement_ring(pixels, 0, num_outer),
            MappingMode.HIGHLIGHT: lambda: self._highlight_ring(pixels, 0, num_outer),
        }
        
        # Get frame from mapping function, fallback to mirroring outer ring
        frame = mapping_functions.get(self.mapping_mode, mapping_functions[MappingMode.MIRROR_OUTER])()
        return frame if frame else self._mirror_ring(pixels, 0, num_outer)

    def _mirror_ring(self, pixels, start_idx, ring_size):
        if ring_size == 0: return [(0,0,0)] * self.RESPEAKER_LEDS
        return [pixels[start_idx + int(i * ring_size / self.RESPEAKER_LEDS)] for i in range(self.RESPEAKER_LEDS)]

    def _sample_both(self, pixels, num_outer, num_inner):
        outer = self._mirror_ring(pixels, 0, num_outer)
        inner = self._mirror_ring(pixels, num_outer, num_inner)
        return [outer[i] if i % 2 == 0 else inner[i] for i in range(self.RESPEAKER_LEDS)]

    def _average_both(self, pixels, num_outer, num_inner):
        outer = self._mirror_ring(pixels, 0, num_outer)
        inner = self._mirror_ring(pixels, num_outer, num_inner)
        return [tuple((o + i) // 2 for o, i in zip(c1, c2)) for c1, c2 in zip(outer, inner)]

    def _complement_ring(self, pixels, start_idx, ring_size):
        original = self._mirror_ring(pixels, start_idx, ring_size)
        return [(255 - r, 255 - g, 255 - b) for r, g, b in original]

    def _highlight_ring(self, pixels, start_idx, ring_size):
        original = self._mirror_ring(pixels, start_idx, ring_size)
        total_brightness = sum(sum(c) for c in original)
        if total_brightness == 0: return original
        
        avg_brightness = total_brightness / (len(original) * 3)
        highlighted = []
        for r, g, b in original:
            brightness = (r + g + b) / 3
            if brightness > avg_brightness * 1.2:
                highlighted.append((min(255, int(r*1.5)), min(255, int(g*1.5)), min(255, int(b*1.5))))
            else:
                highlighted.append((int(r*0.4), int(g*0.4), int(b*0.4)))
        return highlighted

    def _send_frame(self, colors: List[Tuple[int, int, int]]):
        """Queue a frame of raw colors to be sent to the ReSpeaker."""
        data = []
        # Brightness is now handled by the hardware via the _set_hardware_brightness method.
        # We send raw, unscaled color values.
        for r, g, b in colors:
            # The ReSpeaker v2 firmware expects a 4-byte package for each LED: [R, G, B, 0]
            data.extend([r, g, b, 0])
        self._command_queue.put((self.CMD_SHOW, data))

    def set_mapping_mode(self, mode: MappingMode):
        self.mapping_mode = mode

    def enable(self):
        if not self.enabled:
            self.enabled = True
            self._connect()

    def disable(self):
        if self.enabled:
            self.enabled = False
            self.clear()

    def clear(self):
        if self.dev:
            self._send_frame([(0, 0, 0)] * self.RESPEAKER_LEDS)

    def close(self):
        if self._running:
            self._running = False
            self.clear()
            self._command_queue.put((None, None)) # Sentinel to unblock worker
            if self._usb_thread.is_alive():
                self._usb_thread.join(timeout=1.0)
            if self.dev:
                usb.util.dispose_resources(self.dev)

def augment_led_manager(led_manager, mapping_mode: MappingMode = MappingMode.MIRROR_OUTER):
    """
    Augments an LEDManager instance with ReSpeaker support.

    This is the main entry point for the bridge. It takes an existing,
    initialized LEDManager and wraps its methods to automatically control the
    ReSpeaker LEDs in sync with the NeoPixel rings.

    This function modifies the `led_manager` object in-place.

    Args:
        led_manager: An instance of `LEDManager` or `LEDManagerRings`.
        mapping_mode: The initial `MappingMode` to use for displaying effects
                      on the ReSpeaker LEDs.

    Returns:
        An instance of `ReSpeakerLEDBridge` if the hardware is found,
        otherwise `None`. The returned instance can be used to dynamically
        change mapping modes or disable the bridge.

    Example:
        >>> from managers.led_manager import LEDManager
        >>> from hardware.respeaker_led_bridge import augment_led_manager, MappingMode
        >>>
        >>> led_manager = LEDManager()
        >>> bridge = augment_led_manager(led_manager)
        >>>
        >>> # Effects now appear on both NeoPixels and ReSpeaker LEDs
        >>> led_manager.start_effect('RAINBOW')
        >>>
        >>> # Dynamically change how the ReSpeaker displays the effect
        >>> if bridge:
        ...     bridge.set_mapping_mode(MappingMode.HIGHLIGHT)

    Mapping Modes (`MappingMode` enum):
    - MIRROR_OUTER: Copies the outer ring's pattern (default).
    - MIRROR_INNER: Copies the inner ring's pattern.
    - SAMPLE_BOTH: Interleaves pixels from both rings.
    - AVERAGE_BOTH: Blends the colors of both rings.
    - COMPLEMENT: Shows opposite colors for high-contrast feedback.
    - HIGHLIGHT: Emphasizes the brightest spots of the effect.
    """
    bridge = ReSpeakerLEDBridge(led_manager, mapping_mode)
    if not bridge.enabled:
        print("Could not initialize ReSpeaker bridge. Continuing without ReSpeaker LEDs.")
        return None
        
    led_manager._respeaker_bridge = bridge

    # Wrap the pixels.show() method to trigger the bridge update
    if hasattr(led_manager.pixels, 'show'):
        original_show = led_manager.pixels.show
        def show_all():
            original_show()
            bridge.update()
        led_manager.pixels.show = show_all
    
    # Wrap the clear() method to also clear the ReSpeaker
    original_clear = led_manager.clear
    def clear_all():
        original_clear()
        bridge.clear()
    led_manager.clear = clear_all

    # Ensure the bridge is closed when the app shuts down
    import atexit
    atexit.register(bridge.close)
    
    return bridge 