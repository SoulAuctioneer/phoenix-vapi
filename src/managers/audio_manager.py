import sounddevice as sd
import wave
import numpy as np
import threading
import queue
import logging
import time
import os
from typing import Optional, Dict, Any, List, Callable, Set
from dataclasses import dataclass
from contextlib import contextmanager
from config import SoundEffect, AudioBaseConfig

@dataclass
class AudioConfig:
    """Audio configuration parameters"""
    channels: int = AudioBaseConfig.NUM_CHANNELS
    input_channels: Optional[int] = None  # Separate input channels setting
    output_channels: Optional[int] = None  # Separate output channels setting
    rate: int = AudioBaseConfig.SAMPLE_RATE
    chunk: int = AudioBaseConfig.CHUNK_SIZE
    input_device_index: Optional[int] = None
    output_device_index: Optional[int] = None
    default_volume: float = AudioBaseConfig.DEFAULT_VOLUME
    # Preferred data format for audio processing
    dtype: str = 'int16'  # Options: 'int16', 'float32'
    
    def __post_init__(self):
        """Initialize derived values if not explicitly set"""
        if self.input_channels is None:
            self.input_channels = self.channels
        if self.output_channels is None:
            self.output_channels = self.channels
        # Validate dtype
        if self.dtype not in ('int16', 'float32'):
            logging.warning(f"Unsupported dtype '{self.dtype}', defaulting to 'int16'")
            self.dtype = 'int16'
            
    def get_input_channels(self) -> int:
        """Get the number of input channels to use"""
        return self.input_channels or self.channels
        
    def get_output_channels(self) -> int:
        """Get the number of output channels to use"""
        return self.output_channels or self.channels


