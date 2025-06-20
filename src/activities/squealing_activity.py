"""Service for managing the squealing activity state."""

import logging
import asyncio
import random
from typing import Dict, Any
from services.service import BaseService
from managers.accelerometer_manager import SimplifiedState

moving_states = [
    SimplifiedState.FREE_FALL,
    SimplifiedState.IMPACT,
    SimplifiedState.SHAKE,
    SimplifiedState.MOVING,
]

class SquealingActivity(BaseService):
    """Service that manages the squealing activity state
    
    When active, this service:
    1. Plays a bunch of squealing / "where are we" noises / voice lines
    2. On detecting being picked up, stops the activity.
    """
    
    def __init__(self, service_manager):
        super().__init__(service_manager)
        self._is_active = False
        self._tts_task = None
        # TODO: get from config.
        self._ENABLE_LED_EFFECTS = False
        self._LED_BRIGHTNESS = 0.6
        # NOTE: Lower stability is more expressive. ElevenLabs default is likely 0.75.
        # We set it lower for more "panicked" speech.
        # IMPORTANT: This value MUST be reflected in `scripts/precache_tts.py`
        # for these phrases to be properly cached.
        self._TTS_STABILITY = 0.5
        self._tts_delay_min_sec = 0.3
        self._tts_delay_max_sec = 1.5
        self._pickup_speech_delay_sec = 1
        self._squeal_actions = [
            {"type": "sound", "value": "OUCH1"},
            {"type": "speak", "value": "Oh NOOO!! We've CRASHED!"},
            {"type": "speak", "value": "Waaah!!!"},
            {"type": "speak", "value": "Where ARE we??!"},
            {"type": "speak", "value": "Is THIS Earth??"},
            {"type": "speak", "value": "WHAT'S GOING ON?!"},
            {"type": "speak", "value": "I'm scared!!"},
            {"type": "sound", "value": "OUCH2"},
            {"type": "speak", "value": "Did we MAKE it?!"},
            {"type": "speak", "value": "Wow that was such a long journey!!"},
            {"type": "speak", "value": "I'm SO tired!!"},
            {"type": "speak", "value": "OH NO!! The transmitter's broken!!"},
            {"type": "speak", "value": "I want GRANDMA!!!"}
        ]
        self._squeal_action_index = random.randint(0, len(self._squeal_actions) - 1)
        
    async def _squeal_loop(self):
        """The main loop for the squealing activity."""
        while self._is_active:
            try:
                # Get the next action in order
                action = self._squeal_actions[self._squeal_action_index]
                self._squeal_action_index = (self._squeal_action_index + 1) % len(self._squeal_actions)

                action_finished_event = asyncio.Event()
                if action["type"] == "speak":
                    await self.publish({
                        "type": "speak_audio",
                        "text": action["value"],
                        "on_finish_event": action_finished_event,
                        "stability": self._TTS_STABILITY
                    })
                elif action["type"] == "sound":
                    await self.publish({
                        "type": "play_sound",
                        "effect_name": action["value"],
                        "on_finish_event": action_finished_event
                    })
                
                await action_finished_event.wait()
                
                # Wait for a random delay with a red LED effect
                if self._is_active:
                    if self._ENABLE_LED_EFFECTS:
                        await self.publish({
                            "type": "start_led_effect",
                            "data": {
                                "effect_name": "ROTATING_COLOR",
                                "color": "red",
                                "speed": 0.01, # Faster rotation for "panic"
                                "brightness": self._LED_BRIGHTNESS
                            }
                        })

                    # Pause between actions
                    delay = random.uniform(self._tts_delay_min_sec, self._tts_delay_max_sec)
                    self.logger.debug(f"Waiting for {delay:.2f} seconds.")
                    await asyncio.sleep(delay)

                    # Restore the calming green breathing effect if we are still active
                    if self._is_active and self._ENABLE_LED_EFFECTS:
                        await self.publish({
                            "type": "start_led_effect",
                            "data": {
                                "effect_name": "GREEN_BREATHING",
                                "speed": 0.03,
                                "brightness": self._LED_BRIGHTNESS
                            }
                        })
            except asyncio.CancelledError:
                self.logger.info("Squeal loop cancelled.")
                break
            except Exception as e:
                self.logger.error(f"Error in squeal loop: {e}")
                break
        
    async def start(self):
        """Start the squealing activity"""
        await super().start()
        self._is_active = True
        self._squeal_action_index = random.randint(0, len(self._squeal_actions) - 1)
        
        # Start the TTS squealing loop
        self._tts_task = asyncio.create_task(self._squeal_loop())
        
        # Stop any previous LED effect
        await self.publish({
            "type": "stop_led_effect"
        })
        
        # Start the LED effect
        await self.publish({
            "type": "start_led_effect",
            "data": {
                "effect_name": "GREEN_BREATHING",
                "speed": 0.03,  # Slow, gentle rotation
                "brightness": self._LED_BRIGHTNESS 
            }
        })
        
        self.logger.info("squealing activity started")
        
    async def stop(self):
        """Stop the squealing activity"""
        self.logger.info("We're in the stop() method on squealing activity")
        if self._is_active:
            self._is_active = False
            
        if self._tts_task:
            self._tts_task.cancel()
            self._tts_task = None
            
        # Stop the LED effect without waiting to prevent deadlocks.
        # This is a 'fire-and-forget' task.
        asyncio.create_task(self.publish({
            "type": "stop_led_effect"
        }))

        self.logger.info("Calling super().stop() on squealing activity")
        await super().stop()
        self.logger.info("squealing activity stopped")
        
    async def handle_event(self, event: Dict[str, Any]):
        """Handle events from other services"""
        event_type = event.get("type")
        
        if self._is_active:
            if event_type == "sensor_data" and event.get("sensor") == "accelerometer":
                # Extract data from accelerometer event
                data = event.get("data", {})
                current_state_name = data.get("current_state", SimplifiedState.UNKNOWN.name)
                self.logger.debug(f"Current state: {current_state_name}")
                # energy = data.get("energy", 0.0) # Get energy level (0-1)
                current_state_name = data.get("current_state", SimplifiedState.UNKNOWN.name)
                
                # Convert state name back to enum member
                try:
                    current_state_enum = SimplifiedState[current_state_name]
                except KeyError:
                    self.logger.warning(f"Received unknown state name: {current_state_name}")
                    current_state_enum = SimplifiedState.UNKNOWN
                    return
                
                if current_state_enum in moving_states:
                    self._is_active = False
                    
                    # Stop the TTS loop
                    if self._tts_task:
                        self._tts_task.cancel()
                        self._tts_task = None

                    # Play pickup sound effect
                    await self.publish({
                        "type": "play_sound",
                        "effect_name": "WEE3"
                    })

                    # Change LED to rainbow
                    await self.publish({
                        "type": "start_led_effect",
                        "data": {
                            "effect_name": "RAINBOW",
                            "brightness": self._LED_BRIGHTNESS
                        }
                    })

                    # Wait a second
                    await asyncio.sleep(self._pickup_speech_delay_sec)

                    # Start twinkling effect for speech
                    await self.publish({
                        "type": "start_led_effect",
                        "data": {
                            "effect_name": "TWINKLING",
                            "speed": 0.1,
                            "brightness": self._LED_BRIGHTNESS
                        }
                    })

                    # Create an event to wait for TTS completion
                    tts_finished_event = asyncio.Event()
                    
                    await self.publish({
                        "type": "speak_audio",
                        "text": "Ooh! Oooh! Who's that? ... Are you a human? ... Oh yaay! We're gonna be okay! ... Oof, I'm sooo so tired now, maybe we should have a little nap now that we're safe.",
                        "on_finish_event": tts_finished_event,
                        "stability": self._TTS_STABILITY
                    })
                    
                    # Wait for the TTS to finish before ending the activity
                    self.logger.info("Waiting for TTS to complete...")
                    await tts_finished_event.wait()
                    self.logger.info("TTS completed.")

                    # Add a final sequence of yawns and snores
                    await asyncio.sleep(1)

                    # Change to green breathing for yawn
                    await self.publish({
                        "type": "start_led_effect",
                        "data": {
                            "effect_name": "GREEN_BREATHING",
                            "speed": 0.03, # Default calm speed
                            "brightness": self._LED_BRIGHTNESS
                        }
                    })

                    yawn_finished_event = asyncio.Event()
                    await self.publish({
                        "type": "play_sound",
                        "effect_name": "YAWN2",
                        "on_finish_event": yawn_finished_event
                    })
                    await yawn_finished_event.wait()
                    
                    snore_finished_event = asyncio.Event()
                    await self.publish({
                        "type": "play_sound",
                        "effect_name": "SNORE",
                        "on_finish_event": snore_finished_event
                    })
                    await snore_finished_event.wait()

                    await self.publish({
                        "type": "squealing_ended"
                    })
                    self.logger.info("Squealing ended!")

                    
                


    