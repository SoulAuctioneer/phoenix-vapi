"""
Grandma Pea activity

- When the user says "I can see you", the activity service will start this Grandma Pea activity.

Variations on TTS text:
1. Yaay it's grandma pea! Weee!! We love you grandma!
2. Yippee!! It's Grandma Pea! We missed you SO much!!
3. Grandma!! It's really you! We're over the moon, but here on earth!!
4. Grandma Pea! Grandma Pea! You're our favorite in the whole galaxy!!

Similar to @activity_squealing, but with different TTS text. 

When the activity starts, we:
1. immediately start an LED pattern (one of three random patterns),
2. delay for random 0-2 seconds (configurable)
3. speak a random TTS text
4. once TTS is finished, wait for a random 10-12 seconds (configurable)
5. End the activity

"""

import logging
import asyncio
import random
from services.service import BaseService


class GrandmaPeaActivity(BaseService):
    """
    Service that manages the Grandma Pea activity.
    """
    def __init__(self, service_manager):
        super().__init__(service_manager)
        self._is_active = False
        self._activity_task = None
        
        self._LED_BRIGHTNESS = 0.8
        # IMPORTANT: This value MUST be reflected in `scripts/precache_tts.py`
        # for these phrases to be properly cached.
        self._TTS_STABILITY = 0.6
        
        self._initial_delay_min_sec = 0.0
        self._initial_delay_max_sec = 2.0
        
        self._end_delay_min_sec = 10.0
        self._end_delay_max_sec = 12.0
        
        self._tts_messages = [
            "Yaay it's grandma pea! Weee!! We love you grandma!",
            "Yippee!! It's Grandma Pea! We missed you SO much!!",
            "Grandma!! It's really you! We're over the moon, but here on earth!!",
            "Grandma Pea! Grandma Pea! You're our favorite in the whole galaxy!!"
        ]
        
        self._led_effects = [
            "RAINBOW",
            "MAGICAL_SPELL",
            "SPARKLING_PINK_BLUE"
        ]

    async def _activity_loop(self):
        try:
            # 1. Start a random LED pattern
            led_effect = random.choice(self._led_effects)
            await self.publish({
                "type": "start_led_effect",
                "data": {
                    "effect_name": led_effect,
                    "brightness": self._LED_BRIGHTNESS
                }
            })
            
            # 2. Delay for random 0-2 seconds
            initial_delay = random.uniform(self._initial_delay_min_sec, self._initial_delay_max_sec)
            self.logger.info(f"Initial delay for {initial_delay:.2f} seconds.")
            await asyncio.sleep(initial_delay)
            
            # 3. Speak a random TTS text
            tts_message = random.choice(self._tts_messages)
            tts_finished_event = asyncio.Event()
            
            await self.publish({
                "type": "speak_audio",
                "text": tts_message,
                "on_finish_event": tts_finished_event,
                "stability": self._TTS_STABILITY
            })
            
            await tts_finished_event.wait()
            self.logger.info("TTS finished.")
            
            # 4. Wait for a random 10-12 seconds
            end_delay = random.uniform(self._end_delay_min_sec, self._end_delay_max_sec)
            self.logger.info(f"Waiting for {end_delay:.2f} seconds before ending.")
            await asyncio.sleep(end_delay)
            
            # 5. End the activity
            self.logger.info("Grandma activity finished, publishing ended event.")
            await self.publish({"type": "grandma_activity_ended"})

        except asyncio.CancelledError:
            self.logger.info("Grandma activity loop cancelled.")
        except Exception as e:
            self.logger.error(f"Error in Grandma activity loop: {e}", exc_info=True)
        finally:
            self._is_active = False

    async def start(self):
        """Start the Grandma Pea activity"""
        await super().start()
        if self._is_active:
            self.logger.warning("Grandma activity already active.")
            return
            
        self._is_active = True
        self.logger.info("Starting Grandma activity.")
        
        # Stop any previous LED effect
        await self.publish({
            "type": "stop_led_effect"
        })
        
        self._activity_task = asyncio.create_task(self._activity_loop())
        
    async def stop(self):
        """Stop the Grandma Pea activity"""
        if not self._is_active:
            return

        self.logger.info("Stopping Grandma activity.")
        self._is_active = False
        if self._activity_task:
            self._activity_task.cancel()
            self._activity_task = None
            
        # Stop the LED effect without waiting to prevent deadlocks.
        # This is a 'fire-and-forget' task.
        asyncio.create_task(self.publish({
            "type": "stop_led_effect"
        }))
        
        await super().stop()
        self.logger.info("Grandma activity stopped.")




