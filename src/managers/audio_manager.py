import pyaudio
import wave
import numpy as np
import threading
import queue
import logging
import time
import os
from typing import Optional, Dict, Any, List, Callable, Tuple
from dataclasses import dataclass
from contextlib import contextmanager
from config import SoundEffect, AudioBaseConfig, AudioAmplifierConfig, get_filter_logger

@dataclass
class AudioConfig:
    """Audio configuration parameters"""
    format: int = pyaudio.paInt16  # Matches AudioBaseConfig.FORMAT='int16'
    channels: int = AudioBaseConfig.NUM_CHANNELS
    rate: int = AudioBaseConfig.SAMPLE_RATE
    chunk: int = AudioBaseConfig.CHUNK_SIZE
    input_device_index: Optional[int] = None
    output_device_index: Optional[int] = None

class AudioBaseConfig:
    """Base audio configuration that all audio components should use"""
    FORMAT = 'int16'  # numpy/pyaudio compatible format
    NUM_CHANNELS = 1
    SAMPLE_RATE = 16000
    CHUNK_SIZE = 640  # Optimized for WebRTC echo cancellation without stuttering
    BUFFER_SIZE = 5   # Minimal buffering to reduce latency
    DEFAULT_VOLUME = 1.0
    CONVERSATION_SFX_VOLUME = 0.5 # Volume for sound effects when a conversation is active
    # Calculate time-based values
    CHUNK_DURATION_MS = (CHUNK_SIZE / SAMPLE_RATE) * 1000  # Duration of each chunk in milliseconds
    LIKELY_LATENCY_MS = CHUNK_DURATION_MS * BUFFER_SIZE  # Calculate probable latency in milliseconds


class AudioBuffer:
    """Minimal thread-safe audio buffer with volume control"""
    def __init__(self, maxsize: int = AudioBaseConfig.BUFFER_SIZE):
        self.buffer = queue.Queue(maxsize=maxsize)
        self._lock = threading.Lock()
        self._volume = 1.0  # Default volume
        
    def put(self, data: np.ndarray):
        """Put raw audio data into buffer, blocking if full"""
        self.buffer.put(data)
            
    def get(self) -> Optional[np.ndarray]:
        """Get volume-adjusted audio data from buffer"""
        try:
            data = self.buffer.get_nowait()
            if data is not None and self._volume != 1.0:
                # Convert to float32 for volume adjustment
                audio_float = data.astype(np.float32) * self._volume
                # Clip to int16 range and convert back
                data = np.clip(audio_float, -32768, 32767).astype(np.int16)
            return data
        except queue.Empty:
            return None
            
    def clear(self):
        """Clear the buffer"""
        with self._lock:
            while not self.buffer.empty():
                try:
                    self.buffer.get_nowait()
                except queue.Empty:
                    break
                    
    def set_volume(self, volume: float):
        """Set the volume to apply during get"""
        with self._lock:
            self._volume = max(0.0, min(1.0, volume))

class AudioConsumer:
    """Represents a consumer of audio input data"""
    def __init__(self, callback: Callable[[np.ndarray], None], chunk_size: Optional[int] = None):
        self.callback = callback
        self.buffer = AudioBuffer()
        self.active = True
        self.chunk_size = chunk_size

