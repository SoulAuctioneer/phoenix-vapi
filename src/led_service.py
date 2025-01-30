import logging
import asyncio
from typing import List, Tuple
import board
import neopixel

class LEDService:
    """Service for controlling addressable LEDs"""
    def __init__(self, manager, pin=board.D18, num_pixels=16, brightness=0.5):
        super().__init__(manager)
        self.pixels = neopixel.NeoPixel(
            pin, num_pixels, brightness=brightness, auto_write=False)
        self.animation_task = None
        
    async def start(self):
        """Start the LED service"""
        await super().start()
        # Set initial state (all off)
        self.pixels.fill((0, 0, 0))
        self.pixels.show()
        
    async def stop(self):
        """Stop the LED service and turn off all LEDs"""
        if self.animation_task:
            self.animation_task.cancel()
            try:
                await self.animation_task
            except asyncio.CancelledError:
                pass
        self.pixels.fill((0, 0, 0))
        self.pixels.show()
        await super().stop()
        
    async def handle_event(self, event: dict):
        """Handle events from other services"""
        event_type = event.get("type")
        
        if event_type == "interaction_started":
            # Start "listening" animation
            self.start_animation(self.listening_animation())
        elif event_type == "interaction_stopped":
            # Stop any running animation
            if self.animation_task:
                self.animation_task.cancel()
                self.pixels.fill((0, 0, 0))
                self.pixels.show()
                
    def start_animation(self, animation_coro):
        """Start a new LED animation, canceling any existing one"""
        if self.animation_task:
            self.animation_task.cancel()
        self.animation_task = asyncio.create_task(animation_coro)
        
    async def listening_animation(self):
        """Pulsing blue animation to indicate listening"""
        try:
            while True:
                # Pulse from dim to bright blue
                for i in range(0, 100, 2):
                    brightness = i / 100.0
                    self.pixels.fill((0, 0, int(255 * brightness)))
                    self.pixels.show()
                    await asyncio.sleep(0.02)
                    
                for i in range(100, 0, -2):
                    brightness = i / 100.0
                    self.pixels.fill((0, 0, int(255 * brightness)))
                    self.pixels.show()
                    await asyncio.sleep(0.02)
        except asyncio.CancelledError:
            # Clean up on animation cancel
            self.pixels.fill((0, 0, 0))
            self.pixels.show()
            raise
            
    async def set_color(self, color: Tuple[int, int, int]):
        """Set all LEDs to a specific color"""
        self.pixels.fill(color)
        self.pixels.show()
        
    async def set_pixels(self, colors: List[Tuple[int, int, int]]):
        """Set individual LED colors"""
        for i, color in enumerate(colors):
            if i < len(self.pixels):
                self.pixels[i] = color
        self.pixels.show() 