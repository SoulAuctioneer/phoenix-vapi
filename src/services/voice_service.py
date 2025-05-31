import logging
import asyncio
from typing import Dict, Any

from services.service import BaseService
from managers.voice_manager import VoiceManager
from managers.audio_manager import AudioManager, AudioConfig
from config import AudioBaseConfig

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

class VoiceService(BaseService):
    """Service to manage Text-to-Speech using VoiceManager and AudioManager."""
    TTS_PRODUCER_NAME = "elevenlabs_tts_output"

    def __init__(self, service_manager):
        super().__init__(service_manager)
        self.voice_manager = None
        self.audio_manager = None
        self._tts_producer = None

    async def start(self):
        """Start the voice service."""
        await super().start()
        try:
            self.voice_manager = VoiceManager()
            # Get an instance of AudioManager
            # Ensure AudioConfig is initialized if AudioManager hasn't been started elsewhere first
            # Typically AudioService starts AudioManager, so it should be available.
            self.audio_manager = AudioManager.get_instance()
            if not self.audio_manager.is_running:
                logger.warning("AudioManager is not running. VoiceService might not play audio correctly.")
            
            # Pre-create the audio producer for TTS output
            self._tts_producer = self.audio_manager.add_producer(
                name=self.TTS_PRODUCER_NAME,
                chunk_size=AudioBaseConfig.CHUNK_SIZE,
                buffer_size=AudioBaseConfig.BUFFER_SIZE * 10 # Increased buffer size from 2x to 10x
            )
            self.audio_manager.set_producer_volume(self.TTS_PRODUCER_NAME, AudioBaseConfig.DEFAULT_VOLUME)

            logger.info("VoiceService started successfully.")
        except Exception as e:
            logger.error(f"Failed to start VoiceService: {e}", exc_info=True)
            # Propagate the error to ensure the application knows something went wrong.
            raise

    async def stop(self):
        """Stop the voice service."""
        logger.info("Stopping VoiceService...")
        if self.audio_manager and self._tts_producer:
            try:
                self.audio_manager.remove_producer(self.TTS_PRODUCER_NAME)
                logger.info(f"Removed audio producer: {self.TTS_PRODUCER_NAME}")
            except Exception as e:
                logger.error(f"Error removing TTS audio producer: {e}")
        self._tts_producer = None
        self.voice_manager = None # Release VoiceManager instance
        await super().stop()
        logger.info("VoiceService stopped.")

    async def handle_event(self, event: Dict[str, Any]):
        """Handle events, specifically 'speak_audio' for TTS."""
        event_type = event.get("type")

        if event_type == "speak_audio":
            text_to_speak = event.get("text")
            voice_id = event.get("voice_id") # Optional: allow overriding default voice
            model_id = event.get("model_id") # Optional: allow overriding default model

            if not text_to_speak:
                logger.warning("'speak_audio' event received without 'text'.")
                return

            if not self.voice_manager:
                logger.error("VoiceManager not initialized. Cannot speak audio.")
                return
            
            if not self._tts_producer or not self._tts_producer.active:
                logger.error(f"TTS audio producer '{self.TTS_PRODUCER_NAME}' is not active. Recreating.")
                # Attempt to recreate the producer if it's gone missing or inactive
                try:
                    self._tts_producer = self.audio_manager.add_producer(
                        name=self.TTS_PRODUCER_NAME,
                        chunk_size=AudioBaseConfig.CHUNK_SIZE,
                        buffer_size=AudioBaseConfig.BUFFER_SIZE * 10 # Increased buffer size here too
                    )
                    self.audio_manager.set_producer_volume(self.TTS_PRODUCER_NAME, AudioBaseConfig.DEFAULT_VOLUME)
                except Exception as e:
                    logger.error(f"Failed to recreate TTS audio producer: {e}")
                    return

            logger.info(f"Received speak_audio event for text: '{text_to_speak[:30]}'")
            # Run the streaming and playback in a new task to avoid blocking event handling
            asyncio.create_task(self._stream_and_play_tts(text_to_speak, voice_id, model_id))

    async def _stream_and_play_tts(self, text: str, voice_id: str = None, model_id: str = None):
        """Generates audio stream using VoiceManager and plays it via AudioManager."""
        try:
            audio_stream_iterator = await self.voice_manager.generate_audio_stream(
                text,
                voice_id=voice_id,
                model_id=model_id
            )

            if not audio_stream_iterator:
                logger.error("Failed to get audio stream from VoiceManager.")
                return

            logger.info("Playing TTS audio stream...")
            async for audio_chunk_bytes in audio_stream_iterator:
                if audio_chunk_bytes:
                    # Convert PCM bytes to numpy array
                    audio_np_array = self.voice_manager.pcm_bytes_to_numpy(audio_chunk_bytes)
                    
                    if audio_np_array.size > 0:
                        # Resize the chunk using the producer's own resizer method
                        # This will handle remainders and ensure chunks are of the correct size
                        # for the AudioManager's output loop.
                        resized_chunks = self._tts_producer.resize_chunk(audio_np_array)
                        for chunk_to_put in resized_chunks:
                            success = self._tts_producer.buffer.put(chunk_to_put)
                            if not success:
                                logger.warning(f"TTS audio producer buffer full for '{self.TTS_PRODUCER_NAME}'. Audio chunk dropped.")
                    else:
                        logger.warning("Received empty audio array after conversion.")
            logger.info("Finished playing TTS audio stream.")

        except Exception as e:
            logger.error(f"Error during TTS streaming and playback: {e}", exc_info=True) 