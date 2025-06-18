import logging
import asyncio
import os
import hashlib
import aiofiles
from pathlib import Path
from typing import Dict, Any, Optional

from services.service import BaseService
from managers.audio_manager import AudioManager, AudioConfig
from config import AudioBaseConfig, get_filter_logger

logger = get_filter_logger(__name__)
logger.setLevel(logging.DEBUG)

logger.info("Importing VoiceManager...")
from managers.voice_manager import VoiceManager
logger.info("Imported VoiceManager.")

class VoiceService(BaseService):
    """Service to manage Text-to-Speech using VoiceManager and AudioManager."""
    TTS_CACHE_DIR = "data/tts_cache"  # Directory to store cached TTS audio files

    def __init__(self, service_manager):
        super().__init__(service_manager)
        self.voice_manager = None
        self.audio_manager = None
        self._cache_dir = None
        self._current_tts_tasks = {} # Track multiple TTS tasks

    async def start(self):
        """Start the voice service."""
        await super().start()
        try:
            self.voice_manager = VoiceManager()
            self.audio_manager = AudioManager.get_instance()
            if not self.audio_manager.is_running:
                logger.warning("AudioManager is not running. VoiceService might not play audio correctly.")
            
            # Initialize cache directory
            self._cache_dir = Path(self.TTS_CACHE_DIR)
            self._cache_dir.mkdir(exist_ok=True)
            logger.info(f"TTS cache directory: {self._cache_dir.absolute()}")

            logger.info("VoiceService started successfully.")
        except Exception as e:
            logger.error(f"Failed to start VoiceService: {e}", exc_info=True)
            raise

    async def stop(self):
        """Stop the voice service."""
        logger.info("Stopping VoiceService...")
        
        # Cancel all active TTS tasks
        for task in list(self._current_tts_tasks.values()):
            if not task.done():
                task.cancel()
        await asyncio.gather(*self._current_tts_tasks.values(), return_exceptions=True)
        
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

    def _process_and_buffer_audio_chunk(self, tts_producer, audio_chunk_bytes: bytes) -> bool:
        """
        Process audio chunk bytes and buffer them for playback.
        
        Args:
            tts_producer: The audio producer to use for this TTS request
            audio_chunk_bytes: Raw PCM audio bytes
            
        Returns:
            bool: True if processing was successful, False otherwise
        """
        if not audio_chunk_bytes:
            logger.warning("Received empty audio chunk bytes.")
            return False
            
        # Convert PCM bytes to numpy array
        audio_np_array = self.voice_manager.pcm_bytes_to_numpy(audio_chunk_bytes)
        
        if audio_np_array.size > 0:
            # Resize the chunk using the producer's own resizer method
            resized_chunks = tts_producer.resize_chunk(audio_np_array)
            for chunk_to_put in resized_chunks:
                try:
                    tts_producer.buffer.put(chunk_to_put)
                except asyncio.QueueFull:
                    logger.warning(f"TTS audio producer buffer full for '{tts_producer.name}'. Audio chunk dropped.")
            return True
        else:
            logger.warning("Received empty audio array after conversion.")
            return False

    def _tts_task_done_callback(self, producer_name: str, task: asyncio.Task):
        try:
            # This will re-raise any exception caught during the task's execution
            task.result()
            logger.info(f"TTS task for producer '{producer_name}' completed.")
        except asyncio.CancelledError:
            logger.info(f"TTS task for producer '{producer_name}' was successfully cancelled.")
        except Exception as e:
            logger.error(f"TTS playback task for producer '{producer_name}' failed: {e}", exc_info=True)
        finally:
            # Remove the task from tracking
            self._current_tts_tasks.pop(producer_name, None)

    async def handle_event(self, event: Dict[str, Any]):
        """Handle events, specifically 'speak_audio' for TTS."""
        event_type = event.get("type")

        if event_type == "speak_audio":
            text_to_speak = event.get("text")
            voice_id = event.get("voice_id")
            model_id = event.get("model_id")
            on_finish_event = event.get("on_finish_event")

            if not text_to_speak:
                logger.warning("'speak_audio' event received without 'text'.")
                return

            if not self.voice_manager:
                logger.error("VoiceManager not initialized. Cannot speak audio.")
                return
            
            # Fire-and-forget the speak method to handle the full lifecycle
            asyncio.create_task(self.speak(text_to_speak, voice_id, model_id, on_finish_event))

    async def speak(self, text: str, voice_id: Optional[str] = None, model_id: Optional[str] = None, on_finish_event: Optional[asyncio.Event] = None):
        """
        Manages the lifecycle of a TTS request using a temporary, per-request audio producer.
        """
        # 1. Generate a unique producer name for this specific TTS request
        producer_name = f"tts_{hashlib.sha1(text.encode()).hexdigest()[:10]}"

        # 2. Cancel any previous task using the same producer name (should be rare)
        if producer_name in self._current_tts_tasks:
            self._current_tts_tasks[producer_name].cancel()

        # 3. Define the on_finish callback for the producer
        def _on_finish(name):
            logger.info(f"Audio producer '{name}' finished playing.")
            if on_finish_event and not on_finish_event.is_set():
                on_finish_event.set()
        
        # 4. Create a new, temporary producer for this request
        try:
            tts_producer = self.audio_manager.add_producer(
                name=producer_name,
                chunk_size=AudioBaseConfig.CHUNK_SIZE,
                buffer_size=AudioBaseConfig.BUFFER_SIZE * 10,
                is_stream=True # Mark as stream so it's not removed prematurely
            )
            tts_producer.on_finish = _on_finish
            self.audio_manager.set_producer_volume(producer_name, AudioBaseConfig.DEFAULT_VOLUME)
        except Exception as e:
            logger.error(f"Failed to create temporary TTS audio producer '{producer_name}': {e}")
            if on_finish_event: on_finish_event.set() # Unblock the caller
            return

        logger.info(f"Received speak_audio event for text: '{text[:30]}...' using producer '{producer_name}'")
        
        # 5. Create and run new task for streaming/playing
        cached_audio = await self._check_cache(text, voice_id, model_id)
        
        if cached_audio:
            play_coro = self._play_cached_audio(tts_producer, cached_audio)
        else:
            play_coro = self._stream_and_play_tts(tts_producer, text, voice_id, model_id)

        task = asyncio.create_task(play_coro)
        self._current_tts_tasks[producer_name] = task
        task.add_done_callback(lambda t: self._tts_task_done_callback(producer_name, t))

    async def _play_cached_audio(self, tts_producer, audio_data: bytes):
        """Play cached audio data chunk by chunk to allow for cancellation."""
        try:
            logger.info(f"Playing cached TTS audio for producer '{tts_producer.name}'...")
            audio_np_array = self.voice_manager.pcm_bytes_to_numpy(audio_data)
            
            processing_chunk_size = AudioBaseConfig.CHUNK_SIZE * 10 

            for i in range(0, len(audio_np_array), processing_chunk_size):
                await asyncio.sleep(0)
                
                chunk_np = audio_np_array[i:i + processing_chunk_size]
                
                if not self._process_and_buffer_audio_chunk(tts_producer, chunk_np.tobytes()):
                    logger.warning(f"Failed to process a chunk of cached audio for '{tts_producer.name}'.")
                    break
            
            logger.info(f"Finished queuing cached TTS audio for '{tts_producer.name}'.")
            # Mark the producer as no longer loading, so it can be cleaned up when buffer is empty
            tts_producer.loading = False
            tts_producer.is_stream = False

        except asyncio.CancelledError:
            logger.info(f"Cached audio playback for '{tts_producer.name}' was cancelled.")
            self.audio_manager.remove_producer(tts_producer.name)
            raise
        except Exception as e:
            logger.error(f"Error playing cached audio for '{tts_producer.name}': {e}", exc_info=True)
            self.audio_manager.remove_producer(tts_producer.name)

    async def _stream_and_play_tts(self, tts_producer, text: str, voice_id: str = None, model_id: str = None):
        """Generates audio stream using VoiceManager and plays it via AudioManager."""
        try:
            tts_producer.loading = True # Mark as loading to prevent premature cleanup
            audio_stream_iterator = await self.voice_manager.generate_audio_stream(
                text,
                voice_id=voice_id,
                model_id=model_id
            )

            if not audio_stream_iterator:
                logger.error(f"Failed to get audio stream from VoiceManager for '{tts_producer.name}'.")
                self.audio_manager.remove_producer(tts_producer.name)
                return

            logger.info(f"Streaming TTS audio from ElevenLabs for '{tts_producer.name}'...")
            
            all_audio_chunks = []
            
            async for audio_chunk_bytes in audio_stream_iterator:
                if audio_chunk_bytes:
                    all_audio_chunks.append(audio_chunk_bytes)
                    self._process_and_buffer_audio_chunk(tts_producer, audio_chunk_bytes)
                        
            logger.info(f"Finished streaming TTS audio for '{tts_producer.name}'.")
            
            if all_audio_chunks:
                combined_audio = b''.join(all_audio_chunks)
                await self._save_to_cache(combined_audio, text, voice_id, model_id)

            # Mark as finished loading so it can be cleaned up
            tts_producer.loading = False
            tts_producer.is_stream = False

        except asyncio.CancelledError:
            logger.info(f"TTS streaming for '{tts_producer.name}' was cancelled.")
            self.audio_manager.remove_producer(tts_producer.name) # Ensure cleanup on cancel
            raise
        except Exception as e:
            logger.error(f"Error during TTS streaming for '{tts_producer.name}': {e}", exc_info=True)
            self.audio_manager.remove_producer(tts_producer.name) # Ensure cleanup on error 