class AudioBuffer:
    """Minimal thread-safe audio buffer with volume control"""
    def __init__(self, maxsize: int = AudioBaseConfig.BUFFER_SIZE, dtype: str = 'int16'):
        self.buffer = queue.Queue(maxsize=maxsize)
        self._lock = threading.Lock()
        self._volume = 1.0  # Default volume
        self.dtype = dtype  # Store buffer's native dtype
        
    def put(self, data: np.ndarray) -> bool:
        """
        Put audio data into buffer, dropping if full.
        
        Handles both int16 and float32 formats based on buffer's configured dtype.
        """
        try:
            # If data is already in the right format, use it directly
            if data.dtype == np.dtype(self.dtype):
                self.buffer.put_nowait(data)
                return True
                
            # Convert to the buffer's native format
            if self.dtype == 'int16':
                # Convert to int16
                if data.dtype == np.float32 or data.dtype == np.float64:
                    # Scale from [-1.0, 1.0] to int16 range
                    data = (data * 32767).astype(np.int16)
                    logging.debug(f"Converted float data to int16 on put")
                else:
                    # For other formats, just convert to int16
                    data = data.astype(np.int16)
                    
            elif self.dtype == 'float32':
                # Convert to float32
                if data.dtype == np.int16:
                    # Scale from int16 to [-1.0, 1.0] float32 range
                    data = data.astype(np.float32) / 32767.0
                    logging.debug(f"Converted int16 data to float32 on put")
                else:
                    # For other formats, just convert to float32
                    data = data.astype(np.float32)
                    
                # Ensure values are within [-1.0, 1.0]
                if np.max(np.abs(data)) > 1.0:
                    max_val = np.max(np.abs(data))
                    data = np.clip(data, -1.0, 1.0)
                    logging.debug(f"Clipped float32 data from max={max_val:.4f} to 1.0 on put")
                    
            self.buffer.put_nowait(data)
            return True
        except queue.Full:
            return False
            
    def get(self) -> Optional[np.ndarray]:
        """
        Get volume-adjusted audio data from buffer.
        
        Returns data in the buffer's native format (int16 or float32).
        """
        try:
            data = self.buffer.get_nowait()
            if data is None:
                return None
                
            # Apply volume based on data type
            if self._volume != 1.0:
                if self.dtype == 'int16':
                    # For int16, scale using integer math
                    data = (data.astype(np.int32) * int(self._volume * 32767) // 32767).astype(np.int16)
                else:  # float32
                    # For float32, simple multiplication
                    data = data * self._volume
                    # Ensure we didn't exceed [-1.0, 1.0] range
                    if np.max(np.abs(data)) > 1.0:
                        data = np.clip(data, -1.0, 1.0)
                    
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
    def __init__(self, name: str, chunk_size: Optional[int] = None, buffer_size: int = 100, dtype: str = 'int16'):
        self.name = name
        self.buffer = AudioBuffer(maxsize=buffer_size, dtype=dtype)
        self._volume = AudioBaseConfig.DEFAULT_VOLUME
        self.active = True
        self.chunk_size = chunk_size
        # Remainder should match buffer's dtype
        self._remainder = np.array([], dtype=np.dtype(dtype))
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
            
        # Combine with any remainder from last time
        if len(self._remainder) > 0:
            audio_data = np.concatenate([self._remainder, audio_data])
            
        # Calculate how many complete chunks we can extract
        total_samples = len(audio_data)
        num_chunks = total_samples // self.chunk_size
        
        # Extract complete chunks
        chunks = []
        for i in range(num_chunks):
            start = i * self.chunk_size
            end = start + self.chunk_size
            chunks.append(audio_data[start:end])
            
        # Save remainder for next time
        remainder_start = num_chunks * self.chunk_size
        self._remainder = audio_data[remainder_start:]
        
        return chunks


class OptimizedAudioManager:
    """Manages audio resources using SoundDevice for improved performance"""
    _instance = None

    @classmethod
    def get_instance(cls, config: AudioConfig = None) -> 'OptimizedAudioManager':
        """Get or create the AudioManager singleton instance"""
        if cls._instance is None:
            if config is None:
                config = AudioConfig()
            cls._instance = cls(config)
        return cls._instance

    def __init__(self, config: AudioConfig = AudioConfig()):
        if OptimizedAudioManager._instance is not None:
            raise RuntimeError("Use OptimizedAudioManager.get_instance() to get the AudioManager instance")
            
        self.config = config
        self._stream = None
        self._lock = threading.Lock()
        self._running = False
        
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
        
        # Keep track of device information
        self._device_info = None
        
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
        logging.info(f"Creating new producer: {name} with chunk_size={chunk_size}, buffer_size={buffer_size}")
        
        producer = AudioProducer(name, chunk_size=chunk_size, buffer_size=buffer_size, dtype=self.config.dtype)
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
    
    def _output_callback(self, outdata, frames, time, status):
        """
        Callback for output-only audio processing.
        
        This function is called by SoundDevice to fill the output buffer with audio data.
        It mixes audio from all active producers and handles proper format conversion.
        
        Args:
            outdata: numpy array to fill with output data, shape is [frames, channels]
            frames: number of frames to fill
            time: time info from SoundDevice
            status: status info from SoundDevice
        """
        if status:
            logging.warning(f"Audio output callback status: {status}")
        
        try:
            # Get output channel count (outdata shape is [frames, channels])
            num_channels = outdata.shape[1]
            
            # Initialize output data with zeros
            outdata.fill(0)
            
            # Track active producers for mixing
            active_producers = 0
            has_audio_data = False
            
            # Optimized mixing based on data type
            is_int16_output = outdata.dtype == np.int16
            
            # Mix audio from all active producers
            with self._producers_lock:
                for name, producer in self._producers.items():
                    if producer.active:
                        # Get data from producer buffer
                        data = producer.buffer.get()  # Volume already applied here
                        
                        if data is not None:
                            has_audio_data = True
                            logging.debug(f"Got data from producer '{name}': shape={data.shape}, dtype={data.dtype}")
                            
                            # Check if the data matches the expected output format
                            # We need [frames, channels] format for SoundDevice
                            if len(data.shape) == 1:
                                # This is interleaved or mono data, reshape based on channels
                                logging.debug(f"Reshaping 1D data of length {len(data)}")
                                if len(data) % num_channels == 0:
                                    # Interleaved stereo data, reshape to [frames, channels]
                                    frames_in_chunk = len(data) // num_channels
                                    data = data.reshape((frames_in_chunk, num_channels))
                                    logging.debug(f"Reshaped interleaved data to {data.shape}")
                                else:
                                    # Mono data, duplicate to all channels
                                    mono_frames = min(len(data), frames)
                                    logging.debug(f"Duplicating mono data to {num_channels} channels")
                                    for c in range(num_channels):
                                        outdata[:mono_frames, c] += data[:mono_frames]
                                    active_producers += 1
                                    continue
                            
                            # Mix audio data into output buffer
                            frames_to_mix = min(data.shape[0], frames)
                            
                            # Direct addition - no scaling needed since volume is already applied
                            outdata[:frames_to_mix] += data[:frames_to_mix]
                            
                            # Log some stats about the data we're mixing
                            if frames_to_mix > 0:
                                if is_int16_output:
                                    max_val = np.max(np.abs(data[:frames_to_mix])) / 32767.0
                                else:
                                    max_val = np.max(np.abs(data[:frames_to_mix]))
                                logging.debug(f"Mixed {frames_to_mix} frames from '{name}', max value: {max_val:.4f}")
                            
                            active_producers += 1
                            
                        # If buffer is empty and looping is enabled, requeue
                        elif producer.loop and producer._original_audio is not None:
                            if producer.buffer.buffer.empty():
                                self._requeue_queue.put((name, producer._original_audio, producer.loop))
                                logging.debug(f"Requeuing looped audio for producer '{name}'")
            
            # Apply clipping prevention based on output format
            if is_int16_output and np.max(np.abs(outdata)) > 100:  # Threshold for int16
                max_before = np.max(np.abs(outdata)) / 32767.0  # Normalize for logging
                np.clip(outdata, -32767, 32767, out=outdata)
                max_after = np.max(np.abs(outdata)) / 32767.0  # Normalize for logging
                logging.debug(f"Output max value: {max_before:.4f} -> {max_after:.4f} after clipping")
            elif not is_int16_output and np.max(np.abs(outdata)) > 0.05:  # Threshold for float32
                max_before = np.max(np.abs(outdata))
                np.clip(outdata, -1.0, 1.0, out=outdata)
                max_after = np.max(np.abs(outdata))
                logging.debug(f"Output max value: {max_before:.4f} -> {max_after:.4f} after clipping")
            
            if active_producers > 0:
                if has_audio_data:
                    logging.debug(f"Mixed audio from {active_producers} producers with data")
                else:
                    logging.debug(f"Had {active_producers} active producers but no audio data")
                
        except Exception as e:
            logging.error(f"Error in audio output callback: {e}", exc_info=True)
            # Fill with zeros on error to prevent noise
            outdata.fill(0)
            
    def _audio_callback(self, indata, outdata, frames, time, status):
        """Callback function for audio processing in duplex mode"""
        if status:
            logging.warning(f"Audio callback status: {status}")
        
        try:
            # Process input data (indata is a 2D array with shape [frames, channels])
            if indata is not None and frames > 0:
                # Convert to mono and desired format
                audio_data = indata[:, 0].copy().astype(np.int16)
                
                # Distribute to all active consumers
                with self._consumers_lock:
                    for consumer in self._consumers:
                        if consumer.active:
                            if consumer.chunk_size and consumer.chunk_size != frames:
                                # If consumer needs a different chunk size
                                chunk_resizer = self._get_chunk_resizer(consumer.chunk_size)
                                resized_chunks = chunk_resizer.resize_chunk(audio_data)
                                for chunk in resized_chunks:
                                    consumer.callback(chunk)
                            else:
                                consumer.callback(audio_data)
            
            # Forward to output callback for consistent handling
            self._output_callback(outdata, frames, time, status)
                
        except Exception as e:
            logging.error(f"Error in audio callback: {e}", exc_info=True)
            # Fill with zeros on error to prevent noise
            outdata.fill(0.0)
        
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
                        
                        # Update config with default device's sample rate if needed
                        if self.config.rate != default_device_info['default_samplerate']:
                            logging.warning(f"Adjusting sample rate from {self.config.rate} to match device: {default_device_info['default_samplerate']}")
                            self.config.rate = int(default_device_info['default_samplerate'])
                    except Exception as e:
                        logging.warning(f"Couldn't get default device info: {e}")
                
                # Check if we need to create a duplex stream or just output
                if self.config.input_device_index is not None and self._consumers:
                    # Create a duplex stream with proper channel configuration for both input and output
                    self._stream = sd.Stream(
                        samplerate=self.config.rate,
                        blocksize=self.config.chunk, 
                        channels=(self.config.get_input_channels(), self.config.get_output_channels()),
                        dtype=self.config.dtype,  # Use the configured dtype
                        callback=self._audio_callback,
                        device=(self.config.input_device_index, self.config.output_device_index)
                    )
                    logging.info(f"Created duplex stream with {self.config.get_input_channels()} input channels and {self.config.get_output_channels()} output channels")
                elif self._producers:
                    # Just output, no input needed
                    logging.info("Creating output-only stream")
                    logging.debug(f"Stream config: rate={self.config.rate}, blocksize={self.config.chunk}, channels={self.config.get_output_channels()}, dtype={self.config.dtype}")
                    
                    self._stream = sd.OutputStream(
                        samplerate=self.config.rate,
                        blocksize=self.config.chunk, 
                        channels=self.config.get_output_channels(),
                        dtype=self.config.dtype,  # Use the configured dtype
                        callback=self._output_callback,
                        device=self.config.output_device_index
                    )
                    logging.info(f"Created output-only stream with {self.config.get_output_channels()} channels using {self.config.dtype} format")
                else:
                    logging.error("No consumers or producers registered, not starting stream")
                    return
                
                # Log stream details before starting
                logging.debug(f"Stream configuration: {self._stream}")
                
                # Start the stream
                self._stream.start()
                self._running = True
                
                # Start requeue thread for handling looped audio
                self._requeue_stop.clear()
                self._requeue_thread = threading.Thread(target=self._requeue_loop, name="AudioRequeueThread")
                self._requeue_thread.daemon = True
                self._requeue_thread.start()
                
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
            self._requeue_stop.set()
            
            # Stop all consumers and producers
            with self._consumers_lock:
                for consumer in self._consumers:
                    consumer.active = False
            with self._producers_lock:
                for producer in self._producers.values():
                    producer.active = False
            
            # Wait for requeue thread to finish
            if self._requeue_thread and self._requeue_thread.is_alive():
                self._requeue_thread.join(timeout=1.0)
                
            # Stop and close the audio stream
            if self._stream:
                self._stream.stop()
                self._stream.close()
                self._stream = None
                
            logging.info("AudioManager stopped successfully")
                
    def _get_chunk_resizer(self, chunk_size: int) -> AudioProducer:
        """Get or create a reusable chunk resizer with the specified chunk size"""
        with self._chunk_resizer_lock:
            if self._chunk_resizer is None or self._chunk_resizer.chunk_size != chunk_size:
                if self._chunk_resizer is not None:
                    # Clear any existing data
                    self._chunk_resizer.buffer.clear()
                self._chunk_resizer = AudioProducer("chunk_resizer", chunk_size=chunk_size)
            return self._chunk_resizer

    def play_audio(self, audio_data: np.ndarray, producer_name: str = "default", loop: bool = False):
        """
        Play audio data through a specific producer.
        
        Args:
            audio_data: Audio data to play as numpy array
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
            
            # Log the audio data's initial properties
            logging.debug(f"Original audio data: shape={audio_data.shape}, dtype={audio_data.dtype}, min={np.min(audio_data):.4f}, max={np.max(audio_data):.4f}")
            
            # Process based on the stream's dtype
            target_dtype = self.config.dtype
            num_channels = self.config.get_output_channels()
            
            # Detect audio data format and convert as needed
            is_int16_target = target_dtype == 'int16'
            is_float32_target = target_dtype == 'float32'
            
            # Detect stereo/mono format (interleaved or shaped)
            is_stereo_data = False
            is_shaped_format = False
            
            # Check if data is already in [frames, channels] format
            if len(audio_data.shape) == 2:
                is_shaped_format = True
                if audio_data.shape[1] == 2:
                    is_stereo_data = True
                    logging.info("Detected stereo audio data in [frames, channels] format")
                else:
                    logging.info(f"Detected shaped audio data with {audio_data.shape[1]} channels")
            # Check if interleaved stereo data
            elif num_channels == 2 and len(audio_data) % 2 == 0:
                # Might be interleaved stereo
                left_samples = audio_data[0::2]
                right_samples = audio_data[1::2]
                if not np.allclose(left_samples, right_samples, rtol=0.1):
                    is_stereo_data = True
                    logging.info("Detected interleaved stereo audio data")
            
            # Log audio data properties
            logging.info(f"Audio data: shape={audio_data.shape}, dtype={audio_data.dtype}, " +
                        f"stereo={is_stereo_data}, shaped={is_shaped_format}, target_format={target_dtype}")
            
            # Convert to the format expected by SoundDevice (non-interleaved [frames, channels])
            if is_stereo_data and not is_shaped_format and num_channels == 2:
                # Convert from interleaved to [frames, channels]
                frames = len(audio_data) // 2
                reshaped_data = np.empty((frames, 2), dtype=audio_data.dtype)
                reshaped_data[:, 0] = audio_data[0::2]  # Left channel
                reshaped_data[:, 1] = audio_data[1::2]  # Right channel
                audio_data = reshaped_data
                logging.info(f"Converted interleaved stereo data to [frames, channels] format: {audio_data.shape}")
            
            # Double-check there's actual audio content (not all zeroes)
            if is_int16_target:
                max_val = np.max(np.abs(audio_data)) / 32767 if audio_data.dtype == np.int16 else np.max(np.abs(audio_data))
            else:
                max_val = np.max(np.abs(audio_data)) if audio_data.dtype == np.float32 else np.max(np.abs(audio_data)) / 32767
                
            if max_val < 0.001:
                logging.warning(f"Audio data has very low amplitude: {max_val:.6f}, may not be audible")
            
            # Skip unnecessary format conversions if possible
            # The AudioBuffer.put() method will handle specific conversions
            
            # Split audio data into chunks matching the configured chunk size
            chunk_size = self.config.chunk
            
            if len(audio_data.shape) == 2:  # [frames, channels] format
                total_frames = audio_data.shape[0]
                
                chunks_added = 0
                for i in range(0, total_frames, chunk_size):
                    # Calculate frame range
                    end_frame = min(i + chunk_size, total_frames)
                    chunk = audio_data[i:end_frame]
                    
                    # Pad the last chunk if needed
                    if chunk.shape[0] < chunk_size:
                        padding = ((0, chunk_size - chunk.shape[0]), (0, 0))
                        chunk = np.pad(chunk, padding, mode='constant')
                    
                    # Log one chunk sample to verify data
                    if i == 0:
                        logging.debug(f"First chunk: shape={chunk.shape}, min={np.min(chunk):.4f}, max={np.max(chunk):.4f}")
                        
                    success = producer.buffer.put(chunk)
                    if success:
                        chunks_added += 1
                    else:
                        logging.warning(f"Buffer full for producer '{producer_name}', chunk {i+1}/{total_frames//chunk_size + 1} dropped")
                        break
                
                logging.info(f"Added {chunks_added} shaped audio chunks to producer '{producer_name}'")
            else:  # mono or other format
                num_samples = len(audio_data)
                num_chunks = (num_samples + chunk_size - 1) // chunk_size  # Round up
                
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
        if not os.path.exists(wav_path):
            logging.error(f"Sound effect file not found: {wav_path}")
            return False
            
        return self._play_wav_file(wav_path, producer_name="sound_effect", loop=loop)

    def stop_sound(self, effect_name: str):
        """Stop the currently playing sound effect and clean up resources"""
        with self._producers_lock:
            # TODO: Change to use effect_name instead of "sound_effect" so we have a producer for each sound effect
            if "sound_effect" in self._producers:
                producer = self._producers["sound_effect"]
                producer.loop = False  # Ensure loop flag is cleared
                producer._original_audio = None  # Clear original audio data
                producer.buffer.clear()  # Clear any pending audio
                producer.active = False  # Mark as inactive
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
                    if channels > self.config.get_output_channels():
                        logging.warning(f"WAV channels ({channels}) greater than config ({self.config.get_output_channels()}), audio will be downmixed")
                    if rate != self.config.rate:
                        logging.warning(f"WAV rate ({rate}) doesn't match config ({self.config.rate}), playback may be distorted")
                                        
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
                    
                    # Read audio data in the most efficient format
                    audio_data = wf.readframes(frames)
                    
                    # Convert based on the target dtype
                    if width == 2:  # 16-bit audio
                        audio_array = np.frombuffer(audio_data, dtype=np.int16)
                    elif width == 1:  # 8-bit audio
                        audio_array = np.frombuffer(audio_data, dtype=np.uint8).astype(np.int16) * 256
                    elif width == 4:  # 32-bit audio
                        audio_array = np.frombuffer(audio_data, dtype=np.int32).astype(np.int16) // 65536
                    else:
                        logging.warning(f"Unusual bit depth: {width*8}-bit, trying to convert")
                        audio_array = np.frombuffer(audio_data, dtype=np.int16)
                    
                    # Reshape for stereo if necessary
                    if channels == 2:
                        # Reshape to [frames, channels] for SoundDevice
                        audio_array = audio_array.reshape(-1, 2)
                    
                    # Play through the producer using audio_array directly
                    # The AudioBuffer.put() will handle any needed conversion
                    self.play_audio(audio_array, producer_name=producer_name, loop=loop)
                    logging.info(f"Playing WAV file: {wav_path}, channels={channels}, rate={rate}, frames={frames}")
                    
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
        wf.setsampwidth(2)  # 16-bit audio = 2 bytes
        wf.setframerate(self.config.rate)
        
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

# Compatibility layer - remap AudioManager to OptimizedAudioManager
# This ensures existing code can still use AudioManager
AudioManager = OptimizedAudioManager 