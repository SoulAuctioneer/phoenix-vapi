import asyncio
import os
import sys
from pathlib import Path
import logging
import hashlib
from typing import Optional
import aiofiles

# Add src directory to the Python path to mimic the application's runtime environment
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
src_path = os.path.join(project_root, 'src')
sys.path.insert(0, src_path)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# This is slow, but necessary.
from managers.voice_manager import VoiceManager
from config import ElevenLabsConfig, ScavengerHuntConfig

# The default pitch used when an event doesn't specify one.
# This must match VoiceService.DEFAULT_PITCH to ensure cache hits.
DEFAULT_PITCH = 4.0

# --- List of texts to pre-cache ---
# You can add any text here to pre-cache it.
TEXTS_TO_CACHE = [
    # from SquealingActivity
    "Where ARE we??!",
    "WHAT'S GOING ON?!",
    "Is THIS Earth??",
    "Waaah!!!",
    "Are we THERE yet?!",
    "I'm scared!!",
    "Did we MAKE it?!",
    "I'm SO tired!!",
    "Wow that was such a long journey!!",
    "Oh NOOO!! We've CRASHED!",
    "The transmitter's broken!",
    "I want GRANDMA!!!",
    "Ooh! Oooh! Who's that? ... Are you a human? ... Oh yaay! We're gonna be okay! ... Oof, I'm sooo so tired now, maybe we should have a little nap now that we're safe.",

    # from ActivityService
    "OK, shutting down.",

    # from ScavengerHuntConfig
    "We did it! We found all the pieces! Hooray!! Now we can fix the transmitter and call Grandmother Pea on the Mothership! You're the best! ... Now I can have a nice, relaxing nap!",
    "First, the Junction Box is where all the giggly wires meet up to tell secrets!",
    "Yay! We found the Junction Box! All the wires are wiggling with happiness. Great job!",
    "Next, the Transmitter Valve helps us to send messages to the stars!",
    "Yay! We found it! The Transmitter Valve is open and ready to whoosh our messages out!",
    "Last one! The Signal Processor unscrambles all the funny space noises!",
    "Yes! The Signal Processor! Now the alien chatter sounds like songs instead of gobbledegook.",
    "Ooh, I've started sensing something, but it's really, really far away!",
    "Okay! I can feel it now, but it's still pretty far.",
    "Yes, that's it! We're getting closer! The wiggles are getting stronger!",
    "Oh no, the feeling is getting weaker. I think we're going the wrong way.",
    "Oh dear, I've lost the signal completely. Where did it go?",

    # From GrandmaPeaActivity
    "Yaay it's grandma pea! Weee!! We love you grandma!",
    "Yippee!! It's Grandma Pea! We missed you SO much!!",
    "Grandma!! It's really you! We're over the moon, but here on earth!!",
    "Grandma Pea! Grandma Pea! You're our favorite in the whole galaxy!!",

    # from ScavengerHuntConfig (static)
    ScavengerHuntConfig.VICTORY_TEXT,
]

# Add dynamically generated intro texts from ScavengerHuntConfig
def _generate_intro_text(hunt_locations):
    """Generates the intro text for a given list of hunt locations."""
    objectives = [loc.objective_name for loc in hunt_locations]
    if len(objectives) > 2:
        objectives_list_str = ", the ".join(objectives[:-1])
        objectives_list_str = f"the {objectives_list_str}, and the {objectives[-1]}"
    elif len(objectives) == 2:
        objectives_list_str = f"the {objectives[0]} and the {objectives[1]}"
    elif len(objectives) == 1:
        objectives_list_str = f"the {objectives[0]}"
    else:
        objectives_list_str = ScavengerHuntConfig.INTRO_FALLBACK_OBJECTIVES
    
    return ScavengerHuntConfig.INTRO_TEXT_TEMPLATE.format(objectives_list_str=objectives_list_str)

TEXTS_TO_CACHE.append(_generate_intro_text(ScavengerHuntConfig.HUNT_ALPHA))
TEXTS_TO_CACHE.append(_generate_intro_text(ScavengerHuntConfig.HUNT_BETA))

# Remove potential duplicates
TEXTS_TO_CACHE = list(set(TEXTS_TO_CACHE))

# This logic is duplicated from VoiceService to avoid complex dependencies.
def generate_cache_key(text: str, voice_id: Optional[str] = None, model_id: Optional[str] = None, stability: Optional[float] = None, style: Optional[float] = None, use_speaker_boost: Optional[bool] = None, pitch: Optional[float] = None) -> str:
    """Generate a unique cache key based on text and TTS parameters."""
    voice_id = voice_id or ElevenLabsConfig.DEFAULT_VOICE_ID
    model_id = model_id or ElevenLabsConfig.DEFAULT_MODEL_ID
    
    cache_string = f"{text}|{voice_id}|{model_id}|{stability}|{style}|{use_speaker_boost}|{pitch}"
    
    hash_object = hashlib.sha256(cache_string.encode('utf-8'))
    return hash_object.hexdigest()

