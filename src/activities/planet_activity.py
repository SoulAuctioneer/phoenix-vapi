import asyncio
from typing import Dict, Any
from services.service import BaseService
from config import get_filter_logger

# The script for our planet tour.
# Each entry is a tuple: (narration_text, led_effect_name, duration_seconds)
# Duration is how long to show the effect *after* the narration finishes.
PLANET_TOUR_SCRIPT = [
    # Introduction
    (
        "Welcome aboard the Magic Pea starship! Let's go on an amazing tour of our solar system. First, let's fire up the engines! Engaging warp drive!",
        "WARP_DRIVE",
        5,
    ),
    # Mercury
    (
        "Our first stop is Mercury! It's the closest planet to the Sun. It's a small, rocky world covered in craters, kind of like our moon.",
        "MERCURY",
        8,
    ),
    (
        "Time to fly to the next planet! Warp speed!",
        "WARP_DRIVE",
        5,
    ),
    # Venus
    (
        "This is Venus! It's the hottest planet, with thick, yellow clouds that trap the Sun's heat. It's a very stormy place!",
        "VENUS",
        8,
    ),
    (
        "Here we go again! To the next world!",
        "WARP_DRIVE",
        5,
    ),
    # Earth
    (
        "Look, it's our home, Planet Earth! You can see the big blue oceans and the green and brown land. It's the only planet we know with life!",
        "EARTH",
        8,
    ),
    (
        "Let's continue our journey outward!",
        "WARP_DRIVE",
        5,
    ),
    # Mars
    (
        "We've arrived at Mars, the Red Planet! It's red because of rusty iron in the ground. Scientists are very curious about Mars and have sent robots to explore it.",
        "MARS",
        8,
    ),
    (
        "On to the giant planets!",
        "WARP_DRIVE",
        5,
    ),
    # Jupiter
    (
        "Wow, this is Jupiter! It's the biggest planet in our solar system. See those stripes? They are giant storms, and see that big red spot? That's a storm bigger than our whole Earth!",
        "JUPITER",
        10,
    ),
    (
        "Next stop, the planet with the beautiful rings!",
        "WARP_DRIVE",
        5,
    ),
    # Saturn
    (
        "Here is Saturn! It's famous for its amazing rings, which are made of ice, dust, and rock. Isn't it beautiful?",
        "SATURN",
        10,
    ),
    (
        "We're getting far from the sun now!",
        "WARP_DRIVE",
        5,
    ),
    # Uranus
    (
        "This is Uranus. It's a very cold, icy planet that is tilted on its side. It's a beautiful light blue color.",
        "URANUS",
        8,
    ),
    (
        "To the last planet on our tour!",
        "WARP_DRIVE",
        5,
    ),
    # Neptune
    (
        "Our final stop is Neptune! It's a dark, cold, and very windy world. It's the farthest planet from the Sun.",
        "NEPTUNE",
        8,
    ),
    # Conclusion
    (
        "What an incredible journey! We've visited all the planets. Time to head back home. Engaging warp drive for the last time!",
        "WARP_DRIVE",
        5,
    ),
]


class PlanetActivity(BaseService):
    """
    An activity that takes the user on a narrated tour of the solar system,
    with custom LED effects for each planet.
    """

    def __init__(self, service_manager):
        super().__init__(service_manager)
        self.logger = get_filter_logger(self.__class__.__name__)
        self._tour_task: asyncio.Task = None

    async def start(self):
        """Starts the PlanetActivity."""
        await super().start()
        self.logger.info("Planet Activity service started.")

    async def stop(self):
        """Stops the PlanetActivity."""
        if self._tour_task and not self._tour_task.done():
            self._tour_task.cancel()
            await self.publish({"type": "stop_led_effect"})
            self.logger.info("Planet tour cancelled.")
        await super().stop()
        self.logger.info("Planet Activity service stopped.")

    async def start_tour(self):
        """Begins the planet tour."""
        if self._tour_task and not self._tour_task.done():
            self.logger.warning("Tour is already running, cannot start a new one.")
            return
        
        self.logger.info("Starting the planet tour!")
        self._tour_task = asyncio.create_task(self._run_tour())

    async def _run_tour(self):
        """The main coroutine that runs the tour sequence."""
        try:
            for i, (text, effect, duration) in enumerate(PLANET_TOUR_SCRIPT):
                self.logger.info(f"Tour step {i+1}: Planet/scene is {effect}")

                # Announce the current part of the tour
                await self.publish({
                    "type": "speak_audio",
                    "text": text,
                })
                
                # Start the LED effect for this part of the tour
                await self.publish({
                    "type": "start_led_effect",
                    "data": {"effect_name": effect}
                })

                # Wait for an estimated time for speech to finish.
                # A more robust solution might listen for a 'speech_ended' event.
                # For now, we estimate 200 words per minute.
                estimated_speech_time = len(text.split()) / (200 / 60)
                await asyncio.sleep(estimated_speech_time)

                # Wait for the specified duration to enjoy the view
                await asyncio.sleep(duration)
                
            self.logger.info("Planet tour finished!")

        except asyncio.CancelledError:
            self.logger.info("Planet tour task was cancelled.")
        except Exception as e:
            self.logger.error(f"An error occurred during the planet tour: {e}", exc_info=True)
        finally:
            # When the tour is over, signal to the ActivityService to stop.
            await self.publish({
                "type": "activity_ended",
                "activity": "planet_tour" 
            })

    async def handle_event(self, event: Dict[str, Any]):
        """Handles events for PlanetActivity."""
        pass # This activity is self-contained and doesn't need to react to external events. 