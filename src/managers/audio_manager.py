"""
Simplified audio manager that handles audio input and output with improved efficiency.
Focuses solely on 16kHz mono int16 audio with simplified buffer management.
"""
import logging
import numpy as np
import sounddevice as sd
import time
import threading
import wave
import os
import queue
import concurrent.futures
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Dict, List, Optional, Callable, Union, Tuple
from config import AudioBaseConfig, SoundEffect
import random

@dataclass
class AudioConfig:
    """Audio configuration parameters for mono int16 audio processing"""
    channels: int = AudioBaseConfig.NUM_CHANNELS
    chunk: int = AudioBaseConfig.CHUNK_SIZE
    input_device_index: Optional[int] = None
    output_device_index: Optional[int] = None
    default_volume: float = AudioBaseConfig.DEFAULT_VOLUME
    
    def get_channels(self) -> int:
        """Get the number of output channels to use"""
        return max(1, self.channels)  # Ensure at least mono

class AudioConsumer:
    """Audio consumer that receives and processes audio data"""
    
    def __init__(self, callback: Callable[[np.ndarray], None], chunk_size: Optional[int] = None):
        """
        Initialize a new audio consumer
        
        Args:
            callback: Function to call with audio data
            chunk_size: If specified, audio data will be chunked to this size
        """
        self.callback = callback
        self.chunk_size = chunk_size
        self.active = True
        # Buffer for rechunking if needed
        self._audio_buffer = np.array([], dtype=np.int16) if chunk_size else None

class AudioProducer:
    """
    Audio producer that generates audio data for playback
    
    Optimized for CPU efficiency and minimal memory allocation
    """
    
    def __init__(self, name: str, max_buffer_size: int = 100):
        """
        Initialize a new audio producer
        
        Args:
            name: Name of the producer (for debugging)
            max_buffer_size: Maximum size of the producer's buffer
        """
        self.name = name
        self.active = True
        self.loop = False
        
        # Volume control
        self._volume = 1.0  # Default to max volume
        
        # Buffer for audio data
        self._buffer = queue.Queue(maxsize=max_buffer_size)
        
        # Storage for loop data chunks
        self._loop_chunks = []
        
    @property
    def volume(self) -> float:
        """Get current volume level (0.0 to 1.0)"""
        return self._volume
        
    @volume.setter
    def volume(self, value: float):
        """
        Set volume level (0.0 to 1.0)
        Args:
            value: Volume level to set
        """
        self._volume = max(0.0, min(1.0, value))
        logging.info(f"Producer '{self.name}' volume set to {self._volume}")
        
    def put(self, data: np.ndarray) -> bool:
        """
        Put audio data in the buffer
        
        Args:
            data: Audio data as numpy array
            
        Returns:
            bool: True if successful, False if buffer is full
        """
        if not self.active:
            return False
            
        try:
            # Non-blocking put to avoid deadlocks
            self._buffer.put_nowait(data)
            return True
        except queue.Full:
            return False
    
    def clear(self):
        """Clear all audio data from the buffer"""
        try:
            # Clear the buffer
            while not self._buffer.empty():
                self._buffer.get_nowait()
                
            # Also clear loop chunks
            self._loop_chunks = []
            
            logging.debug(f"Producer '{self.name}' buffer cleared")
        except Exception as e:
            logging.error(f"Error clearing producer buffer: {e}")
            
    def set_loop_data(self, audio_data: np.ndarray, chunk_size: int):
        """
        Set audio data for looping playback
        
        Args:
            audio_data: Audio data as numpy array
            chunk_size: Size of chunks to split the data into
        """
        # Clear existing loop data
        self._loop_chunks = []
        
        # Split audio data into chunks for looping
        for i in range(0, len(audio_data), chunk_size):
            end = min(i + chunk_size, len(audio_data))
            chunk = audio_data[i:end]
            
            # Pad the last chunk if necessary
            if len(chunk) < chunk_size:
                chunk = np.pad(chunk, (0, chunk_size - len(chunk)), mode='constant')
                
            # Store the chunk for looping
            self._loop_chunks.append(chunk)
            
        logging.debug(f"Producer '{self.name}' loop data set with {len(self._loop_chunks)} chunks")
        
    def get(self) -> Optional[np.ndarray]:
        """
        Get audio data from the buffer with volume applied
        
        Returns:
            np.ndarray: Audio data with volume applied, or None if buffer is empty
        """
        try:
            data = self._buffer.get_nowait()
            if data is None:
                return None
                
            # OPTIMIZATION: Only apply volume if not at maximum
            if self._volume < 1.0:
                # Scale to float in [-1, 1] range, apply volume, then back to int16
                # Converting to float32 is faster than float64
                data = np.clip(
                    (data.astype(np.float32) / 32767.0 * self._volume * 32767.0), 
                    -32767, 32767
                ).astype(np.int16)
                
            # Log at debug level for troubleshooting
            if logging.getLogger().isEnabledFor(logging.DEBUG):
                logging.debug(f"Producer '{self.name}' returned {len(data)} samples with volume {self._volume}")
                
            return data
        except queue.Empty:
            # Try to refill buffer from loop chunks if looping is enabled
            if self.loop and self._loop_chunks and self._buffer.empty():
                # Log at debug level to avoid overhead
                if logging.getLogger().isEnabledFor(logging.DEBUG):
                    logging.debug(f"Refilling buffer for looping producer '{self.name}' with {len(self._loop_chunks)} chunks")
                    
                # Add chunks without copying if possible to reduce allocations
                for chunk in self._loop_chunks:
                    # If the producer is no longer active, stop refilling
                    if not self.active:
                        return None
                    # Use a shared reference when safe, copy only when needed
                    if not self.put(chunk if self._volume == 1.0 else chunk.copy()):
                        break
                        
                # Try again after refilling
                try:
                    data = self._buffer.get_nowait()
                    if data is None:
                        return None
                        
                    # Only apply volume if needed
                    if self._volume < 1.0:
                        # Scale to float in [-1, 1] range, apply volume, then back to int16
                        data = np.clip(
                            (data.astype(np.float32) / 32767.0 * self._volume * 32767.0), 
                            -32767, 32767
                        ).astype(np.int16)
                        
                    # Log at debug level for troubleshooting
                    if logging.getLogger().isEnabledFor(logging.DEBUG):
                        logging.debug(f"Producer '{self.name}' returned {len(data)} looped samples with volume {self._volume}")
                        
                    return data
                except queue.Empty:
                    pass
            return None

