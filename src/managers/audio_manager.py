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
    """Audio producer that generates audio data with integrated buffer"""
    
    def __init__(self, name: str, max_buffer_size: int = 100):
        """
        Initialize a new audio producer with integrated buffer
        
        Args:
            name: Name of the producer
            max_buffer_size: Maximum number of chunks to buffer
        """
        self.name = name
        self._buffer = queue.Queue(maxsize=max_buffer_size)
        self.active = True
        self.loop = False
        self._volume = 1.0
        self._loop_chunks = []  # Pre-chunked data for looping
        
    def put(self, data: np.ndarray) -> bool:
        """
        Add audio data to the producer's buffer
        
        Args:
            data: Audio data to add
            
        Returns:
            bool: True if data was added, False if buffer is full
        """
        try:
            self._buffer.put_nowait(data)
            return True
        except queue.Full:
            return False
    
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
                    return data
                except queue.Empty:
                    pass
            return None
    
    def clear(self):
        """Clear all data from the buffer"""
        while not self._buffer.empty():
            try:
                self._buffer.get_nowait()
            except queue.Empty:
                break
    
    @property
    def volume(self) -> float:
        """Get the current volume"""
        return self._volume
    
    @volume.setter
    def volume(self, value: float):
        """Set the volume (0.0 to 1.0)"""
        self._volume = max(0.0, min(1.0, value))
        
    def set_loop_data(self, audio_data: np.ndarray, chunk_size: int):
        """
        Set data for looping, pre-chunked for efficiency
        
        Args:
            audio_data: Audio data to loop
            chunk_size: Size of chunks to split data into
        """
        if not audio_data.size:
            self._loop_chunks = []
            return
            
        # Pre-chunk the audio data for efficient looping
        self._loop_chunks = []
        for i in range(0, len(audio_data), chunk_size):
            end = min(i + chunk_size, len(audio_data))
            chunk = audio_data[i:end]
            
            # Pad the last chunk if necessary
            if len(chunk) < chunk_size:
                chunk = np.pad(chunk, (0, chunk_size - len(chunk)), mode='constant')
                
            self._loop_chunks.append(chunk)

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
            for name, producer in self._producers.items():
                if producer.active:
                    data = producer.get()  # Get data while holding lock
                    if data is not None and data.size > 0:
                        active_producers_data.append((name, data))
        
        # Process the data WITHOUT holding the lock
        has_audio = False
        
        # Mix audio from active producers outside the lock
        for name, data in active_producers_data:
            # Mix mono data into all output channels
            frames_to_mix = min(len(data), frames)
            
            # Make sure data is int16 to prevent unexpected behavior
            if data.dtype != np.int16:
                data = data.astype(np.int16)
            
            # Special handling for sound effect producer
            if name == "sound_effect" and frames_to_mix > 0:
                logging.debug(f"Mixing sound_effect: {frames_to_mix} frames")
            
            # Efficient duplication to all output channels
            for c in range(num_channels):
                outdata[:frames_to_mix, c] += data[:frames_to_mix]
            
            has_audio = True
        
        # Check if any audio was produced
        if has_audio and np.max(np.abs(outdata)) > 32700:
            # Only clip if necessary to prevent distortion
            np.clip(outdata, -32767, 32767, out=outdata)
    
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
                producer = self._producers[producer_name]
                
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
            if loop:
                producer.set_loop_data(audio_data, self.config.chunk)
                producer.loop = True
            else:
                producer.loop = False
            
            # Split audio data into chunks matching the configured chunk size
            chunk_size = self.config.chunk
            
            # Clear existing data first
            producer.clear()
            
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
        filename = SoundEffect.get_filename(effect_name)
        if not filename:
            logging.error(f"Unknown sound effect: {effect_name}")
            return False
        
        wav_path = os.path.join("assets", filename)
        
        # Check the cache first for this sound effect
        audio_data = None
        with self._sound_effect_cache_lock:
            if effect_name.lower() in self._sound_effect_cache:
                audio_data = self._sound_effect_cache[effect_name.lower()]
                if logging.getLogger().isEnabledFor(logging.DEBUG):
                    logging.debug(f"Using cached sound effect: {effect_name}")
        
        # If not in cache, load it and add to cache
        if audio_data is None:
            if not os.path.exists(wav_path):
                logging.error(f"Sound effect file not found: {wav_path}")
                return False
                
            # Load the sound data
            try:
                audio_data = self._load_wav_file_data(wav_path)
                
                # Cache the sound effect for future use
                with self._sound_effect_cache_lock:
                    self._sound_effect_cache[effect_name.lower()] = audio_data
                    
                if logging.getLogger().isEnabledFor(logging.DEBUG):
                    logging.debug(f"Cached sound effect: {effect_name}")
            except Exception as e:
                logging.error(f"Failed to load sound effect {effect_name}: {e}")
                return False
        
        # Remove existing sound_effect producer if it exists
        with self._producers_lock:
            if "sound_effect" in self._producers:
                old_producer = self._producers["sound_effect"]
                old_producer.active = False
                old_producer.clear()
                del self._producers["sound_effect"]
                logging.info("Removed existing sound_effect producer")
                
        # Create a new producer with maximum volume for sound effects
        producer = self.add_producer("sound_effect", buffer_size=1000, initial_volume=1.0)
        logging.info(f"Created new sound_effect producer with volume 1.0")
            
        # Play the sound data through the producer
        return self._play_audio_data(audio_data, producer_name="sound_effect", loop=loop)

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
        Play audio data through a producer.
        
        Args:
            audio_data: Audio data as numpy array
            producer_name: Name of the producer to use
            loop: Whether to loop the audio
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not self._running:
            logging.error("Cannot play audio data - AudioManager not running")
            return False
            
        try:
            # Play the audio through the producer
            self.play_audio(audio_data, producer_name=producer_name, loop=loop)
            logging.info(f"Playing audio data: {len(audio_data)} samples, loop={loop}")
            return True
                
        except Exception as e:
            logging.error(f"Failed to play audio data: {str(e)}", exc_info=True)
        
        return False
        
    def preload_sound_effects(self, sound_names=None):
        """
        Preload commonly used sound effects into the cache for faster playback.
        If sound_names is not provided, preloads all chirp sounds and other common effects.
        
        Args:
            sound_names: Optional list of sound effect names to preload
        """
        if sound_names is None:
            # Preload commonly used sound effects
            sound_names = [
                SoundEffect.CHIRP1, SoundEffect.CHIRP2, 
                SoundEffect.CHIRP3, SoundEffect.CHIRP4, 
                SoundEffect.CHIRP5, SoundEffect.CHIRP6,
                SoundEffect.CHIRP7, SoundEffect.CHIRP8,
                SoundEffect.YAWN, SoundEffect.YAWN2
            ]
        
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
        """Stop the currently playing sound effect and clean up resources"""
        with self._producers_lock:
            # TODO: Change to use effect_name instead of "sound_effect" so we have a producer for each sound effect
            if "sound_effect" in self._producers:
                producer = self._producers["sound_effect"]
                producer.loop = False  # Ensure loop flag is cleared
                producer.clear()  # Clear any pending audio
                producer.active = False  # Mark as inactive
                del self._producers["sound_effect"]  # Remove from active producers
                logging.info("Sound effect stopped and cleaned up")
        
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