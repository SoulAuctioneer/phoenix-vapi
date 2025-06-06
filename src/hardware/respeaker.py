"""
Low-level driver for the ReSpeaker 4-Mic Array LED ring.

This module provides direct control over the ReSpeaker's onboard APA102 LEDs
via its USB vendor-specific commands. It allows for setting individual pixels
and running a small set of pre-programmed hardware effects (listen, speak, etc.).

Note:
This is a low-level driver. For integrating ReSpeaker LEDs with the project's
main `LEDManager` (which controls NeoPixel rings), it is highly recommended to use
the `hardware.respeaker_led_bridge.py` module instead. The bridge provides a
more powerful, flexible, and efficient way to create unified dual-LED effects.
"""
import usb.core
import usb.util


class PixelRing:
    TIMEOUT = 8000

    def __init__(self, dev):
        self.dev = dev

    def all_off(self):
        self.off()
        self.set_vad_led(0)

    def trace(self):
        self.write(0)

    def mono(self, color):
        self.write(1, [(color >> 16) & 0xFF, (color >> 8) & 0xFF, color & 0xFF, 0])
    
    def set_color(self, rgb=None, r=0, g=0, b=0):
        if rgb:
            self.mono(rgb)
        else:
            self.write(1, [r, g, b, 0])

    def off(self):
        self.mono(0)

    def listen(self, direction=None):
        self.write(2)

    wakeup = listen

    def speak(self):
        self.write(3)

    def think(self):
        self.write(4)

    wait = think

    def spin(self):
        self.write(5)

    def show(self, data):
        self.write(6, data)

    customize = show
        
    def set_brightness(self, brightness):
        self.write(0x20, [brightness])
    
    def set_color_palette(self, a, b):
        self.write(0x21, [(a >> 16) & 0xFF, (a >> 8) & 0xFF, a & 0xFF, 0, (b >> 16) & 0xFF, (b >> 8) & 0xFF, b & 0xFF, 0])

    # Voice Activity Detection LED (VAD)
    def set_vad_led(self, state):
        self.write(0x22, [state])

    def set_volume_leds(self, volume):
        # NOTE This is just the LED effect for showing volume, not the actual volume of the speaker
        self.write(0x23, [volume])

    def change_pattern(self, pattern=None):
        print('Changing pattern is not yet supported')

    def write(self, cmd, data=[0]):
        self.dev.ctrl_transfer(
            usb.util.CTRL_OUT | usb.util.CTRL_TYPE_VENDOR | usb.util.CTRL_RECIPIENT_DEVICE,
            0, cmd, 0x1C, data, self.TIMEOUT)

    def close(self):
        """
        close the interface
        """
        usb.util.dispose_resources(self.dev)


def find(vid=0x2886, pid=0x0018):
    dev = usb.core.find(idVendor=vid, idProduct=pid)
    if not dev:
        return

    # configuration = dev.get_active_configuration()

    # interface_number = None
    # for interface in configuration:
    #     interface_number = interface.bInterfaceNumber

    #     if dev.is_kernel_driver_active(interface_number):
    #         dev.detach_kernel_driver(interface_number)

    return PixelRing(dev)


def disable_leds():
    pixel_ring = find()
    pixel_ring.all_off()


if __name__ == '__main__':
    import time

    pixel_ring = find()

    while True:
        try:
            pixel_ring.wakeup(180)
            time.sleep(3)
            pixel_ring.listen()
            time.sleep(3)
            pixel_ring.think()
            time.sleep(3)
            pixel_ring.set_volume_leds(8)
            time.sleep(3)
            pixel_ring.off()
            time.sleep(3)
        except KeyboardInterrupt:
            break

    pixel_ring.off()
