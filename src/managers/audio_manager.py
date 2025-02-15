import pyaudio
import wave
import numpy as np
import threading
import queue
import logging
import time
import os
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass
from contextlib import contextmanager
from config import SoundEffect, AUDIO_DEFAULT_VOLUME, AudioBaseConfig

@dataclass
class AudioConfig:
    """Audio configuration parameters"""
    format: int = pyaudio.paInt16  # Matches AudioBaseConfig.FORMAT='int16'
    channels: int = AudioBaseConfig.NUM_CHANNELS
    rate: int = AudioBaseConfig.SAMPLE_RATE
    chunk: int = AudioBaseConfig.CHUNK_SIZE
    input_device_index: Optional[int] = None
    output_device_index: Optional[int] = None
    default_volume: float = AUDIO_DEFAULT_VOLUME


class AudioBuffer:
    """Minimal thread-safe audio buffer with volume control"""
    def __init__(self, maxsize: int = AudioBaseConfig.BUFFER_SIZE):
        self.buffer = queue.Queue(maxsize=maxsize)
        self._lock = threading.Lock()
        self._volume = 1.0  # Default volume
        
    def put(self, data: np.ndarray) -> bool:
        """Put raw audio data into buffer, dropping if full"""
        try:
            self.buffer.put_nowait(data)
            return True
        except queue.Full:
            return False
            
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
    def __init__(self, name: str, chunk_size: Optional[int] = None, buffer_size: int = 100):
        self.name = name
        self.buffer = AudioBuffer(maxsize=buffer_size)
        self._volume = AUDIO_DEFAULT_VOLUME
        self.active = True
        self.chunk_size = chunk_size
        self._remainder = np.array([], dtype=np.int16)
        self.loop = False  # Whether to loop the audio
        self._original_audio = None  # Store original audio data for looping

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

    def stop(self):
        """Stop this producer and clean up its resources"""
        self.active = False
        self.buffer.clear()
        self._remainder = np.array([], dtype=np.int16)
        self._original_audio = None  # Clear original audio data
        self.loop = False  # Reset loop flag
        logging.info(f"Producer '{self.name}' stopped and cleaned up")

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
                
    def _create_producer(self, name: str, chunk_size: Optional[int] = None, buffer_size: int = 100, initial_volume: Optional[float] = None) -> AudioProducer:
        """Create a new producer instance without adding it to the producers dictionary"""
        print(f"DEBUG: Creating producer '{name}' with chunk_size={chunk_size}, buffer_size={buffer_size}", flush=True)
        logging.info(f"Creating new producer: {name} with chunk_size={chunk_size}, buffer_size={buffer_size}")
        
        producer = AudioProducer(name, chunk_size=chunk_size, buffer_size=buffer_size)
        producer.active = True
        if initial_volume is not None:
            producer.volume = initial_volume
        return producer
        
    def add_producer(self, name: str, chunk_size: Optional[int] = None, buffer_size: int = 100, initial_volume: Optional[float] = None) -> AudioProducer:
        """Add a new audio producer"""
        producer = self._create_producer(name, chunk_size, buffer_size, initial_volume)
        
        with self._producers_lock:
            self._producers[name] = producer
            logging.info(f"Producer '{name}' added and activated")
            
        return producer
        
    def remove_producer(self, name: str):
        """Remove an audio producer"""
        with self._producers_lock:
            if name in self._producers:
                self._producers[name].active = False
                del self._producers[name]
                
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
                logging.info("AudioManager already running")
                return
                
            try:
                logging.info("Initializing PyAudio...")
                self._py_audio = pyaudio.PyAudio()
                
                logging.info("Setting up audio streams...")
                self._setup_streams()
                self._running = True
                
                # Start input and output threads
                logging.info("Starting audio threads...")
                self._input_thread = threading.Thread(target=self._input_loop, name="AudioInputThread")
                self._output_thread = threading.Thread(target=self._output_loop, name="AudioOutputThread")
                self._requeue_thread = threading.Thread(target=self._requeue_loop, name="AudioRequeueThread")
                self._input_thread.daemon = True
                self._output_thread.daemon = True
                self._requeue_thread.daemon = True
                self._input_thread.start()
                self._output_thread.start()
                self._requeue_thread.start()
                logging.info("AudioManager started successfully")
                
            except Exception as e:
                logging.error(f"Failed to start audio: {e}", exc_info=True)
                self.stop()
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
            logging.info(f"Available input devices: {input_devices}")
            logging.info(f"Available output devices: {output_devices}")
            
            # Setup input stream
            logging.info("Opening input stream...")
            self._input_stream = self._py_audio.open(
                format=self.config.format,
                channels=self.config.channels,
                rate=self.config.rate,
                input=True,
                input_device_index=self.config.input_device_index,
                frames_per_buffer=self.config.chunk
            )
            
            # Setup output stream
            logging.info("Opening output stream...")
            self._output_stream = self._py_audio.open(
                format=self.config.format,
                channels=self.config.channels,
                rate=self.config.rate,
                output=True,
                output_device_index=self.config.output_device_index,
                frames_per_buffer=self.config.chunk
            )
            logging.info("Audio streams setup successfully")
            
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
        logging.info("Input processing loop started")
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
        logging.info("Input processing loop stopped")
                
    def _output_loop(self):
        """Main output processing loop"""
        logging.info("Output processing loop started")
        last_producer_log = 0  # Track when we last logged producer states
        no_data_count = 0  # Track consecutive no-data iterations
        
        while self._running:
            try:
                # Mix audio from all active producers
                mixed_audio = np.zeros(self.config.chunk, dtype=np.float32)
                active_producers = 0
                
                with self._producers_lock:
                    producer_states = []  # For logging
                    for name, producer in self._producers.items():
                        state = {
                            'name': name,
                            'active': producer.active,
                            'buffer_empty': producer.buffer.buffer.empty(),
                            'chunk_size': producer.chunk_size,
                            'buffer_size': producer.buffer.buffer.qsize()
                        }
                        producer_states.append(state)
                        
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
                                    else:
                                        no_data_count += 1
                                        if no_data_count % 100 == 0:  # Log every 100th no-data iteration
                                            logging.debug(f"No data available from producer '{name}' for {no_data_count} iterations")
                    
                    # Convert back to int16 and clip to prevent overflow
                    mixed_audio = np.clip(mixed_audio, -32768, 32767).astype(np.int16)
                        
                # Write to output stream
                if active_producers > 0:
                    logging.debug(f"Writing {len(mixed_audio)} samples to output stream")
                    self._output_stream.write(mixed_audio.tobytes())
                else:
                    # Small sleep to prevent spinning too fast when no data
                    time.sleep(0.001)  # 1ms sleep
                    
            except Exception as e:
                if self._running:  # Only log if we haven't stopped intentionally
                    logging.error(f"Error in output loop: {e}", exc_info=True)
                    
        logging.info("Output processing loop stopped")
                
    def play_audio(self, audio_data: np.ndarray, producer_name: str = "default", loop: bool = False):
        """Play audio data through a specific producer
        Args:
            audio_data: Audio data to play as numpy array
            producer_name: Name of the producer to use
            loop: Whether to loop the audio (default: False)
        """
        print(f"DEBUG: Entering play_audio with {len(audio_data)} samples", flush=True)
        logging.info(f"play_audio called for producer '{producer_name}' with {len(audio_data)} samples, loop={loop}")
        
        try:
            if not self._running:
                logging.warning("play_audio called but AudioManager is not running")
                return
                
            # Create producer if needed
            with self._producers_lock:
                if producer_name not in self._producers:
                    logging.info(f"Creating new producer '{producer_name}'")
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
                logging.info(f"Converting audio data from {audio_data.dtype} to int16")
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
                
                success = producer.buffer.put(chunk)
                if success:
                    chunks_added += 1
                else:
                    logging.warning(f"Buffer full for producer '{producer_name}', chunk {i+1}/{num_chunks} dropped")
                    break  # Stop if buffer is full
                    
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
        if not os.path.exists(wav_path):
            logging.error(f"Sound effect file not found: {wav_path}")
            return False
            
        return self._play_wav_file(wav_path, producer_name="sound_effect", loop=loop)

    def stop_sound(self):
        """Stop the currently playing sound effect and clean up resources"""
        with self._producers_lock:
            if "sound_effect" in self._producers:
                producer = self._producers["sound_effect"]
                producer.loop = False  # Ensure loop flag is cleared
                producer._original_audio = None  # Clear original audio data
                producer.buffer.clear()  # Clear any pending audio
                producer.stop()  # Stop the producer
                del self._producers["sound_effect"]  # Remove from active producers
                logging.info("Sound effect stopped and cleaned up")
        
    def _play_wav_file(self, wav_path: str, producer_name: str = "sound_effect", loop: bool = False) -> bool:
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
                logging.info(f"Opening WAV file: {wav_path}")
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
                    producer_name, audio_data, should_loop = self._requeue_queue.get(timeout=0.1)
                except queue.Empty:
                    continue

                # Process the requeue request
                if self._running:
                    self.play_audio(audio_data, producer_name=producer_name, loop=should_loop)
                
                self._requeue_queue.task_done()
                
            except Exception as e:
                logging.error(f"Error in requeue loop: {e}", exc_info=True)
                time.sleep(0.1)  # Prevent tight loop on error