class AudioManager:
    """Manages audio resources using SoundDevice for 16kHz mono int16 audio"""
    _instance = None

    @classmethod
    def get_instance(cls, config: AudioConfig = None) -> 'AudioManager':
        """Get or create the AudioManager singleton instance"""
        if cls._instance is None:
            if config is None:
                config = AudioConfig()
            cls._instance = cls(config)
        return cls._instance

    def __init__(self, config: AudioConfig = AudioConfig()):
        """Initialize the audio manager with the given configuration"""
        if AudioManager._instance is not None:
            raise RuntimeError("Use AudioManager.get_instance() to get the AudioManager instance")
            
        self.config = config
        self._stream = None
        self._lock = threading.Lock()
        self._running = False
        
        # Audio consumers and producers
        self._consumers: List[AudioConsumer] = []
        self._producers: Dict[str, AudioProducer] = {}
        
        # Use finer-grained locks for different resource types to minimize contention
        self._consumers_lock = threading.Lock()
        self._producers_lock = threading.Lock()
        self._stream_lock = threading.Lock()  # For audio stream operations
        self._sound_effect_lock = threading.Lock()  # For sound effect operations
        
        # Thread-local storage for temporary buffers to avoid allocations
        self._thread_local = threading.local()
        
        # Dedicated thread pool for audio operations to improve performance
        # Using max_workers=2 to avoid excessive parallelism while still allowing concurrent operations
        self._audio_thread_pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=2, 
            thread_name_prefix="audio_worker"
        )
        logging.info("Created dedicated thread pool for audio operations")
        
        # Cache for sound effects to avoid repeated loading from disk
        self._sound_effect_cache = {}
        self._sound_effect_cache_lock = threading.Lock()
        
        # Track sound effect producers for easier management
        self._sound_effect_producers = {}  # Maps effect_name -> producer_name
        
    def add_consumer(self, callback: Callable[[np.ndarray], None], 
                     chunk_size: Optional[int] = None, 
                     sample_rate: Optional[int] = None) -> AudioConsumer:
        """
        Add a new audio consumer
        
        Args:
            callback: Function that will receive audio data chunks
            chunk_size: If specified, audio will be delivered in chunks of this size
            sample_rate: This parameter is ignored as the system always uses 16kHz
            
        Returns:
            AudioConsumer: The created consumer instance
        """
        # Ignore sample_rate parameter - we always use 16kHz
        if sample_rate is not None and sample_rate != AudioBaseConfig.SAMPLE_RATE:
            logging.warning(f"Ignoring requested sample rate {sample_rate}Hz - system always uses {AudioBaseConfig.SAMPLE_RATE}Hz")
            
        consumer = AudioConsumer(callback, chunk_size)
        with self._consumers_lock:
            self._consumers.append(consumer)
        return consumer
        
    def remove_consumer(self, consumer: AudioConsumer):
        """Remove an audio consumer"""
        with self._consumers_lock:
            if consumer in self._consumers:
                consumer.active = False
                self._consumers.remove(consumer)
                
    def add_producer(self, name: str, buffer_size: int = 100, 
                    initial_volume: Optional[float] = None) -> AudioProducer:
        """
        Add a new audio producer
        
        Args:
            name: Name for the producer
            buffer_size: Size of the producer's buffer
            initial_volume: Initial volume (0.0 to 1.0)
            
        Returns:
            AudioProducer: The created producer
        """
        logging.info(f"Creating producer: {name} with buffer_size={buffer_size}")
        
        producer = AudioProducer(name, max_buffer_size=buffer_size)
        if initial_volume is not None:
            producer.volume = initial_volume
            
        with self._producers_lock:
            self._producers[name] = producer
            logging.info(f"Producer '{name}' added and activated")
            
        return producer
        
    def remove_producer(self, name: str):
        """Remove an audio producer with minimized lock time"""
        # Only acquire lock for the dictionary operation, not for cleanup
        producer = None
        with self._producers_lock:
            if name in self._producers:
                producer = self._producers[name]
                producer.active = False
                del self._producers[name]
        
        # If we got a producer, clear it outside the lock
        if producer:
            producer.clear()  # This doesn't need to be under lock
    
    def set_producer_volume(self, name: str, volume: float):
        """Set volume for a specific producer"""
        with self._producers_lock:
            if name in self._producers:
                self._producers[name].volume = max(0.0, min(1.0, volume))
                
    @property
    def is_running(self) -> bool:
        """Check if the audio manager is running"""
        return self._running
    
    def _get_temp_buffer(self, size, dtype=np.int16):
        """
        Get a thread-local temporary buffer to avoid allocations in real-time audio code
        
        Args:
            size: Size of buffer needed
            dtype: NumPy data type of the buffer (default: np.int16)
            
        Returns:
            NumPy array with requested size and type
        """
        # Create thread_local.buffers dictionary if it doesn't exist
        if not hasattr(self._thread_local, 'buffers'):
            self._thread_local.buffers = {}
            
        # Create buffer of this size and type if not already cached
        buffer_key = (size, dtype)
        if buffer_key not in self._thread_local.buffers or self._thread_local.buffers[buffer_key].size < size:
            self._thread_local.buffers[buffer_key] = np.zeros(size, dtype=dtype)
            
        # Return the buffer (sliced to the correct size)
        return self._thread_local.buffers[buffer_key][:size]
    
    def _process_input(self, indata, frames):
        """Process input audio data and distribute to consumers"""
        if indata is None or frames == 0:
            return
            
        # Get mono from first channel for input processing
        audio_data = indata[:, 0].copy().astype(np.int16)
        
        # Check if audio is too silent (common issue causing empty audio issues)
        if np.max(np.abs(audio_data)) < 50:  # Very quiet, likely just noise
            return
            
        # OPTIMIZATION: Get a snapshot of active consumers under lock
        # This minimizes the time we hold the lock to just the snapshot operation
        active_consumers = []
        with self._consumers_lock:
            # Only collect references to active consumers
            active_consumers = [(c, c.chunk_size, c.callback) for c in self._consumers if c.active]
            
        # No active consumers, early return
        if not active_consumers:
            return
            
        # Process consumers WITHOUT holding the lock
        for consumer, chunk_size, callback in active_consumers:
            try:
                # Check if this consumer needs specific chunk_size handling
                if chunk_size is not None and chunk_size != frames:
                    # NOTE: We're modifying consumer._audio_buffer outside the lock
                    # This is acceptable if consumers are only modified from the main thread
                    # For true thread-safety, consider implementing per-consumer locks
                    
                    # Initialize this consumer's audio buffer if needed
                    # Need to access consumer directly to modify its buffer
                    if consumer._audio_buffer is None:
                        with self._consumers_lock:
                            if consumer.active:  # Double-check it's still active
                                consumer._audio_buffer = np.array([], dtype=np.int16)
                            else:
                                continue
                    
                    # Combine with existing buffer
                    # NOTE: We're using the consumer's buffer directly, which
                    # could be modified by other threads. This is a potential race condition.
                    with self._consumers_lock:
                        if consumer.active:  # Double-check active before processing
                            consumer._audio_buffer = np.concatenate([consumer._audio_buffer, audio_data])
                        else:
                            continue
                    
                    # Process complete chunks
                    buffer_size = len(consumer._audio_buffer)
                    while consumer.active and buffer_size >= chunk_size:
                        # Extract one chunk of the desired size
                        with self._consumers_lock:
                            if not consumer.active:
                                break
                            chunk = consumer._audio_buffer[:chunk_size]
                            consumer._audio_buffer = consumer._audio_buffer[chunk_size:]
                            buffer_size = len(consumer._audio_buffer)
                        
                        # Call the callback outside the lock
                        callback(chunk)
                else:
                    # No special handling needed, just pass the data directly
                    callback(audio_data)
            except Exception as e:
                logging.error(f"Error processing audio for consumer: {e}", exc_info=True)
    
    def _process_output(self, outdata, frames):
        """Fill output buffer with mixed audio from all producers"""
        # Initialize output data with zeros
        outdata.fill(0)
        
        # Get output channel count
        num_channels = outdata.shape[1]
        
        # OPTIMIZATION: Capture producer data under lock, then process without lock
        # This minimizes the time we hold the lock to just the data acquisition
        active_producers_data = []
        
        # Use a shorter critical section - only acquire data while holding lock
        with self._producers_lock:
            # Only get references to active producers and their data
            producer_count = 0
            for name, producer in self._producers.items():
                if producer.active:
                    producer_count += 1
                    data = producer.get()  # Get data while holding lock
                    if data is not None and data.size > 0:
                        active_producers_data.append((name, data))
            
            # Occasionally log info about active producers for debugging
            if logging.getLogger().isEnabledFor(logging.DEBUG) and random.random() < 0.01:  # ~1% of callbacks
                logging.debug(f"Active producers: {producer_count}, with data: {len(active_producers_data)}")
        
        # Process the data WITHOUT holding the lock
        has_audio = False
        
        # Log debug info about active producers with data
        if active_producers_data and logging.getLogger().isEnabledFor(logging.DEBUG) and random.random() < 0.05:  # ~5% of callbacks with data
            producer_names = [name for name, _ in active_producers_data]
            logging.debug(f"Processing audio from producers: {producer_names}")
        
        # Mix audio from active producers outside the lock
        for name, data in active_producers_data:
            # Mix mono data into all output channels
            frames_to_mix = min(len(data), frames)
            
            # Make sure data is int16 to prevent unexpected behavior
            if data.dtype != np.int16:
                data = data.astype(np.int16)
            
            # Detailed logging for sound effect producers
            if name.startswith("sound_effect_") and logging.getLogger().isEnabledFor(logging.DEBUG) and random.random() < 0.1:
                max_val = np.max(np.abs(data))
                logging.debug(f"Mixing {name}: {frames_to_mix} frames, max amplitude: {max_val}")
            
            # Efficient duplication to all output channels
            for c in range(num_channels):
                outdata[:frames_to_mix, c] += data[:frames_to_mix]
            
            has_audio = True
        
        # Check if any audio was produced
        if has_audio and np.max(np.abs(outdata)) > 32700:
            # Only clip if necessary to prevent distortion
            np.clip(outdata, -32767, 32767, out=outdata)
            
            # Log clipping for debugging
            if logging.getLogger().isEnabledFor(logging.DEBUG):
                logging.debug("Audio clipping detected - mixing multiple sources at high volume")
                
        # Log when we have no audio but should (debug potential silence issues)
        elif not has_audio and len(self._producers) > 0 and logging.getLogger().isEnabledFor(logging.DEBUG) and random.random() < 0.01:
            active_count = sum(1 for p in self._producers.values() if p.active)
            if active_count > 0:
                logging.debug(f"No audio data available from {active_count} active producers")
    
    def _audio_callback(self, indata, outdata, frames, time, status):
        """
        Unified callback for audio processing (handles both input and output)
        
        Args:
            indata: Input audio data from the microphone (can be None for output-only streams)
            outdata: Output buffer to fill with audio data
            frames: Number of frames to process
            time: Time info from SoundDevice
            status: Status info from SoundDevice
        """
        # Check for any issues with the audio hardware
        if status:
            # Only log at warning level for occasional issues
            if status.input_overflow:
                logging.warning("Audio input overflow - input data may be lost")
            elif status.output_underflow:
                logging.warning("Audio output underflow - output may have gaps")
            else:
                logging.warning(f"Audio callback status: {status}")
        
        try:
            # Process input (distribute to consumers)
            # Only process input if we actually have input data
            if indata is not None and frames > 0:
                self._process_input(indata, frames)
            
            # Process output (mix from producers)
            # Always process output to ensure we fill the buffer
            self._process_output(outdata, frames)
                
        except Exception as e:
            # Log error but continue audio processing to avoid crashes
            logging.error(f"Error in audio callback: {e}", exc_info=True)
            # Fill with zeros on error to prevent noise
            outdata.fill(0)
    
    def start(self):
        """Start audio processing"""
        with self._lock:
            if self._running:
                logging.info("AudioManager already running")
                return
                
            try:
                logging.info("Setting up audio using SoundDevice...")
                
                # Log available devices
                input_devices = self.get_input_devices()
                output_devices = self.get_output_devices()
                logging.info(f"Available input devices: {input_devices}")
                logging.info(f"Available output devices: {output_devices}")
                
                # Get default device info if not specified
                if self.config.output_device_index is None:
                    try:
                        default_output = sd.default.device[1]
                        default_device_info = sd.query_devices(default_output)
                        logging.info(f"Using default output device: {default_device_info['name']}")
                        logging.info(f"Default device details: {default_device_info}")
                        
                        # Force the sample rate to 16kHz regardless of the device's default
                        logging.info(f"Forcing sample rate to {AudioBaseConfig.SAMPLE_RATE}Hz regardless of device default")
                    except Exception as e:
                        logging.warning(f"Couldn't get default device info: {e}")
                
                # Determine what type of stream to create
                # Always create at least an input stream for wakeword detection and other services
                if self.config.input_device_index is not None or len(input_devices) > 0:
                    # Create a duplex stream for both input and output
                    input_device = self.config.input_device_index
                    if input_device is None and len(input_devices) > 0:
                        # Use the default input device if none specified
                        input_device = sd.default.device[0]
                    
                    self._stream = sd.Stream(
                        samplerate=AudioBaseConfig.SAMPLE_RATE,  # Always use 16kHz
                        blocksize=self.config.chunk,
                        channels=(1, self.config.get_channels()),  # Always mono input, but allow multiple output channels
                        dtype='int16',  # Always use int16
                        callback=self._audio_callback,
                        device=(input_device, self.config.output_device_index)
                    )
                    logging.info(f"Created duplex stream with 1 input channel and {self.config.get_channels()} output channels at {AudioBaseConfig.SAMPLE_RATE}Hz")
                elif self._producers:
                    # Only output needed, no input capabilities
                    logging.info("Creating output-only stream")
                    
                    self._stream = sd.OutputStream(
                        samplerate=AudioBaseConfig.SAMPLE_RATE,  # Always use 16kHz
                        blocksize=self.config.chunk,
                        channels=self.config.get_channels(),  # Allow multiple output channels
                        dtype='int16',  # Always use int16
                        callback=self._audio_callback,
                        device=self.config.output_device_index
                    )
                    logging.info(f"Created output-only stream with {self.config.get_channels()} channels at {AudioBaseConfig.SAMPLE_RATE}Hz")
                else:
                    logging.warning("No input devices found and no producers registered. Audio functionality will be limited.")
                    return
                
                # Start the stream
                self._stream.start()
                self._running = True
                
                logging.info("AudioManager started successfully")
                
            except Exception as e:
                logging.error(f"Failed to start audio: {e}", exc_info=True)
                self.stop()
                raise
                
    def stop(self):
        """Stop audio processing and cleanup resources"""
        with self._lock:
            if not self._running:
                return
                
            self._running = False
            
            # Stop all sound effects first
            self.stop_all_sound_effects()
            
            # Stop all consumers and producers
            with self._consumers_lock:
                for consumer in self._consumers:
                    consumer.active = False
            with self._producers_lock:
                for producer in self._producers.values():
                    producer.active = False
            
            # Stop and close the audio stream
            if self._stream:
                self._stream.stop()
                self._stream.close()
                self._stream = None
                
            # Shutdown the audio thread pool
            try:
                self._audio_thread_pool.shutdown(wait=False)
                logging.info("Audio thread pool shut down")
            except Exception as e:
                logging.error(f"Error shutting down audio thread pool: {e}")
                
            logging.info("AudioManager stopped successfully")

    def play_audio(self, audio_data: np.ndarray, producer_name: str = "default", loop: bool = False):
        """
        Play mono audio data through a specific producer.
        
        Args:
            audio_data: Mono audio data as numpy array (will be converted to int16)
            producer_name: Name of the producer to use 
            loop: Whether to loop the audio (default: False)
        """
        logging.info(f"play_audio called for producer '{producer_name}' with {len(audio_data)} samples, loop={loop}")
        
        try:
            if not self._running:
                logging.warning("play_audio called but AudioManager is not running")
                return
                
            # Create producer if needed
            with self._producers_lock:
                if producer_name not in self._producers:
                    logging.info(f"Creating new producer '{producer_name}'")
                    producer = self.add_producer(producer_name, buffer_size=1000)
                else:
                    # Get existing producer and ensure it's active
                    producer = self._producers[producer_name]
                    if not producer.active:
                        producer.active = True
                        logging.info(f"Reactivated producer '{producer_name}'")
                
                # Clear any existing audio in the producer buffer
                producer.clear()
                
                if not producer.active:
                    logging.warning(f"Producer '{producer_name}' is not active")
                    return
            
            # Check if audio data has the expected shape (1D array for mono)
            if len(audio_data.shape) > 1:
                logging.warning(f"Expected mono audio but got shape {audio_data.shape}. Converting to mono.")
                # Handle multi-dimensional arrays by flattening or taking first channel
                if audio_data.shape[1] > 1:
                    audio_data = audio_data[:, 0]  # Take first channel if stereo
                else:
                    audio_data = audio_data.flatten()
                
            # Ensure data is in int16 format
            if audio_data.dtype != np.int16:
                # Handle conversion from float to int16
                if np.issubdtype(audio_data.dtype, np.floating):
                    # Normalize and scale
                    max_val = np.max(np.abs(audio_data))
                    if max_val > 0:
                        # Scale to use full int16 range
                        normalized = audio_data / max_val
                        audio_data = (normalized * 32767).astype(np.int16)
                    else:
                        # Silent audio - just convert
                        audio_data = audio_data.astype(np.int16)
                else:
                    # Direct conversion for other integer types
                    audio_data = audio_data.astype(np.int16)
            
            # Set loop data if looping is enabled
            producer = self._producers[producer_name]  # Get the producer again without the lock
            if loop:
                producer.set_loop_data(audio_data, self.config.chunk)
                producer.loop = True
                logging.debug(f"Set loop data for producer '{producer_name}' with {len(audio_data)} samples")
            else:
                producer.loop = False
            
            # Split audio data into chunks matching the configured chunk size
            chunk_size = self.config.chunk
            
            # Add chunked data to the producer
            chunks_added = 0
            for i in range(0, len(audio_data), chunk_size):
                end = min(i + chunk_size, len(audio_data))
                chunk = audio_data[i:end]
                
                # Pad the last chunk if necessary
                if len(chunk) < chunk_size:
                    chunk = np.pad(chunk, (0, chunk_size - len(chunk)), mode='constant')
                
                if producer.put(chunk):
                    chunks_added += 1
                else:
                    logging.warning(f"Buffer full for producer '{producer_name}', dropping chunk")
                    break
            
            logging.info(f"Added {chunks_added} mono chunks to producer '{producer_name}'")
                
        except Exception as e:
            logging.error(f"Error in play_audio: {str(e)}", exc_info=True)
            
    def play_sound(self, effect_name: str, loop: bool = False) -> bool:
        """
        Play a sound effect by name.
        Args:
            effect_name: Name of the sound effect (case-insensitive)
            loop: Whether to loop the sound effect (default: False)
        Returns:
            bool: True if the sound effect was found and playback started, False otherwise
        """
        try:
            # Check for debug environment variable to enable additional diagnostics
            debug_audio = os.environ.get("PHOENIX_AUDIO_DEBUG", "0").lower() in ("1", "true", "yes")
            
            effect_name_lower = effect_name.lower()
            filename = SoundEffect.get_filename(effect_name)
            if not filename:
                logging.error(f"Unknown sound effect: {effect_name}")
                return False
            
            wav_path = os.path.join("assets", filename)
            
            # Log diagnostic information in debug mode
            if debug_audio:
                logging.info(f"Sound effect request: '{effect_name}' -> filename: '{filename}'")
                logging.info(f"Using path: {wav_path} (exists: {os.path.exists(wav_path)})")
            
            # Check the cache first for this sound effect
            audio_data = None
            with self._sound_effect_cache_lock:
                if effect_name_lower in self._sound_effect_cache:
                    audio_data = self._sound_effect_cache[effect_name_lower]
                    if debug_audio or logging.getLogger().isEnabledFor(logging.DEBUG):
                        logging.debug(f"Using cached sound effect: {effect_name} ({len(audio_data)} samples)")
            
            # If not in cache, load it and add to cache
            if audio_data is None:
                if not os.path.exists(wav_path):
                    logging.error(f"Sound effect file not found: {wav_path}")
                    # Try to help diagnose the issue
                    if debug_audio:
                        # Check if assets directory exists and list files
                        assets_dir = "assets"
                        if os.path.exists(assets_dir):
                            files = os.listdir(assets_dir)
                            logging.info(f"Assets directory contains {len(files)} files, first 5: {files[:5]}")
                        else:
                            logging.error(f"Assets directory '{assets_dir}' does not exist")
                            # Check the current working directory
                            cwd = os.getcwd()
                            logging.info(f"Current working directory: {cwd}")
                    return False
                    
                # Load the sound data
                try:
                    if debug_audio:
                        logging.info(f"Loading sound effect from disk: {wav_path}")
                    
                    audio_data = self._load_wav_file_data(wav_path)
                    
                    if audio_data is None or len(audio_data) == 0:
                        logging.error(f"Failed to load sound data from {wav_path}: Empty audio data")
                        return False
                    
                    # Cache the sound effect for future use
                    with self._sound_effect_cache_lock:
                        self._sound_effect_cache[effect_name_lower] = audio_data
                        
                    if debug_audio or logging.getLogger().isEnabledFor(logging.DEBUG):
                        logging.debug(f"Cached sound effect: {effect_name} ({len(audio_data)} samples)")
                except Exception as e:
                    logging.error(f"Failed to load sound effect {effect_name}: {e}")
                    if debug_audio:
                        import traceback
                        logging.error(traceback.format_exc())
                    return False
            
            # Create a producer name based on the effect name
            producer_name = f"sound_effect_{effect_name_lower}"
            
            # Track this producer in our sound effect producers map
            self._sound_effect_producers[effect_name_lower] = producer_name
            
            # Play the sound data through the dedicated producer
            success = self._play_audio_data(audio_data, producer_name=producer_name, loop=loop)
            
            if success:
                if debug_audio or logging.getLogger().isEnabledFor(logging.DEBUG):
                    logging.debug(f"Successfully played sound effect '{effect_name}' using producer '{producer_name}'")
            else:
                logging.error(f"Failed to play sound effect '{effect_name}' using producer '{producer_name}'")
                
            return success
        except Exception as e:
            logging.error(f"Unexpected error playing sound effect '{effect_name}': {e}")
            import traceback
            logging.error(traceback.format_exc())
            return False

    def _load_wav_file_data(self, wav_path: str) -> np.ndarray:
        """
        Load a WAV file into a numpy array.
        
        Args:
            wav_path: Path to the WAV file
            
        Returns:
            np.ndarray: Audio data as a numpy array
            
        Raises:
            Exception: If the file couldn't be loaded
        """
        logging.info(f"Loading WAV file: {wav_path}")
        with wave.open(wav_path, "rb") as wf:
            # Get WAV file properties
            channels = wf.getnchannels()
            width = wf.getsampwidth()
            rate = wf.getframerate()
            frames = wf.getnframes()
            
            logging.info(f"WAV file details: channels={channels}, bit depth={width*8}, sample rate={rate}, frames={frames}")
            
            # Read all audio data at once
            audio_data = wf.readframes(frames)
            
            # Convert to numpy array based on bit depth
            if width == 2:  # 16-bit audio
                audio_array = np.frombuffer(audio_data, dtype=np.int16)
            elif width == 1:  # 8-bit audio
                audio_array = np.frombuffer(audio_data, dtype=np.uint8).astype(np.int16) * 256
            elif width == 4:  # 32-bit audio
                audio_array = np.frombuffer(audio_data, dtype=np.int32).astype(np.int16) // 65536
            else:
                audio_array = np.frombuffer(audio_data, dtype=np.int16)
            
            # Ensure we have a valid array
            if audio_array.size == 0:
                raise ValueError(f"WAV file produced empty audio data: {wav_path}")
                
            # Normalize the audio to ensure good volume
            max_amplitude = np.max(np.abs(audio_array))
            if max_amplitude > 0:
                # Scale to use 80% of full int16 range to prevent distortion
                scale_factor = (32767 * 0.8) / max_amplitude
                audio_array = np.clip((audio_array * scale_factor), -32767, 32767).astype(np.int16)
                
            return audio_array
            
    def _play_audio_data(self, audio_data: np.ndarray, producer_name: str = "sound_effect", loop: bool = False) -> bool:
        """
        Play audio data through a producer
        
        Args:
            audio_data: Audio data to play
            producer_name: Name of the producer to use (default: sound_effect)
            loop: Whether to loop the audio (default: False)
            
        Returns:
            bool: True if successful, False otherwise
        """
        if audio_data is None or len(audio_data) == 0:
            logging.error("Cannot play empty audio data")
            return False
            
        if not self.is_running:
            logging.warning("Cannot play audio: Audio Manager is not running")
            return False
            
        # Ensure audio_data is in the expected format (mono int16)
        if audio_data.ndim > 1:
            # Take just the first channel if multi-channel
            audio_data = audio_data[:, 0]
            
        if audio_data.dtype != np.int16:
            # Convert to int16 if needed
            audio_data = audio_data.astype(np.int16)
            
        try:
            # Efficiently handle playing audio data through the producer
            with self._producers_lock:
                # Check if the producer exists, create it if it doesn't
                if producer_name not in self._producers:
                    logging.debug(f"Creating new producer '{producer_name}' for audio playback")
                    self._producers[producer_name] = AudioProducer(producer_name)
                    
                producer = self._producers[producer_name]
                
                # Reactivate the producer if it's not active
                if not producer.active:
                    producer.active = True
                    
                # Clear existing audio from the producer if it exists
                producer.clear()
                
                # Set producer to loop if requested
                producer.loop = loop
                
                # If looping, set up the loop chunks
                if loop:
                    # Use chunk size from config
                    chunk_size = self.config.chunk
                    producer.set_loop_data(audio_data, chunk_size)
                    logging.debug(f"Set up looping audio with {len(audio_data) // chunk_size + 1} chunks")
                    return True
                    
                # Otherwise, split data into chunks and add to buffer
                chunk_size = self.config.chunk
                
                # Add chunks to producer (outside of lock to minimize lock time)
                has_chunks = False
                for i in range(0, len(audio_data), chunk_size):
                    end = min(i + chunk_size, len(audio_data))
                    chunk = audio_data[i:end]
                    
                    # Pad the last chunk if necessary
                    if len(chunk) < chunk_size:
                        chunk = np.pad(chunk, (0, chunk_size - len(chunk)), mode='constant')
                        
                    # Add the chunk to the producer's buffer
                    if not producer.put(chunk):
                        logging.warning(f"Producer buffer full for '{producer_name}', dropping chunk")
                        break
                    has_chunks = True
                    
                if not has_chunks:
                    logging.error(f"Failed to add any chunks to producer '{producer_name}'")
                    return False
                    
                logging.debug(f"Added {len(audio_data) // chunk_size + 1} audio chunks to producer '{producer_name}'")
                return True
                
        except Exception as e:
            logging.error(f"Error playing audio through producer '{producer_name}': {e}")
            return False
        
    def preload_sound_effects(self, sound_names=None):
        """
        Preload commonly used sound effects into the cache for faster playback.
        If sound_names is not provided, does not preload any effects (they will be
        loaded on-demand when first used, then cached).
        
        Args:
            sound_names: Optional list of sound effect names to preload
        """
        if sound_names is None:
            # Don't preload anything, just return
            logging.info("No sound effects specified for preloading. Will load on demand.")
            return
        
        # Load each sound effect in the background using the thread pool
        def _load_effect(name):
            try:
                filename = SoundEffect.get_filename(name)
                if not filename:
                    logging.error(f"Unknown sound effect for preloading: {name}")
                    return
                
                wav_path = os.path.join("assets", filename)
                if not os.path.exists(wav_path):
                    logging.error(f"Sound effect file not found for preloading: {wav_path}")
                    return
                
                # Check if already cached
                with self._sound_effect_cache_lock:
                    if name.lower() in self._sound_effect_cache:
                        logging.debug(f"Sound effect already cached: {name}")
                        return
                
                # Load the sound data
                audio_data = self._load_wav_file_data(wav_path)
                
                # Cache the sound effect
                with self._sound_effect_cache_lock:
                    self._sound_effect_cache[name.lower()] = audio_data
                    
                logging.info(f"Preloaded sound effect: {name}")
            except Exception as e:
                logging.error(f"Error preloading sound effect {name}: {e}")
        
        # Submit loading tasks to the thread pool
        for name in sound_names:
            self._audio_thread_pool.submit(_load_effect, name)
            
        logging.info(f"Submitted {len(sound_names)} sound effects for preloading")

    def stop_sound(self, effect_name: str):
        """
        Stop a specific sound effect and clean up resources
        
        Args:
            effect_name: Name of the sound effect to stop
        """
        # Check for debug environment variable to enable additional diagnostics
        debug_audio = os.environ.get("PHOENIX_AUDIO_DEBUG", "0").lower() in ("1", "true", "yes")
        
        effect_name_lower = effect_name.lower()
        producer_name = f"sound_effect_{effect_name_lower}"
        
        # First check if this producer exists
        producer_found = False
        with self._producers_lock:
            # Check if this specific sound effect producer exists
            if producer_name in self._producers:
                producer = self._producers[producer_name]
                producer.loop = False  # Ensure loop flag is cleared
                producer.clear()  # Clear any pending audio
                producer.active = False  # Mark as inactive
                producer_found = True
                
                # We don't delete the producer so it can be reused
                # Only set it to inactive so it's not processed in audio callbacks
                # This avoids the overhead of creating and destroying producers
                
                if debug_audio or logging.getLogger().isEnabledFor(logging.DEBUG):
                    logging.debug(f"Sound effect '{effect_name}' stopped using producer '{producer_name}'")
            
        # Also check if we have a record in the sound effect producers map
        if effect_name_lower in self._sound_effect_producers:
            mapped_producer = self._sound_effect_producers[effect_name_lower]
            
            # If this is a different producer than the one we already checked,
            # also stop it to be thorough (in case of mapping changes)
            if mapped_producer != producer_name:
                with self._producers_lock:
                    if mapped_producer in self._producers:
                        producer = self._producers[mapped_producer]
                        producer.loop = False
                        producer.clear()
                        producer.active = False
                        producer_found = True
                        
                        if debug_audio or logging.getLogger().isEnabledFor(logging.DEBUG):
                            logging.debug(f"Sound effect '{effect_name}' stopped using mapped producer '{mapped_producer}'")
            
            # Keep the mapping but don't remove it - we may need to 
            # reference it again if the sound is restarted
        
        if not producer_found:
            if debug_audio or logging.getLogger().isEnabledFor(logging.DEBUG):
                logging.debug(f"No active producer found for sound effect: {effect_name}")
        else:
            logging.info(f"Sound effect '{effect_name}' stopped")

    def _play_wav_file(self, wav_path: str, producer_name: str = "sound_effect", loop: bool = False) -> bool:
        """
        Play a mono WAV file.
        
        Args:
            wav_path: Path to the WAV file
            producer_name: Name of the producer to use
            loop: Whether to loop the audio
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not self._running:
            logging.error("Cannot play WAV file - AudioManager not running")
            return False
            
        try:
            logging.info(f"Opening WAV file: {wav_path}")
            with wave.open(wav_path, "rb") as wf:
                # Get WAV file properties
                channels = wf.getnchannels()
                width = wf.getsampwidth()
                rate = wf.getframerate()
                frames = wf.getnframes()
                
                logging.info(f"WAV file details: channels={channels}, bit depth={width*8}, sample rate={rate}, frames={frames}")
                
                # Read all audio data at once
                audio_data = wf.readframes(frames)
                
                # Convert to numpy array based on bit depth
                if width == 2:  # 16-bit audio
                    audio_array = np.frombuffer(audio_data, dtype=np.int16)
                elif width == 1:  # 8-bit audio
                    audio_array = np.frombuffer(audio_data, dtype=np.uint8).astype(np.int16) * 256
                elif width == 4:  # 32-bit audio
                    audio_array = np.frombuffer(audio_data, dtype=np.int32).astype(np.int16) // 65536
                else:
                    audio_array = np.frombuffer(audio_data, dtype=np.int16)
                
                # Ensure we have a valid array
                if audio_array.size == 0:
                    logging.error(f"WAV file produced empty audio data: {wav_path}")
                    return False
                    
                # Normalize the audio to ensure good volume
                max_amplitude = np.max(np.abs(audio_array))
                if max_amplitude > 0:
                    # Scale to use 80% of full int16 range to prevent distortion
                    scale_factor = (32767 * 0.8) / max_amplitude
                    audio_array = np.clip((audio_array * scale_factor), -32767, 32767).astype(np.int16)
                
                # Play the audio through the producer
                self.play_audio(audio_array, producer_name=producer_name, loop=loop)
                logging.info(f"Playing WAV file: {wav_path}, frames={frames}")
                return True
                
        except FileNotFoundError:
            logging.error(f"WAV file not found: {wav_path}")
        except Exception as e:
            logging.error(f"Failed to play WAV file {wav_path}: {str(e)}", exc_info=True)
        
        return False
                
    @contextmanager
    def get_recorder(self, filename: str):
        """Context manager for recording audio to a file"""
        wf = wave.open(filename, 'wb')
        wf.setnchannels(1)  # Always mono for recording
        wf.setsampwidth(2)  # 16-bit audio = 2 bytes
        wf.setframerate(AudioBaseConfig.SAMPLE_RATE)  # Always use 16kHz
        
        try:
            yield lambda data: wf.writeframes(data.tobytes())
        finally:
            wf.close()
            
    def get_input_devices(self) -> Dict[int, str]:
        """Get available input devices"""
        devices = {}
        try:
            device_list = sd.query_devices()
            for i, dev in enumerate(device_list):
                if dev['max_input_channels'] > 0:
                    devices[i] = dev['name']
        except Exception as e:
            logging.error(f"Error getting input devices: {e}")
        return devices
        
    def get_output_devices(self) -> Dict[int, str]:
        """Get available output devices"""
        devices = {}
        try:
            device_list = sd.query_devices()
            for i, dev in enumerate(device_list):
                if dev['max_output_channels'] > 0:
                    devices[i] = dev['name']
        except Exception as e:
            logging.error(f"Error getting output devices: {e}")
        return devices

    def stop_all_sound_effects(self):
        """Stop all currently playing sound effects"""
        # Check for debug environment variable to enable additional diagnostics
        debug_audio = os.environ.get("PHOENIX_AUDIO_DEBUG", "0").lower() in ("1", "true", "yes")
        
        # Find and stop all sound effect producers
        sound_effect_count = 0
        with self._producers_lock:
            # Find all sound effect producers (they start with "sound_effect_")
            sound_effect_producers = [name for name in self._producers.keys() 
                                     if name.startswith("sound_effect_")]
            
            # Stop each one
            for producer_name in sound_effect_producers:
                producer = self._producers[producer_name]
                if producer.active:
                    producer.loop = False
                    producer.clear()
                    producer.active = False
                    sound_effect_count += 1
                    
                    if debug_audio or logging.getLogger().isEnabledFor(logging.DEBUG):
                        logging.debug(f"Stopped sound effect producer: {producer_name}")
        
        # Log the result            
        if sound_effect_count > 0:
            logging.info(f"Stopped {sound_effect_count} sound effect(s)")
        elif debug_audio or logging.getLogger().isEnabledFor(logging.DEBUG):
            logging.debug("No active sound effects to stop")
            
        # Don't clear the tracking map - we keep the mappings for reuse

    def set_sound_effect_volume(self, effect_name: str, volume: float):
        """
        Set the volume for a specific sound effect
        
        Args:
            effect_name: Name of the sound effect
            volume: Volume level (0.0 to 1.0)
        """
        # Check for debug environment variable to enable additional diagnostics
        debug_audio = os.environ.get("PHOENIX_AUDIO_DEBUG", "0").lower() in ("1", "true", "yes")
        
        # Clamp volume to valid range
        volume = max(0.0, min(1.0, volume))
        
        effect_name_lower = effect_name.lower()
        producer_name = f"sound_effect_{effect_name_lower}"
        
        # Set volume for the producer if it exists
        volume_set = False
        with self._producers_lock:
            if producer_name in self._producers:
                self._producers[producer_name].volume = volume
                volume_set = True
                
                if debug_audio or logging.getLogger().isEnabledFor(logging.DEBUG):
                    logging.debug(f"Set volume for sound effect '{effect_name}' to {volume}")
            
            # Also check if we have a record in our tracking map that points to a different producer
            elif effect_name_lower in self._sound_effect_producers:
                mapped_producer = self._sound_effect_producers[effect_name_lower]
                if mapped_producer in self._producers:
                    self._producers[mapped_producer].volume = volume
                    volume_set = True
                    
                    if debug_audio or logging.getLogger().isEnabledFor(logging.DEBUG):
                        logging.debug(f"Set volume for sound effect '{effect_name}' to {volume} using mapped producer '{mapped_producer}'")
        
        if volume_set:
            logging.info(f"Set volume for sound effect '{effect_name}' to {volume}")
        else:
            if debug_audio or logging.getLogger().isEnabledFor(logging.DEBUG):
                logging.debug(f"Cannot set volume - sound effect '{effect_name}' not found") 