class AudioProducer:
    """Represents a producer of audio output data"""
    def __init__(self, name: str, chunk_size: Optional[int] = None, buffer_size: int = 100, is_stream: bool = False):
        self.name = name
        self.buffer = AudioBuffer(maxsize=buffer_size)
        self._volume = AudioBaseConfig.DEFAULT_VOLUME
        self.active = True
        self.logger = get_filter_logger(__name__)
        self.chunk_size = chunk_size
        self._remainder = np.array([], dtype=np.int16)
        self.loop = False  # Whether to loop the audio
        self._original_audio = None  # Store original audio data for looping
        self.on_finish: Optional[Callable[[str], None]] = None
        self.loading = False
        self.is_stream = is_stream

    @property
    def volume(self) -> float:
        return self._volume

    @volume.setter
    def volume(self, value: float):
        self._volume = max(0.0, min(1.0, value))
        self.buffer.set_volume(self._volume)

    def resize_chunk(self, audio_data: np.ndarray) -> List[np.ndarray]:
        """Resize audio chunk to desired size, handling remainder samples"""
        if self.chunk_size is None:
            return [audio_data]
            
        if len(self._remainder) > 0:
            audio_data = np.concatenate([self._remainder, audio_data])
            
        chunks = []
        num_complete_chunks = len(audio_data) // self.chunk_size
        for i in range(num_complete_chunks):
            start = i * self.chunk_size
            end = start + self.chunk_size
            chunks.append(audio_data[start:end])
            
        remainder_start = num_complete_chunks * self.chunk_size
        self._remainder = audio_data[remainder_start:]
        
        return chunks

    def clear(self):
        """Clear the buffer and reset the remainder."""
        self.buffer.clear()
        self._remainder = np.array([], dtype=np.int16)
        self.logger.info(f"Producer '{self.name}' buffer cleared")

    def stop(self):
        """Stop this producer and clean up its resources"""
        self.active = False
        self.clear()
        self._original_audio = None  # Clear original audio data
        self.loop = False  # Reset loop flag
        self.logger.info(f"Producer '{self.name}' stopped and cleaned up")

