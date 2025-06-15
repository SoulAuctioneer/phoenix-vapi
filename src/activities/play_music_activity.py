import asyncio
from typing import Dict, Any, Optional

from services.service import BaseService
from config import SoundEffect, get_filter_logger


class PlayMusicActivity(BaseService):
    """
    An activity that plays a music track once, waits for a short period, and then ends.
    """
    def __init__(self, service_manager):
        super().__init__(service_manager)
        self.logger = get_filter_logger(self.__class__.__name__)
        self._finish_task: Optional[asyncio.Task] = None
        # The name of the sound effect to play
        self._sound_name = SoundEffect.TUNE_PLANTASIA.name

    async def start(self):
        """
        Starts the activity by publishing a request to play the sound.
        """
        await super().start()
        self.logger.info(f"Starting PlayMusicActivity, playing sound: {self._sound_name}")
        await self.publish({
            "type": "play_sound",
            "effect_name": self._sound_name,
            #"volume": 0.7
        })

    async def stop(self):
        """
        Stops the activity, cancelling any pending finish task.
        """
        if self._finish_task and not self._finish_task.done():
            self._finish_task.cancel()
        await super().stop()
        self.logger.info("PlayMusicActivity stopped.")

    async def _wait_and_finish(self):
        """
        Waits for 10 seconds then publishes the activity_ended event.
        """
        try:
            await asyncio.sleep(10)
            self.logger.info("10 seconds elapsed, publishing activity_ended for play_music.")
            await self.publish({
                "type": "activity_ended",
                "activity": "play_music"
            })
        except asyncio.CancelledError:
            self.logger.info("Wait and finish task was cancelled.")

    async def handle_event(self, event: Dict[str, Any]):
        """
        Handles events, looking for the sound_effect_finished event to trigger the end timer.
        """
        event_type = event.get("type")
        if event_type == "sound_effect_finished":
            effect_name = event.get("data", {}).get("effect_name")
            if effect_name == self._sound_name:
                self.logger.info(f"Sound '{self._sound_name}' finished playing. Waiting 10 seconds to end activity.")
                self._finish_task = asyncio.create_task(self._wait_and_finish()) 