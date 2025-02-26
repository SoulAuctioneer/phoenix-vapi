import sounddevice as sd
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
from config import SoundEffect, AudioBaseConfig

@dataclass
class AudioConfig:
    """Audio configuration parameters for mono int16 audio processing"""
    channels: int = AudioBaseConfig.NUM_CHANNELS
    rate: int = AudioBaseConfig.SAMPLE_RATE
    chunk: int = AudioBaseConfig.CHUNK_SIZE
    input_device_index: Optional[int] = None
    output_device_index: Optional[int] = None
    default_volume: float = AudioBaseConfig.DEFAULT_VOLUME
    
    def get_channels(self) -> int:
        """Get the number of output channels to use"""
        return max(1, self.channels)  # Ensure at least mono


class AudioBuffer:
    """Minimal thread-safe audio buffer with volume control for int16 audio"""
    def __init__(self, maxsize: int = AudioBaseConfig.BUFFER_SIZE):
        self.buffer = queue.Queue(maxsize=maxsize)
        self._lock = threading.Lock()
        self._volume = 1.0  # Default volume
        
    def put(self, data: np.ndarray) -> bool:
        """
        Put int16 audio data into buffer, dropping if full.
        
        Args:
            data: Audio data as numpy array with dtype=int16
        
        Returns:
            bool: True if data was successfully queued, False if buffer was full
        """
        try:
            # Ensure data is int16
            if data.dtype != np.int16:
                data = data.astype(np.int16)
                
            self.buffer.put_nowait(data)
            return True
        except queue.Full:
            return False
            
    def get(self) -> Optional[np.ndarray]:
        """
        Get volume-adjusted audio data from buffer.
        
        Returns:
            np.ndarray: int16 audio data with volume applied, or None if buffer is empty
        """
        try:
            data = self.buffer.get_nowait()
            if data is None:
                return None
                
            # Apply volume (efficient int16 scaling)
            if self._volume != 1.0:
                # Fast integer-based volume scaling for int16
                data = (data.astype(np.int32) * int(self._volume * 32767) // 32767).astype(np.int16)
                    
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
        self.active = True
        self.chunk_size = chunk_size


class AudioProducer:
    """Represents a producer of audio output data"""
    def __init__(self, name: str, chunk_size: Optional[int] = None, buffer_size: int = 100):
        self.name = name
        self.buffer = AudioBuffer(maxsize=buffer_size)
        self._volume = AudioBaseConfig.DEFAULT_VOLUME
        self.active = True
        self.chunk_size = chunk_size
        self._remainder = np.array([], dtype=np.int16)  # Always int16
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


class AudioManager:
    """Manages audio resources using SoundDevice for improved performance with int16 mono audio"""
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
        self._stream = None
        self._lock = threading.Lock()
        self._running = False
        
        # Audio consumers and producers
        self._consumers: List[AudioConsumer] = []
        self._producers: Dict[str, AudioProducer] = {}
        self._consumers_lock = threading.Lock()
        self._producers_lock = threading.Lock()
        
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
        logging.info(f"Creating producer: {name} with chunk_size={chunk_size}, buffer_size={buffer_size}")
        
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
    
    def _output_callback(self, outdata, frames, time, status):
        """
        Callback for output-only audio processing.
        
        This function is called by SoundDevice to fill the output buffer with audio data.
        It mixes audio from all active producers, duplicating mono audio across all output channels.
        
        Args:
            outdata: numpy array to fill with output data, shape is [frames, channels]
            frames: number of frames to fill
            time: time info from SoundDevice
            status: status info from SoundDevice
        """
        if status:
            logging.warning(f"Audio output callback status: {status}")
        
        try:
            # Get output channel count
            num_channels = outdata.shape[1]
            
            # Initialize output data with zeros
            outdata.fill(0)
            
            # Track active producers and audio status
            active_producers = 0
            has_audio_data = False
            
            # Mix audio from all active producers
            with self._producers_lock:
                for name, producer in self._producers.items():
                    if producer.active:
                        # Get volume-adjusted data from producer buffer
                        data = producer.buffer.get()
                        
                        if data is not None:
                            has_audio_data = True
                            
                            # Mix mono data into all output channels
                            frames_to_mix = min(len(data), frames)
                            
                            # Efficient duplication to all output channels
                            for c in range(num_channels):
                                outdata[:frames_to_mix, c] += data[:frames_to_mix]
                            
                            if frames_to_mix > 0:
                                # Log normalized max value for consistency
                                max_val = np.max(np.abs(data[:frames_to_mix])) / 32767.0
                                logging.debug(f"Mixed {frames_to_mix} frames from '{name}', max value: {max_val:.4f}")
                            
                            active_producers += 1
                            
                        # Requeue looping audio if buffer is empty
                        elif producer.loop and producer._original_audio is not None:
                            if producer.buffer.buffer.empty():
                                self._requeue_queue.put((name, producer._original_audio.copy(), producer.loop))
                                logging.debug(f"Requeuing looped audio for producer '{name}'")
            
            # Apply clipping if needed (prevent integer overflow distortion)
            if np.max(np.abs(outdata)) > 32700:  # Close to int16 max
                max_before = np.max(np.abs(outdata)) / 32767.0  # Normalized value
                np.clip(outdata, -32767, 32767, out=outdata)
                max_after = np.max(np.abs(outdata)) / 32767.0  # Normalized value
                logging.debug(f"Output max value: {max_before:.4f} -> {max_after:.4f} after clipping")
            
            if active_producers > 0:
                if has_audio_data:
                    logging.debug(f"Mixed audio from {active_producers} producers")
                
        except Exception as e:
            logging.error(f"Error in audio output callback: {e}", exc_info=True)
            # Fill with zeros on error to prevent noise
            outdata.fill(0)
            
    def _audio_callback(self, indata, outdata, frames, time, status):
        """Callback function for audio processing in duplex mode"""
        if status:
            logging.warning(f"Audio callback status: {status}")
        
        try:
            # Process input data (get mono from first channel)
            if indata is not None and frames > 0:
                audio_data = indata[:, 0].copy().astype(np.int16)
                
                # Distribute to all active consumers
                with self._consumers_lock:
                    for consumer in self._consumers:
                        if consumer.active:
                            consumer.callback(audio_data)
            
            # Forward to output callback
            self._output_callback(outdata, frames, time, status)
                
        except Exception as e:
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
                        
                        # Update config with default device's sample rate if needed
                        if self.config.rate != default_device_info['default_samplerate']:
                            logging.warning(f"Adjusting sample rate to match device: {default_device_info['default_samplerate']}")
                            self.config.rate = int(default_device_info['default_samplerate'])
                    except Exception as e:
                        logging.warning(f"Couldn't get default device info: {e}")
                
                # Determine what type of stream to create
                # Always create at least an input stream for wakeword detection and other services
                if self.config.input_device_index is not None or len(input_devices) > 0:
                    # Create a duplex stream for both input and output even if no consumers yet
                    # This ensures audio capture is available for wakeword detection
                    input_device = self.config.input_device_index
                    if input_device is None and len(input_devices) > 0:
                        # Use the default input device if none specified
                        input_device = sd.default.device[0]
                    
                    self._stream = sd.Stream(
                        samplerate=self.config.rate,
                        blocksize=self.config.chunk,
                        channels=(1, self.config.get_channels()),  # Always mono input, but allow multiple output channels
                        dtype='int16',  # Always use int16
                        callback=self._audio_callback,
                        device=(input_device, self.config.output_device_index)
                    )
                    logging.info(f"Created duplex stream with 1 input channel and {self.config.get_channels()} output channels")
                elif self._producers:
                    # Only output needed, no input capabilities
                    logging.info("Creating output-only stream")
                    
                    self._stream = sd.OutputStream(
                        samplerate=self.config.rate,
                        blocksize=self.config.chunk,
                        channels=self.config.get_channels(),  # Allow multiple output channels
                        dtype='int16',  # Always use int16
                        callback=self._output_callback,
                        device=self.config.output_device_index
                    )
                    logging.info(f"Created output-only stream with {self.config.get_channels()} channels using int16 format")
                else:
                    logging.warning("No input devices found and no producers registered. Audio functionality will be limited.")
                    return
                
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
                    producer._original_audio = None  # Clear any previous audio data
            
            # Check if audio data has the expected shape (1D array for mono)
            if len(audio_data.shape) > 1:
                logging.warning(f"Expected mono audio but got shape {audio_data.shape}. Treating as mono.")
                # Handle unexpected multi-dimensional arrays by flattening
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
                
                logging.debug(f"Converted audio to int16, max amplitude: {np.max(np.abs(audio_data))}")
            
            # Check for low amplitude
            max_amplitude = np.max(np.abs(audio_data))
            if max_amplitude < 100:  # Very low for int16
                logging.warning(f"Audio data has very low amplitude: {max_amplitude}, may not be audible")
            
            # Split audio data into chunks matching the configured chunk size
            chunk_size = self.config.chunk
            num_samples = len(audio_data)
            
            chunks_added = 0
            for i in range(0, num_samples, chunk_size):
                # Calculate chunk range
                end_sample = min(i + chunk_size, num_samples)
                chunk = audio_data[i:end_sample]
                
                # Pad the last chunk if needed
                if len(chunk) < chunk_size:
                    chunk = np.pad(chunk, (0, chunk_size - len(chunk)), mode='constant')
                
                success = producer.buffer.put(chunk)
                if success:
                    chunks_added += 1
                else:
                    logging.warning(f"Buffer full for producer '{producer_name}', chunk {i+1}/{(num_samples//chunk_size) + 1} dropped")
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
        """
        Play a mono WAV file through the audio system.
        
        Args:
            wav_path: Path to the WAV file
            producer_name: Name of the producer to use
            loop: Whether to loop the audio
            
        Returns:
            bool: True if playback started successfully, False otherwise
        """
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
                    
                    # Verify WAV format
                    if rate != self.config.rate:
                        logging.warning(f"WAV rate ({rate}) doesn't match config ({self.config.rate}), playback may be distorted")
                        
                    # Verify WAV is mono (since all WAVs should be mono)
                    if channels != 1:
                        logging.warning(f"Expected mono WAV file but got {channels} channels. File: {wav_path}")
                                        
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
                    
                    # Read audio data efficiently
                    audio_data = wf.readframes(frames)
                    
                    # Convert to int16 if needed
                    if width == 2:  # 16-bit audio
                        audio_array = np.frombuffer(audio_data, dtype=np.int16)
                    elif width == 1:  # 8-bit audio
                        audio_array = np.frombuffer(audio_data, dtype=np.uint8).astype(np.int16) * 256
                    elif width == 4:  # 32-bit audio
                        audio_array = np.frombuffer(audio_data, dtype=np.int32).astype(np.int16) // 65536
                    else:
                        logging.warning(f"Unusual bit depth: {width*8}-bit, trying to convert")
                        audio_array = np.frombuffer(audio_data, dtype=np.int16)
                    
                    # Play through the producer
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
        wf.setnchannels(1)  # Always mono for recording
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