async def precache_tts_audio():
    """
    Generates and caches TTS audio files for a predefined list of texts across all available voices.
    This script helps to reduce runtime latency by pre-generating audio files.
    """
    try:
        voice_manager = VoiceManager()
    except ValueError as e:
        logger.error(f"Failed to initialize VoiceManager: {e}")
        logger.error("Please ensure your ELEVENLABS_API_KEY is set in your .env file.")
        return

    # NOTE: This path should match PRE_CACHE_DIR in VoiceService
    pre_cache_dir = Path("assets/tts_cache")
    pre_cache_dir.mkdir(parents=True, exist_ok=True)

    voices_to_cache = ElevenLabsConfig.VOICE_IDS
    total_phrases = len(TEXTS_TO_CACHE) * len(voices_to_cache)

    logger.info(f"Starting TTS pre-caching for {len(TEXTS_TO_CACHE)} phrases across {len(voices_to_cache)} voices...")
    logger.info(f"Total audio files to check/generate: {total_phrases}")
    logger.info(f"Cache directory: {pre_cache_dir.absolute()}")

    cached_count = 0
    generated_count = 0
    failed_count = 0

    for voice_name, voice_id in voices_to_cache.items():
        logger.info(f"--- Processing voice: {voice_name.upper()} (ID: {voice_id}) ---")
        for text in TEXTS_TO_CACHE:
            # Using default TTS parameters for now.
            # If you use custom parameters (voice, pitch, etc.) in your app,
            # you'll need to replicate them here for the cache to match.
            cache_key = generate_cache_key(text, voice_id=voice_id, pitch=DEFAULT_PITCH)
            cache_path = pre_cache_dir / f"{cache_key}.pcm"

            if cache_path.exists():
                logger.info(f"Skipping '{text[:40]}...': already cached for voice {voice_name}.")
                cached_count += 1
                continue

            logger.info(f"Caching '{text[:40]}...' for voice {voice_name}")
            
            try:
                audio_stream = await voice_manager.generate_audio_stream(text, voice_id=voice_id, pitch=DEFAULT_PITCH)
                if audio_stream:
                    audio_bytes = b"".join([chunk async for chunk in audio_stream])
                    if audio_bytes:
                        async with aiofiles.open(cache_path, 'wb') as f:
                            await f.write(audio_bytes)
                        logger.info(f"-> Successfully cached '{text[:40]}...'.")
                        generated_count += 1
                    else:
                        logger.warning(f"-> Failed to cache '{text[:40]}...': Received empty audio stream.")
                        failed_count += 1
                else:
                    logger.error(f"-> Failed to generate audio for '{text[:40]}...'.")
                    failed_count += 1
            except Exception as e:
                logger.error(f"-> Error caching '{text[:40]}...': {e}", exc_info=False)
                failed_count += 1
            
            # Small delay to avoid hitting API rate limits
            await asyncio.sleep(1.5) # Increased delay slightly

    logger.info("\n--- Pre-caching summary ---")
    logger.info(f"Total combinations checked: {total_phrases}")
    logger.info(f"Already cached: {cached_count}")
    logger.info(f"Newly generated: {generated_count}")
    logger.info(f"Failed: {failed_count}")
    logger.info("---------------------------\n")


if __name__ == "__main__":
    # Ensure .env variables are loaded
    from dotenv import load_dotenv
    # Assuming the script is run from the root of the project,
    # otherwise, adjust the path to .env file.
    dotenv_path = Path(__file__).resolve().parent.parent / '.env'
    if dotenv_path.exists():
        load_dotenv(dotenv_path=dotenv_path)
        logger.info(f"Loaded .env file from: {dotenv_path}")
    else:
        logger.warning(f".env file not found at {dotenv_path}. Environment variables should be set manually.")

    # Move this import down here to ensure the path is set up first
    from dotenv import load_dotenv

    # Check for API key before starting
    if not os.getenv("ELEVENLABS_API_KEY"):
        logger.error("ELEVENLABS_API_KEY environment variable not set.")
        logger.error("Please create a .env file in the project root and add your key.")
    else:
        try:
            asyncio.run(precache_tts_audio())
        except KeyboardInterrupt:
            logger.info("Pre-caching interrupted by user.") 