class AudioManager:
    """Manages audio resources and provides thread-safe access"""
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
        if AudioManager._instance is not None:
            raise RuntimeError("Use AudioManager.get_instance() to get the AudioManager instance")
            
        self.config = config
        self._py_audio: Optional[pyaudio.PyAudio] = None
        self._input_stream: Optional[pyaudio.Stream] = None
        self._output_stream: Optional[pyaudio.Stream] = None
        self._lock = threading.Lock()
        self._running = False
        self.logger = get_filter_logger(__name__)
        self._input_thread: Optional[threading.Thread] = None
        self._output_thread: Optional[threading.Thread] = None
        
        # Audio consumers and producers
        self._consumers: List[AudioConsumer] = []
        self._producers: Dict[str, AudioProducer] = {}
        self._consumers_lock = threading.Lock()
        self._producers_lock = threading.Lock()
        
        # Reusable chunk resizer
        self._chunk_resizer: Optional[AudioProducer] = None
        self._chunk_resizer_lock = threading.Lock()

        # Queue for requeuing audio data
        self._requeue_queue = queue.Queue()
        self._requeue_thread = None
        self._requeue_stop = threading.Event()
        self.master_volume: float = AudioBaseConfig.DEFAULT_VOLUME # Initialize directly from AudioBaseConfig
        self.amplifier = None
        self._amp_enabled = False
        self._last_audio_activity_time = 0
        
    def set_amplifier(self, amplifier):
        """Sets the amplifier instance for power management."""
        self.amplifier = amplifier
        # Ensure amp is off initially if we are just setting it
        if self.amplifier and self._amp_enabled:
            self.amplifier.disable()
            self._amp_enabled = False

    def add_consumer(self, callback: Callable[[np.ndarray], None], chunk_size: Optional[int] = None) -> AudioConsumer:
        """Add a new audio consumer"""
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
                
    def _create_producer(self, name: str, chunk_size: Optional[int] = None, buffer_size: int = 100, initial_volume: Optional[float] = 1.0, is_stream: bool = False) -> AudioProducer:
        """Create a new producer instance without adding it to the producers dictionary"""
        print(f"DEBUG: Creating producer '{name}' with chunk_size={chunk_size}, buffer_size={buffer_size}, initial_volume={initial_volume}", flush=True)
        self.logger.info(f"Creating new producer: {name} with chunk_size={chunk_size}, buffer_size={buffer_size}, initial_volume={initial_volume}, is_stream={is_stream}")
        
        producer = AudioProducer(name, chunk_size=chunk_size, buffer_size=buffer_size, is_stream=is_stream)
        producer.active = True
        if initial_volume is not None:
            producer.volume = initial_volume
        return producer
        
    def add_producer(self, name: str, chunk_size: Optional[int] = None, buffer_size: int = 100, initial_volume: Optional[float] = None, is_stream: bool = False) -> AudioProducer:
        """Add a new audio producer"""
        producer = self._create_producer(name, chunk_size, buffer_size, initial_volume, is_stream)
        
        with self._producers_lock:
            self._producers[name] = producer
            self.logger.info(f"Producer '{name}' added and activated")
            
        return producer
        
    def remove_producer(self, name: str):
        """Remove an audio producer"""
        with self._producers_lock:
            if name in self._producers:
                producer = self._producers[name]
                producer.stop() # Call stop() for full cleanup
                del self._producers[name]
                self.logger.info(f"Producer '{name}' fully stopped and removed")
            else:
                logging.warning(f"Attempted to remove non-existent producer: {name}")
                
    def set_producer_volume(self, name: str, volume: float):
        """Set volume for a specific producer"""
        with self._producers_lock:
            if name in self._producers:
                self._producers[name].volume = max(0.0, min(1.0, volume))
                
    @property
    def is_running(self) -> bool:
        return self._running
        
    def start(self):
        """Start audio processing"""
        with self._lock:
            if self._running:
                self.logger.info("AudioManager already running")
                return
                
            try:
                self.logger.info("Initializing PyAudio...")
                self._py_audio = pyaudio.PyAudio()
                
                self.logger.info("Setting up audio streams...")
                self._setup_streams()
                self._running = True
                
                # Start input and output threads
                self.logger.info("Starting audio threads...")
                self._input_thread = threading.Thread(target=self._input_loop, name="AudioInputThread")
                self._output_thread = threading.Thread(target=self._output_loop, name="AudioOutputThread")
                self._requeue_thread = threading.Thread(target=self._requeue_loop, name="AudioRequeueThread")
                self._input_thread.daemon = True
                self._output_thread.daemon = True
                self._requeue_thread.daemon = True
                self._input_thread.start()
                self._output_thread.start()
                self._requeue_thread.start()
                self.logger.info("AudioManager started successfully")
                
            except Exception as e:
                logging.error(f"Failed to start audio: {e}", exc_info=True)
                raise
                
    def stop(self):
        """Stop audio processing and cleanup resources"""
        with self._lock:
            self._running = False
            self._requeue_stop.set()
            
            # Stop all consumers and producers
            with self._consumers_lock:
                for consumer in self._consumers:
                    consumer.active = False
            with self._producers_lock:
                for producer in self._producers.values():
                    producer.active = False
            
            # Wait for threads to finish
            if self._input_thread and self._input_thread.is_alive():
                self._input_thread.join(timeout=1.0)
            if self._output_thread and self._output_thread.is_alive():
                self._output_thread.join(timeout=1.0)
            if self._requeue_thread and self._requeue_thread.is_alive():
                self._requeue_thread.join(timeout=1.0)
                
            self._cleanup_streams()
            
            if self._py_audio:
                self._py_audio.terminate()
                self._py_audio = None
                
    def _setup_streams(self):
        """Setup audio streams"""
        if not self._py_audio:
            logging.error("PyAudio not initialized")
            return
            
        try:
            # Log available devices
            input_devices = self.get_input_devices()
            output_devices = self.get_output_devices()
            self.logger.info(f"Available input devices: {input_devices}")
            self.logger.info(f"Available output devices: {output_devices}")
            
            # Find and set the ReSpeaker device index automatically if not already set
            if self.config.input_device_index is None:
                respeaker_input_found = False
                for i, name in input_devices.items():
                    if "ReSpeaker" in name:
                        self.config.input_device_index = i
                        self.logger.info(f"Automatically selected ReSpeaker input device at index {i}: '{name}'")
                        respeaker_input_found = True
                        break
                if not respeaker_input_found:
                    self.logger.info("No ReSpeaker input device found. Using system default.")

            if self.config.output_device_index is None:
                respeaker_output_found = False
                for i, name in output_devices.items():
                    if "ReSpeaker" in name:
                        self.config.output_device_index = i
                        self.logger.info(f"Automatically selected ReSpeaker output device at index {i}: '{name}'")
                        respeaker_output_found = True
                        break
                if not respeaker_output_found:
                    self.logger.info("No ReSpeaker output device found. Using system default.")

            # Setup input stream
            self.logger.info(f"Opening input stream (Device Index: {self.config.input_device_index})...")
            self._input_stream = self._py_audio.open(
                format=self.config.format,
                channels=self.config.channels,
                rate=self.config.rate,
                input=True,
                input_device_index=self.config.input_device_index,
                frames_per_buffer=self.config.chunk
            )
            
            # Setup output stream
            self.logger.info(f"Opening output stream (Device Index: {self.config.output_device_index})...")
            self._output_stream = self._py_audio.open(
                format=self.config.format,
                channels=self.config.channels,
                rate=self.config.rate,
                output=True,
                output_device_index=self.config.output_device_index,
                frames_per_buffer=self.config.chunk
            )
            self.logger.info("Audio streams setup successfully")
            
        except Exception as e:
            logging.error(f"Error setting up audio streams: {e}", exc_info=True)
            raise
            
    def _cleanup_streams(self):
        """Cleanup audio streams"""
        if self._input_stream:
            try:
                self._input_stream.stop_stream()
                self._input_stream.close()
            except Exception as e:
                logging.error(f"Error closing input stream: {e}")
            self._input_stream = None
            
        if self._output_stream:
            try:
                self._output_stream.stop_stream()
                self._output_stream.close()
            except Exception as e:
                logging.error(f"Error closing output stream: {e}")
            self._output_stream = None
            
    def _get_chunk_resizer(self, chunk_size: int) -> AudioProducer:
        """Get or create a reusable chunk resizer with the specified chunk size"""
        with self._chunk_resizer_lock:
            if self._chunk_resizer is None or self._chunk_resizer.chunk_size != chunk_size:
                if self._chunk_resizer is not None:
                    # Clear any existing data
                    self._chunk_resizer.buffer.clear()
                self._chunk_resizer = AudioProducer("chunk_resizer", chunk_size=chunk_size)
            return self._chunk_resizer

    def _input_loop(self):
        """Main input processing loop"""
        self.logger.info("Input processing loop started")
        while self._running:
            try:
                # Read from input stream
                data = self._input_stream.read(self.config.chunk, exception_on_overflow=False)
                audio_data = np.frombuffer(data, dtype=np.int16)
                
                # Distribute to all active consumers
                with self._consumers_lock:
                    for consumer in self._consumers:
                        if consumer.active:
                            if consumer.chunk_size and consumer.chunk_size != len(audio_data):
                                chunk_resizer = self._get_chunk_resizer(consumer.chunk_size)
                                resized_chunks = chunk_resizer.resize_chunk(audio_data)
                                for chunk in resized_chunks:
                                    consumer.callback(chunk)
                            else:
                                consumer.callback(audio_data)
                            
            except Exception as e:
                if self._running:  # Only log if we haven't stopped intentionally
                    logging.error(f"Error in audio input loop: {e}", exc_info=True)
        self.logger.info("Input processing loop stopped")
                
    def _output_loop(self):
        """Main output processing loop"""
        self.logger.info("Output processing loop started")
        last_producer_log = 0  # Track when we last logged producer states
        no_data_count = 0  # Track consecutive no-data iterations
        
        while self._running:
            try:
                # Mix audio from all active producers
                mixed_audio = np.zeros(self.config.chunk, dtype=np.float32)
                active_producers = 0
                finished_producer_callbacks: List[Tuple[Callable[[str], None], str]] = []

                with self._producers_lock:
                    producers_to_remove = []
                    for name, producer in list(self._producers.items()):
                        state = {
                            'name': name,
                            'active': producer.active,
                            'buffer_empty': producer.buffer.buffer.empty(),
                            'chunk_size': producer.chunk_size,
                            'buffer_size': producer.buffer.buffer.qsize()
                        }
                        
                        if producer.active:
                            data = producer.buffer.get()  # Volume already applied here
                            if data is not None:
                                no_data_count = 0  # Reset no-data counter
                                if len(data) == self.config.chunk:
                                    # Pre-scale to prevent clipping when mixing
                                    mixed_audio += data.astype(np.float32) * 0.8
                                    active_producers += 1
                                    state['had_data'] = True
                                    logging.debug(f"Mixed data from producer '{name}'")
                                else:
                                    logging.warning(f"Skipped chunk from '{name}': expected {self.config.chunk} samples, got {len(data)}")
                            else:
                                if producer.buffer.buffer.empty():
                                    # If looping is enabled and we have original audio data, queue it for requeuing
                                    if producer.loop and producer._original_audio is not None and producer.active:
                                        logging.debug(f"Queueing audio data for requeuing producer '{name}' with loop={producer.loop}")
                                        self._requeue_queue.put((name, producer._original_audio, producer.loop))
                                    elif not producer.loop and not producer.loading and not producer.is_stream:
                                        # Sound finished, mark for callback and removal
                                        if producer.on_finish:
                                            finished_producer_callbacks.append((producer.on_finish, name))
                                        producers_to_remove.append(name)
                        else:
                            # Producer is inactive, mark for removal once its buffer is empty
                            if producer.buffer.buffer.empty():
                                producers_to_remove.append(name)
                    
                    # Clean up producers that have finished
                    for name in producers_to_remove:
                        if name in self._producers:
                            self._producers[name].stop()
                            del self._producers[name]
                            self.logger.info(f"Producer '{name}' finished/inactive and was removed.")

                # Apply master volume before final clipping and conversion
                mixed_audio *= self.master_volume

                # Convert back to int16 and clip to prevent overflow
                mixed_audio = np.clip(mixed_audio, -32768, 32767).astype(np.int16)
                        
                if active_producers > 0:
                    self._last_audio_activity_time = time.time()
                    if self.amplifier and not self._amp_enabled:
                        self.amplifier.enable()
                        self._amp_enabled = True
                elif self.amplifier and self._amp_enabled:
                    if time.time() - self._last_audio_activity_time > AudioAmplifierConfig.DISABLE_DELAY:
                        self.amplifier.disable()
                        self._amp_enabled = False

                # Write to output stream
                if active_producers > 0 or np.any(mixed_audio):
                    logging.debug(f"Writing {len(mixed_audio)} samples to output stream with master_volume {self.master_volume:.2f}")
                    self._output_stream.write(mixed_audio.tobytes())
                else:
                    # Small sleep to prevent spinning too fast when no data
                    time.sleep(0.001)  # 1ms sleep
                
                # Call callbacks after releasing the lock to avoid deadlocks
                for callback, name in finished_producer_callbacks:
                    try:
                        callback(name)
                    except Exception as e:
                        self.logger.error(f"Error in on_finish callback for producer '{name}': {e}", exc_info=True)

            except Exception as e:
                if self._running:  # Only log if we haven't stopped intentionally
                    logging.error(f"Error in output loop: {e}", exc_info=True)
                    
        self.logger.info("Output processing loop stopped")
                
    def play_audio(self, audio_data: np.ndarray, producer_name: str = "default", loop: bool = False):
        """Play audio data through a specific producer
        Args:
            audio_data: Audio data to play as numpy array
            producer_name: Name of the producer to use
            loop: Whether to loop the audio (default: False)
        """
        print(f"DEBUG: Entering play_audio with {len(audio_data)} samples", flush=True)
        self.logger.info(f"play_audio called for producer '{producer_name}' with {len(audio_data)} samples, loop={loop}")
        
        try:
            if not self._running:
                logging.warning("play_audio called but AudioManager is not running")
                return
                
            # Create producer if needed
            with self._producers_lock:
                if producer_name not in self._producers:
                    self.logger.info(f"Creating new producer '{producer_name}'")
                    producer = self._create_producer(producer_name, chunk_size=self.config.chunk, buffer_size=1000)
                    self._producers[producer_name] = producer
                producer = self._producers[producer_name]
                
                if not producer.active:
                    logging.warning(f"Producer '{producer_name}' is not active")
                    return
                    
                # Set loop flag and store original audio if looping
                producer.loop = loop
                if loop:
                    producer._original_audio = audio_data.copy()
                else:
                    producer._original_audio = None  # Clear any previous audio data if not looping
                    
            # Ensure audio data is int16
            if audio_data.dtype != np.int16:
                self.logger.info(f"Converting audio data from {audio_data.dtype} to int16")
                audio_data = np.clip(audio_data * 32767, -32768, 32767).astype(np.int16)
            
            # Split audio data into chunks matching the configured chunk size
            num_samples = len(audio_data)
            chunk_size = self.config.chunk  # Always use config.chunk since output loop expects this
            num_chunks = (num_samples + chunk_size - 1) // chunk_size  # Round up division
            
            chunks_added = 0
            for i in range(num_chunks):
                start = i * chunk_size
                end = min(start + chunk_size, num_samples)
                chunk = audio_data[start:end]
                # Pad the last chunk with zeros if needed
                if len(chunk) < chunk_size:
                    chunk = np.pad(chunk, (0, chunk_size - len(chunk)), mode='constant')
                
                producer.buffer.put(chunk)
                chunks_added += 1
            
            # All data has been queued, mark loading as complete
            producer.loading = False
                    
        except Exception as e:
            logging.error(f"Error in play_audio: {str(e)}", exc_info=True)
                
    def play_sound(self, effect_name: str, loop: bool = False, on_finish: Optional[Callable[[str], None]] = None) -> bool:
        """
        Play a sound effect by name.
        Args:
            effect_name: Name of the sound effect (case-insensitive)
            loop: Whether to loop the sound effect (default: False)
            on_finish: Callback to execute when the sound finishes
        Returns:
            bool: True if the sound effect was found and playback started, False otherwise
        """
        wav_path = SoundEffect.get_file_path(effect_name)
        if not wav_path:
            logging.error(f"Unknown sound effect: {effect_name}")
            return False
            
        if not os.path.exists(wav_path):
            logging.error(f"Sound effect file not found: {wav_path}")
            return False
            
        return self._play_wav_file(wav_path, producer_name=effect_name, loop=loop, on_finish=on_finish)

    def stop_sound(self, effect_name: str):
        """Stop the currently playing sound effect and clean up resources"""
        with self._producers_lock:
            self.logger.debug(f"Attempting to stop sound for effect: {effect_name}")
            if effect_name in self._producers:
                producer = self._producers[effect_name]
                self.logger.debug(f"Found producer '{effect_name}'. State before stop: active={producer.active}, loop={producer.loop}")
                producer.stop()  # This marks the producer as inactive and clears its loop flag.
                self.logger.info(f"Sound effect '{effect_name}' stopped. State after stop: active={producer.active}, loop={producer.loop}")
            else:
                self.logger.warning(f"Could not stop sound. Producer '{effect_name}' not found. Active producers: {list(self._producers.keys())}")
        
    def _play_wav_file(self, wav_path: str, producer_name: str, loop: bool = False, on_finish: Optional[Callable[[str], None]] = None) -> bool:
        """Play a WAV file through the audio system"""
        if not self._running:
            logging.error("Cannot play WAV file - AudioManager not running")
            return False

        # Clear any existing sound effect first
        with self._producers_lock:
            if producer_name in self._producers:
                self._producers[producer_name].buffer.clear()

        def _play_in_thread():
            try:
                self.logger.info(f"Opening WAV file: {wav_path}")
                with wave.open(wav_path, "rb") as wf:
                    # Log WAV file properties
                    channels = wf.getnchannels()
                    width = wf.getsampwidth()
                    rate = wf.getframerate()
                    frames = wf.getnframes()
                    
                    # Verify WAV format matches our configuration
                    if channels != self.config.channels:
                        logging.error(f"WAV channels ({channels}) doesn't match config ({self.config.channels})")
                        return False
                    if rate != self.config.rate:
                        logging.error(f"WAV rate ({rate}) doesn't match config ({self.config.rate})")
                        return False
                    if width != self._py_audio.get_sample_size(self.config.format):
                        logging.error(f"WAV width ({width}) doesn't match config format")
                        return False
                                        
                    # Create or get producer and set volume
                    with self._producers_lock:
                        if producer_name not in self._producers:
                            # Get current volume if producer exists
                            current_volume = None
                            if producer_name in self._producers:
                                current_volume = self._producers[producer_name].volume
                            producer = self._create_producer(producer_name, chunk_size=self.config.chunk, buffer_size=1000, initial_volume=current_volume)
                            self._producers[producer_name] = producer
                        producer = self._producers[producer_name]
                        producer.on_finish = on_finish
                        producer.loading = True
                    
                    audio_data = wf.readframes(frames)
                    audio_array = np.frombuffer(audio_data, dtype=np.int16)
                    self.play_audio(audio_array, producer_name=producer_name, loop=loop)
                    
            except FileNotFoundError:
                logging.error(f"WAV file not found: {wav_path}")
                return False
            except Exception as e:
                logging.error(f"Failed to play WAV file {wav_path}: {str(e)}", exc_info=True)
                return False
                
            return True

        # Start playback in a separate thread
        thread = threading.Thread(target=_play_in_thread, name=f"wav_player_{producer_name}")
        thread.daemon = True
        thread.start()
        return True
                
    @contextmanager
    def get_recorder(self, filename: str):
        """Context manager for recording audio to a file"""
        wf = wave.open(filename, 'wb')
        wf.setnchannels(self.config.channels)
        wf.setsampwidth(self._py_audio.get_sample_size(self.config.format))
        wf.setframerate(self.config.rate)
        
        try:
            yield lambda data: wf.writeframes(data.tobytes())
        finally:
            wf.close()
            
    def get_input_devices(self) -> Dict[int, str]:
        """Get available input devices"""
        devices = {}
        if self._py_audio:
            for i in range(self._py_audio.get_device_count()):
                device_info = self._py_audio.get_device_info_by_index(i)
                if device_info['maxInputChannels'] > 0:
                    devices[i] = device_info['name']
        return devices
        
    def get_output_devices(self) -> Dict[int, str]:
        """Get available output devices"""
        devices = {}
        if self._py_audio:
            for i in range(self._py_audio.get_device_count()):
                device_info = self._py_audio.get_device_info_by_index(i)
                if device_info['maxOutputChannels'] > 0:
                    devices[i] = device_info['name']
        return devices

    def _requeue_loop(self):
        """Background thread for handling audio requeuing"""
        while not self._requeue_stop.is_set():
            try:
                # Get the next requeue request with a timeout
                try:
                    producer_name, audio_data, _ = self._requeue_queue.get(timeout=0.1)
                except queue.Empty:
                    continue

                # Before re-playing, check if the producer still exists and is supposed to be looping.
                with self._producers_lock:
                    if producer_name not in self._producers:
                        self.logger.debug(f"Ignoring requeue for '{producer_name}': producer removed.")
                        continue
                    
                    producer = self._producers[producer_name]
                    # Log current state before checking
                    self.logger.debug(f"Requeue check for '{producer_name}': active={producer.active}, loop={producer.loop}")
                    if not producer.loop or not producer.active:
                        self.logger.debug(f"Ignoring requeue for '{producer_name}': looping disabled.")
                        continue
                
                # If we're here, the producer should be refilled directly, not by calling play_audio.
                # This prevents resetting the loop flag.
                num_samples = len(audio_data)
                chunk_size = self.config.chunk
                num_chunks = (num_samples + chunk_size - 1) // chunk_size

                for i in range(num_chunks):
                    start = i * chunk_size
                    end = min(start + chunk_size, num_samples)
                    chunk = audio_data[start:end]
                    # Pad the last chunk with zeros if needed
                    if len(chunk) < chunk_size:
                        chunk = np.pad(chunk, (0, chunk_size - len(chunk)), mode='constant')
                    
                    producer.buffer.put(chunk)
                
                self.logger.debug(f"Requeued audio for looping producer '{producer_name}'")
                self._requeue_queue.task_done()
                
            except Exception as e:
                logging.error(f"Error in requeue loop: {e}", exc_info=True)
                time.sleep(0.1)  # Prevent tight loop on error

    def set_master_volume(self, volume: float):
        """Set the master volume for all audio output, clamping between 0.0 and 1.0."""
        self.master_volume = max(0.0, min(1.0, volume))
        self.logger.info(f"Master volume set to {self.master_volume}")

    def get_sound_duration(self, effect_name: str) -> Optional[float]:
        """
        Get the duration of a sound effect in seconds.
        Args:
            effect_name: Name of the sound effect (case-insensitive)
        Returns:
            float: Duration in seconds, or None if not found
        """
        wav_path = SoundEffect.get_file_path(effect_name)
        if not wav_path or not os.path.exists(wav_path):
            logging.error(f"Sound effect not found for duration check: {effect_name}")
            return None
        try:
            with wave.open(wav_path, "rb") as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                duration = frames / float(rate)
                return duration
        except Exception as e:
            logging.error(f"Could not read duration from WAV file {wav_path}: {e}")
            return None
