from enum import Enum
from typing import Union
from services.service import BaseService
import logging

class SpecialEffect(str, Enum):
    """Available special effects combining both sound and LED effects"""
    # Combined effects (effects that have both sound and light)
    MAGICAL_SPELL = "MAGICAL_SPELL"
    LIGHTNING = "LIGHTNING"
    RAIN = "RAIN"
    RAINBOW = "RAINBOW"

    # Sound-only effects
    YAWN = "YAWN"
    WHOOSH = "WHOOSH"
    MYSTERY = "MYSTERY"

    # LED-only effects
    BLUE_BREATHING = "BLUE_BREATHING"
    GREEN_BREATHING = "GREEN_BREATHING"
    ROTATING_PINK_BLUE = "ROTATING_PINK_BLUE"
    ROTATING_GREEN_YELLOW = "ROTATING_GREEN_YELLOW"
    TWINKLING = "TWINKLING"
    
    @classmethod
    def get_sound_effect(cls, effect: str) -> Union[str, None]:
        """Get the corresponding sound effect name for a special effect"""
        sound_effect_map = {
            cls.MAGICAL_SPELL: "magical_spell",
            cls.LIGHTNING: "lightning",
            cls.RAIN: "rain",
            cls.RAINBOW: "mystery",
            # Below sounds don't have corresponding LED effects
            cls.YAWN: "yawn",
            cls.WHOOSH: "whoosh",
            cls.MYSTERY: "mystery",
        }
        return sound_effect_map.get(cls(effect))
    
    @classmethod
    def get_led_effect(cls, effect: str) -> Union[str, None]:
        """Get the corresponding LED effect name for a special effect"""
        led_effect_map = {
            cls.MAGICAL_SPELL: "MAGICAL_SPELL",
            cls.LIGHTNING: "LIGHTNING",
            cls.RAIN: "RAIN",
            cls.RAINBOW: "RAINBOW",
            # Below effects don't have corresponding sound effects
            cls.BLUE_BREATHING: "BLUE_BREATHING",
            cls.GREEN_BREATHING: "GREEN_BREATHING",
            cls.ROTATING_PINK_BLUE: "ROTATING_PINK_BLUE",
            cls.ROTATING_GREEN_YELLOW: "ROTATING_GREEN_YELLOW",
            cls.TWINKLING: "TWINKLING",
        }
        return led_effect_map.get(cls(effect))


class SpecialEffectService(BaseService):
    """Service for playing combined special effects (sound and/or LED)"""
    
    def __init__(self, service_manager):
        super().__init__(service_manager)
    
    async def start(self):
        """Initialize the special effect service"""
        logging.info("Special effect service started")
    
    async def stop(self):
        """Stop the special effect service"""
        logging.info("Special effect service stopped")
    
    async def play_effect(self, effect_name: str):
        """Play a special effect by name"""
        try:
            # Force uppercase for effect name
            effect_name = effect_name.upper()

            # Validate the effect name
            effect = SpecialEffect(effect_name)
            
            # Get corresponding sound and LED effects
            sound_effect = SpecialEffect.get_sound_effect(effect_name)
            led_effect = SpecialEffect.get_led_effect(effect_name)
            
            # Publish sound effect event if applicable
            if sound_effect:
                await self.publish({
                    "type": "play_sound",
                    "effect_name": sound_effect
                })
                logging.info(f"Published sound effect: {sound_effect}")
            
            # Publish LED effect event if applicable
            if led_effect:
                await self.publish({
                    "type": "start_led_effect",
                    "data": {
                        "effectName": led_effect
                    }
                })
                logging.info(f"Published LED effect: {led_effect}")
                
        except ValueError:
            logging.error(f"Invalid effect name: {effect_name}")
            raise
        except Exception as e:
            logging.error(f"Error playing special effect: {e}")
            raise
    
    async def handle_event(self, event):
        """Handle special effect events"""
        if event.get("type") == "play_special_effect":
            effect_name = event.get("effect_name")
            if effect_name:
                await self.play_effect(effect_name) 