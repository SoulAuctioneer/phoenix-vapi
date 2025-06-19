"""
Provides Text-to-Speech (TTS) functionality by interfacing with VoiceManager and AudioManager.

This service manages the lifecycle of TTS requests, including caching, streaming from an API
(like ElevenLabs), and handling playback completion notifications in a thread-safe manner.

TTS Event Flow:
----------------

1.  **Initiation (e.g., `SquealingActivity`)**:
    *   A service creates an `asyncio.Event` object to act as a completion signal.
    *   It publishes a `speak_audio` event, including the text and the `on_finish_event`.
    *   The service then waits on the event using `await tts_finished_event.wait()`.

2.  **Event Distribution (`ServiceManager`)**:
    *   The `ServiceManager` broadcasts the `speak_audio` event to subscribers.

3.  **TTS Handling (`VoiceService` - Main Thread)**:
    *   `VoiceService.handle_event` receives the event and its payload.
    *   It creates a non-blocking background task by calling `VoiceService.speak()`.

4.  **Playback Preparation (`VoiceService.speak` - Main Thread)**:
    *   A unique producer name is generated for the TTS request.
    *   A thread-safe callback, `_on_finish`, is defined to set the `on_finish_event`
      on the main event loop.
    *   `AudioManager` creates a new audio producer with the `_on_finish` callback attached.
    *   The service checks for a cached audio file. If found, it's queued for playback.
      If not, it streams the audio from the API, plays it, and caches it.

5.  **Audio Playback (`AudioManager` - Background Thread)**:
    *   The `AudioManager`'s output loop (in a separate thread) pulls audio chunks
      from the producer's buffer and sends them to the speaker.
    *   When the buffer is empty and streaming is complete, it invokes the `_on_finish`
      callback.

6.  **Completion Signal (Crossing the Thread Boundary)**:
    *   The `_on_finish` function executes within the `AudioManager`'s background thread.
    *   It uses `loop.call_soon_threadsafe(on_finish_event.set)` to safely schedule
      the `set()` operation on the main `asyncio` event loop.

7.  **Execution Resumes (Main Thread)**:
    *   The `asyncio` event loop executes `on_finish_event.set()`.
    *   The original service, paused at `await`, is unblocked and continues execution.

ASCII Flow Diagram:
-------------------

+--------------------------------+      +------------------+      +---------------------------------+      +-------------------------------------+
| SquealingActivity              |      | ServiceManager   |      | VoiceService (Main Thread)      |      | AudioManager (Background Thread)    |
| (or any other service)         |      |                  |      |                                 |      |                                     |
+--------------------------------+      +------------------+      +---------------------------------+      +-------------------------------------+
               |                               |                                 |                                     |
1. create `tts_finished_event`   |                                 |                                     |
               |                               |                                 |                                     |
2. `publish("speak_audio", ...)` |                                 |                                     |
               |------------------------------>|                                 |                                     |
               |                               |                                 |                                     |
3. `await tts_finished_event.wait()` |         4. Distribute Event           |                                     |
         (Execution Pauses)        |------------------------------>| 5. `handle_event` receives event    |
               |                               |                                 |      - Unpacks `on_finish_event`      |
               |                               |                                 |      - `create_task(speak())`         |
               |                               |                                 |                                     |
               |                               |                                 | 6. `speak()` runs                   |
               |                               |                                 |      - Defines `_on_finish` callback  |
               |                               |                                 |      - `add_producer` with callback   |
               |                               |                                 |------------------------------------->| 7. Producer created with callback
               |                               |                                 |                                     |
               |                               |                                 | 8. Stream/Play audio via producer   |
               |                               |                                 |------------------------------------->| 9. `_output_loop` plays audio
               |                               |                                 |                                     |      from producer buffer
               |                               |                                 |                                     |
               |                               |                                 |                                     |           ... audio plays ...
               |                               |                                 |                                     |
               |                               |                                 |                                     | 10. Buffer empty, playback ends
               |                               |                                 |                                     |      Calls `producer.on_finish()`
               |                               |                                 |                                     |
               |                               |                      (Callback in Audio Thread)         |
               |                               |                                 |<-------------------------------------| 11. `_on_finish` is executed
               |                               |                                 |                                     |
               |                               |                                 | 12. `loop.call_soon_threadsafe(...)`|
               |                               |                                 |         (Schedules on Main Thread)  |
               |                               |                                 |                                     |
       (Execution still Paused)    |                                 | 13. `on_finish_event.set()` is run  |
               |                               |                                 |      by the main event loop         |
               |                               |                                 |                                     |
14. `wait()` unblocks            |                               |                                     |
    (Execution Resumes)          |                               |                                     |
               |                               |                                 |                                     |

"""
import logging
import asyncio
import os
import hashlib
import aiofiles
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

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
    TTS_PRODUCER_NAME = "elevenlabs_tts" # A constant name for the TTS audio producer
    DEFAULT_PITCH = 4.0

    def __init__(self, service_manager):
        super().__init__(service_manager)
        self.voice_manager = None
        self.audio_manager = None
        self._cache_dir = None
        self._current_tts_task: Optional[Tuple[asyncio.Task, Optional[asyncio.Event]]] = None

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
        
        # Cancel the active TTS task if it exists
        if self._current_tts_task:
            task, event = self._current_tts_task
            if not task.done():
                task.cancel()
                if event:
                    event.set() # Ensure waiters are not stuck
        
        # Await the task to ensure it's cancelled
        if self._current_tts_task:
            await asyncio.gather(self._current_tts_task[0], return_exceptions=True)

        # Clean up the audio producer from the manager
        if self.audio_manager:
            self.audio_manager.remove_producer(self.TTS_PRODUCER_NAME)
        
        self.voice_manager = None # Release VoiceManager instance
        await super().stop()
        logger.info("VoiceService stopped.")

    def _generate_cache_key(self, text: str, voice_id: Optional[str] = None, model_id: Optional[str] = None, stability: Optional[float] = None, style: Optional[float] = None, use_speaker_boost: Optional[bool] = None, pitch: Optional[float] = None) -> str:
        """Generate a unique cache key based on text and TTS parameters."""
        # Use default values if not provided
        from config import ElevenLabsConfig
        voice_id = voice_id or ElevenLabsConfig.DEFAULT_VOICE_ID
        model_id = model_id or ElevenLabsConfig.DEFAULT_MODEL_ID
        
        # Create a unique string combining all parameters
        cache_string = f"{text}|{voice_id}|{model_id}|{stability}|{style}|{use_speaker_boost}|{pitch}"
        
        # Generate SHA256 hash for filename
        hash_object = hashlib.sha256(cache_string.encode('utf-8'))
        return hash_object.hexdigest()

    def _get_cache_path(self, cache_key: str) -> Path:
        """Get the full path for a cached audio file."""
        return self._cache_dir / f"{cache_key}.pcm"

    async def _check_cache(self, text: str, voice_id: Optional[str] = None, model_id: Optional[str] = None, stability: Optional[float] = None, style: Optional[float] = None, use_speaker_boost: Optional[bool] = None, pitch: Optional[float] = None) -> Optional[bytes]:
        """Check if audio is cached and return it if available."""
        cache_key = self._generate_cache_key(text, voice_id, model_id, stability, style, use_speaker_boost, pitch)
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

    async def _save_to_cache(self, audio_data: bytes, text: str, voice_id: Optional[str] = None, model_id: Optional[str] = None, stability: Optional[float] = None, style: Optional[float] = None, use_speaker_boost: Optional[bool] = None, pitch: Optional[float] = None):
        """Save audio data to cache."""
        cache_key = self._generate_cache_key(text, voice_id, model_id, stability, style, use_speaker_boost, pitch)
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

    def _tts_task_done_callback(self, task: asyncio.Task):
        # The task is already done, so we just need to log and clean up.
        # The 'on_finish_event' is handled either upon natural completion (in _on_finish)
        # or upon cancellation (in handle_event).
        try:
            # This will re-raise any exception caught during the task's execution
            task.result()
            logger.info(f"TTS task for producer '{self.TTS_PRODUCER_NAME}' completed successfully.")
        except asyncio.CancelledError:
            logger.info(f"TTS task for producer '{self.TTS_PRODUCER_NAME}' was successfully cancelled.")
        except Exception as e:
            logger.error(f"TTS playback task for producer '{self.TTS_PRODUCER_NAME}' failed: {e}", exc_info=True)
        finally:
            # Clear the current task
            if self._current_tts_task and self._current_tts_task[0] == task:
                self._current_tts_task = None

    async def handle_event(self, event: Dict[str, Any]):
        """Handle events, specifically 'speak_audio' for TTS."""
        event_type = event.get("type")
        if event_type == "speak_audio":
            # --- Cancel any existing TTS task ---
            if self._current_tts_task:
                old_task, old_event = self._current_tts_task
                if not old_task.done():
                    logger.warning("New 'speak_audio' request received. Cancelling the previous one.")
                    old_task.cancel()
                    # Signal the old event immediately to prevent deadlocks
                    if old_event and not old_event.is_set():
                        old_event.set()
            
            # --- Process the new request ---
            text_to_speak = event.get("text")
            if not text_to_speak:
                logger.warning("'speak_audio' event received without 'text'.")
                if event.get("on_finish_event"):
                    event["on_finish_event"].set()
                return

            if not self.voice_manager:
                logger.error("VoiceManager not initialized. Cannot speak audio.")
                if event.get("on_finish_event"):
                    event["on_finish_event"].set()
                return

            # Create and store the new task
            task = asyncio.create_task(self.speak(event))
            self._current_tts_task = (task, event.get("on_finish_event"))
            task.add_done_callback(self._tts_task_done_callback)

    async def speak(self, event: Dict[str, Any]):
        """
        Manages the lifecycle of a TTS request using a temporary, per-request audio producer.
        This coroutine is managed by `handle_event` and should not be called directly.
        """
        # 1. Extract parameters from the event
        text = event.get("text")
        voice_id = event.get("voice_id")
        model_id = event.get("model_id")
        stability = event.get("stability")
        style = event.get("style")
        use_speaker_boost = event.get("use_speaker_boost")
        pitch = event.get("pitch", self.DEFAULT_PITCH)
        on_finish_event = event.get("on_finish_event")

        # 2. Define the on_finish callback for the producer
        loop = asyncio.get_running_loop()
        def _on_finish(producer_name):
            logger.info(f"Audio producer '{producer_name}' finished playing naturally.")
            if on_finish_event:
                try:
                    # Use call_soon_threadsafe because this is called from the AudioManager thread
                    loop.call_soon_threadsafe(on_finish_event.set)
                except Exception as e:
                    logger.error(f"Error setting on_finish_event for '{producer_name}': {e}")
        
        # 3. Get or create the producer
        try:
            tts_producer = self.audio_manager.add_producer(
                name=self.TTS_PRODUCER_NAME,
                chunk_size=AudioBaseConfig.CHUNK_SIZE,
                buffer_size=AudioBaseConfig.BUFFER_SIZE * 10,
                is_stream=True
            )
            tts_producer.on_finish = _on_finish
            tts_producer.clear() # Clear any leftover data
            self.audio_manager.set_producer_volume(self.TTS_PRODUCER_NAME, AudioBaseConfig.DEFAULT_VOLUME)
        except Exception as e:
            logger.error(f"Failed to create/get TTS audio producer '{self.TTS_PRODUCER_NAME}': {e}")
            if on_finish_event:
                on_finish_event.set()
            return

        logger.info(f"Processing speak_audio event for text: '{text[:30]}...'")
        
        # 4. Check cache or stream audio
        cached_audio = await self._check_cache(text, voice_id, model_id, stability, style, use_speaker_boost, pitch)
        
        play_coro = None
        if cached_audio:
            play_coro = self._play_cached_audio(tts_producer, cached_audio)
        else:
            play_coro = self._stream_and_play_tts(tts_producer, text, voice_id, model_id, stability, style, use_speaker_boost, pitch)

        # 5. Execute playback
        try:
            await play_coro
        except asyncio.CancelledError:
            logger.info(f"TTS speak task for '{text[:30]}...' was cancelled.")
            # Do NOT remove the producer here, as a new task may be about to use it.
            # The producer is a shared resource, managed by the service's start/stop lifecycle.
            raise # Re-raise CancelledError to be handled by the done callback
        except Exception as e:
            logger.error(f"Error during TTS playback for '{text[:30]}...': {e}", exc_info=True)
            if on_finish_event:
                on_finish_event.set()

        # Mark the producer as no longer loading, so it can be cleaned up when buffer is empty
        tts_producer.loading = False
        tts_producer.is_stream = False

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
            # Do not remove producer on cancellation, it's a shared resource.
            raise
        except Exception as e:
            logger.error(f"Error playing cached audio for '{tts_producer.name}': {e}", exc_info=True)
            self.audio_manager.remove_producer(tts_producer.name)

    async def _stream_and_play_tts(self, tts_producer, text: str, voice_id: str = None, model_id: str = None, stability: float = None, style: float = None, use_speaker_boost: bool = None, pitch: float = 0.0):
        """Generates audio stream using VoiceManager and plays it via AudioManager."""
        try:
            tts_producer.loading = True # Mark as loading to prevent premature cleanup
            audio_stream_iterator = await self.voice_manager.generate_audio_stream(
                text,
                voice_id=voice_id,
                model_id=model_id,
                stability=stability,
                style=style,
                use_speaker_boost=use_speaker_boost,
                pitch=pitch
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
                await self._save_to_cache(combined_audio, text, voice_id, model_id, stability, style, use_speaker_boost, pitch)

            # Mark as finished loading so it can be cleaned up
            tts_producer.loading = False
            tts_producer.is_stream = False

        except asyncio.CancelledError:
            logger.info(f"TTS streaming for '{tts_producer.name}' was cancelled.")
            # Do not remove producer on cancellation, it's a shared resource.
            raise
        except Exception as e:
            logger.error(f"Error during TTS streaming for '{tts_producer.name}': {e}", exc_info=True)
            self.audio_manager.remove_producer(tts_producer.name) # Ensure cleanup on error 