import logging
import asyncio
import os
import hashlib
import aiofiles
from pathlib import Path
from typing import Dict, Any, Optional

from services.service import BaseService
from managers.voice_manager import VoiceManager
from managers.audio_manager import AudioManager, AudioConfig
from config import AudioBaseConfig

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

class VoiceService(BaseService):
    """Service to manage Text-to-Speech using VoiceManager and AudioManager."""
    TTS_PRODUCER_NAME = "elevenlabs_tts_output"
    TTS_CACHE_DIR = "data/tts_cache"  # Directory to store cached TTS audio files

    def __init__(self, service_manager):
        super().__init__(service_manager)
        self.voice_manager = None
        self.audio_manager = None
        self._tts_producer = None
        self._cache_dir = None

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

            # Initialize cache directory
            self._cache_dir = Path(self.TTS_CACHE_DIR)
            self._cache_dir.mkdir(exist_ok=True)
            logger.info(f"TTS cache directory: {self._cache_dir.absolute()}")

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

    def _generate_cache_key(self, text: str, voice_id: Optional[str] = None, model_id: Optional[str] = None) -> str:
        """Generate a unique cache key based on text and TTS parameters."""
        # Use default values if not provided
        from config import ElevenLabsConfig
        voice_id = voice_id or ElevenLabsConfig.DEFAULT_VOICE_ID
        model_id = model_id or ElevenLabsConfig.DEFAULT_MODEL_ID
        
        # Create a unique string combining all parameters
        cache_string = f"{text}|{voice_id}|{model_id}"
        
        # Generate SHA256 hash for filename
        hash_object = hashlib.sha256(cache_string.encode('utf-8'))
        return hash_object.hexdigest()

    def _get_cache_path(self, cache_key: str) -> Path:
        """Get the full path for a cached audio file."""
        return self._cache_dir / f"{cache_key}.pcm"

    async def _check_cache(self, text: str, voice_id: Optional[str] = None, model_id: Optional[str] = None) -> Optional[bytes]:
        """Check if audio is cached and return it if available."""
        cache_key = self._generate_cache_key(text, voice_id, model_id)
        cache_path = self._get_cache_path(cache_key)
        
        if cache_path.exists():
            try:
                async with aiofiles.open(cache_path, 'rb') as f:
                    audio_data = await f.read()
                logger.info(f"Cache hit for text: '{text[:30]}...' (key: {cache_key[:8]}...)")
                return audio_data
            except Exception as e:
                logger.error(f"Error reading cached audio file {cache_path}: {e}")
                return None
        
        return None

    async def _save_to_cache(self, audio_data: bytes, text: str, voice_id: Optional[str] = None, model_id: Optional[str] = None):
        """Save audio data to cache."""
        cache_key = self._generate_cache_key(text, voice_id, model_id)
        cache_path = self._get_cache_path(cache_key)
        
        try:
            async with aiofiles.open(cache_path, 'wb') as f:
                await f.write(audio_data)
            logger.info(f"Cached audio for text: '{text[:30]}...' (key: {cache_key[:8]}...)")
        except Exception as e:
            logger.error(f"Error saving audio to cache {cache_path}: {e}")

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

            logger.info(f"Received speak_audio event for text: '{text_to_speak[:30]}...'")
            
            # Check cache first
            cached_audio = await self._check_cache(text_to_speak, voice_id, model_id)
            
            if cached_audio:
                # Play from cache
                asyncio.create_task(self._play_cached_audio(cached_audio))
            else:
                # Generate new audio and cache it
                asyncio.create_task(self._stream_and_play_tts(text_to_speak, voice_id, model_id))

    async def _play_cached_audio(self, audio_data: bytes):
        """Play cached audio data."""
        try:
            logger.info("Playing cached TTS audio...")
            
            # Convert PCM bytes to numpy array
            audio_np_array = self.voice_manager.pcm_bytes_to_numpy(audio_data)
            
            if audio_np_array.size > 0:
                # Resize the chunk using the producer's own resizer method
                resized_chunks = self._tts_producer.resize_chunk(audio_np_array)
                for chunk_to_put in resized_chunks:
                    success = self._tts_producer.buffer.put(chunk_to_put)
                    if not success:
                        logger.warning(f"TTS audio producer buffer full for '{self.TTS_PRODUCER_NAME}'. Audio chunk dropped.")
            else:
                logger.warning("Cached audio data is empty.")
                
            logger.info("Finished playing cached TTS audio.")
            
        except Exception as e:
            logger.error(f"Error playing cached audio: {e}", exc_info=True)

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

            logger.info("Streaming TTS audio from ElevenLabs...")
            
            # Collect all audio chunks for caching
            all_audio_chunks = []
            
            async for audio_chunk_bytes in audio_stream_iterator:
                if audio_chunk_bytes:
                    # Store chunk for caching
                    all_audio_chunks.append(audio_chunk_bytes)
                    
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
                        
            logger.info("Finished streaming TTS audio.")
            
            # Save to cache if we have audio data
            if all_audio_chunks:
                combined_audio = b''.join(all_audio_chunks)
                await self._save_to_cache(combined_audio, text, voice_id, model_id)

        except Exception as e:
            logger.error(f"Error during TTS streaming and playback: {e}", exc_info=True) 