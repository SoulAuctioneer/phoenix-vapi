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
from src.config import SoundEffect, AUDIO_DEFAULT_VOLUME, AudioBaseConfig
from src.core.audio_core import AudioCore

@dataclass
class AudioConfig:
    """Audio configuration parameters"""
    format: int = AudioBaseConfig.FORMAT
    channels: int = AudioBaseConfig.NUM_CHANNELS
    rate: int = AudioBaseConfig.SAMPLE_RATE
    chunk: int = AudioBaseConfig.CHUNK_SIZE
    input_device_index: Optional[int] = None
    output_device_index: Optional[int] = None
    default_volume: float = AUDIO_DEFAULT_VOLUME


class AudioBuffer:
    """Minimal thread-safe audio buffer"""
    def __init__(self, maxsize: int = AudioBaseConfig.BUFFER_SIZE):
        self.buffer = queue.Queue(maxsize=maxsize)
        self._lock = threading.Lock()
        
    def put(self, data: np.ndarray) -> bool:
        """Put data into buffer, dropping if full"""
        try:
            self.buffer.put_nowait(data)
            return True
        except queue.Full:
            return False
            
    def get(self) -> Optional[np.ndarray]:
        """Get data from buffer"""
        try:
            return self.buffer.get_nowait()
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

class AudioConsumer:
    """Represents a consumer of audio input data"""
    def __init__(self, callback: Callable[[np.ndarray], None], chunk_size: Optional[int] = None):
        self.callback = callback
        self.buffer = AudioBuffer()
        self.active = True
        self.chunk_size = chunk_size

class AudioProducer:
    """Represents a producer of audio output data"""
    def __init__(self, name: str, producer_id: int):
        self.name = name
        self.producer_id = producer_id
        self.volume = AUDIO_DEFAULT_VOLUME
        self.active = True

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
        
        # Pre-allocated buffers for audio mixing
        self._mixed_buffer = np.zeros(self.config.chunk, dtype=np.float32)  # Using float32 for mixing
        self._output_buffer = np.zeros(self.config.chunk, dtype=np.int16)  # Final output buffer
        
        self._audio_core = None
        
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
                
    def _create_producer(self, name: str, buffer_size: int = 32768) -> AudioProducer:
        """Create a new producer instance with a larger default buffer size"""
        producer_id = self._audio_core.create_producer(buffer_size)
        if producer_id < 0:
            raise RuntimeError("Failed to create audio producer")
            
        producer = AudioProducer(name, producer_id)
        return producer
        
    def add_producer(self, name: str, buffer_size: int = 32768) -> AudioProducer:
        """Add a new audio producer with a larger default buffer size"""
        producer = self._create_producer(name, buffer_size)
        self._producers[name] = producer
        logging.info(f"Producer '{name}' added and activated")
        return producer
        
    def remove_producer(self, name: str):
        """Remove an audio producer"""
        if name in self._producers:
            producer = self._producers[name]
            producer.active = False
            self._audio_core.set_active(producer.producer_id, False)
            del self._producers[name]
                
    def set_producer_volume(self, name: str, volume: float):
        """Set volume for a specific producer"""
        if name in self._producers:
            producer = self._producers[name]
            producer.volume = max(0.0, min(1.0, volume))
            self._audio_core.set_volume(producer.producer_id, producer.volume)
                
    @property
    def is_running(self) -> bool:
        return self._running
        
    def start(self):
        """Start audio processing"""
        if self._running:
            logging.info("AudioManager already running")
            return
            
        try:
            logging.info("Initializing audio core...")
            self._audio_core = AudioCore()
            self._running = True
            logging.info("AudioManager started successfully")
            
        except Exception as e:
            logging.error(f"Failed to start audio: {e}", exc_info=True)
            self.stop()
            raise
                
    def stop(self):
        """Stop audio processing and cleanup resources"""
        self._running = False
        self._audio_core = None
        self._producers.clear()
                
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
                # Reset the mixed buffer (faster than creating new array)
                self._mixed_buffer.fill(0)
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
                            data = producer.buffer.get()
                            if data is not None:
                                no_data_count = 0  # Reset no-data counter
                                if len(data) == self.config.chunk:
                                    # Simple mixing with volume adjustment
                                    audio_float = data.astype(np.float32) * 0.8  # Scale down to prevent clipping
                                    if producer.volume != 1.0:
                                        audio_float *= producer.volume
                                    self._mixed_buffer += audio_float
                                    active_producers += 1
                                    state['had_data'] = True
                                    logging.debug(f"Mixed data from producer '{name}'")
                                else:
                                    logging.warning(f"Skipped chunk from '{name}': expected {self.config.chunk} samples, got {len(data)}")
                            else:
                                if producer.buffer.buffer.empty():
                                    no_data_count += 1
                                    if no_data_count % 100 == 0:  # Log every 100th no-data iteration
                                        logging.debug(f"No data available from producer '{name}' for {no_data_count} iterations")
                    
                    # Convert mixed float32 back to int16
                    if active_producers > 0:
                        # Clip in float32 first
                        np.clip(self._mixed_buffer, -32768, 32767, out=self._mixed_buffer)
                        # Then convert to int16
                        self._output_buffer[:] = self._mixed_buffer.astype(np.int16)
                        self._output_stream.write(self._output_buffer.tobytes())
                    else:
                        # Small sleep to prevent spinning too fast when no data
                        time.sleep(0.001)  # 1ms sleep
                    
            except Exception as e:
                if self._running:  # Only log if we haven't stopped intentionally
                    logging.error(f"Error in output loop: {e}", exc_info=True)
                    
        logging.info("Output processing loop stopped")
                
    def play_audio(self, audio_data: np.ndarray, producer_name: str = "default"):
        """Play audio data through a specific producer"""
        logging.info(f"play_audio called for producer '{producer_name}' with {len(audio_data)} samples")
        
        try:
            if not self._running:
                logging.warning("play_audio called but AudioManager is not running")
                return
                
            # Create producer if needed
            if producer_name not in self._producers:
                logging.info(f"Creating new producer '{producer_name}'")
                producer = self.add_producer(producer_name)
            else:
                producer = self._producers[producer_name]
                
            if not producer.active:
                logging.warning(f"Producer '{producer_name}' is not active")
                return
                    
            # Convert to float32 and normalize
            if audio_data.dtype != np.float32:
                audio_data = audio_data.astype(np.float32)
                if audio_data.dtype == np.int16:
                    audio_data /= 32768.0
                    
            # Write to audio core
            samples_written = self._audio_core.write_samples(producer.producer_id, audio_data)
            if samples_written < len(audio_data):
                logging.warning(f"Buffer full for producer '{producer_name}', {len(audio_data) - samples_written} samples dropped")
                    
        except Exception as e:
            logging.error(f"Error in play_audio: {str(e)}", exc_info=True)
                
    def play_sound(self, effect_name: str) -> bool:
        """
        Play a sound effect by name.
        Args:
            effect_name: Name of the sound effect (case-insensitive)
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
            
        return self._play_wav_file(wav_path, producer_name="sound_effect") 
        
    def _play_wav_file(self, wav_path: str, producer_name: str = "sound_effect") -> bool:
        """Play a WAV file through the audio system"""
        if not self._running:
            logging.error("Cannot play WAV file - AudioManager not running")
            return False

        def _play_in_thread():
            try:
                logging.info(f"Opening WAV file: {wav_path}")
                with wave.open(wav_path, "rb") as wf:
                    # Verify WAV format matches our configuration
                    if wf.getnchannels() != self.config.channels:
                        logging.error(f"WAV channels ({wf.getnchannels()}) doesn't match config ({self.config.channels})")
                        return False
                    if wf.getframerate() != self.config.rate:
                        logging.error(f"WAV rate ({wf.getframerate()}) doesn't match config ({self.config.rate})")
                        return False
                    if wf.getsampwidth() != 2:  # We expect 16-bit audio
                        logging.error(f"WAV sample width ({wf.getsampwidth()}) doesn't match expected (2)")
                        return False
                                        
                    # Create producer if needed
                    if producer_name not in self._producers:
                        producer = self.add_producer(producer_name)
                    else:
                        producer = self._producers[producer_name]
                        
                    # Read and play in chunks
                    chunk_frames = self.config.chunk
                    chunk_bytes = chunk_frames * wf.getnchannels() * wf.getsampwidth()
                    
                    while self._running and producer.active:
                        data = wf.readframes(chunk_frames)
                        if not data:
                            break
                            
                        # Pad the last chunk if needed
                        if len(data) < chunk_bytes:
                            data = data + b'\x00' * (chunk_bytes - len(data))
                            
                        # Convert to float32 (-1.0 to 1.0 range)
                        audio_chunk = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
                        
                        # Write to audio core with retries
                        max_retries = 3
                        for _ in range(max_retries):
                            samples_written = self._audio_core.write_samples(producer.producer_id, audio_chunk)
                            if samples_written == len(audio_chunk):
                                break
                            time.sleep(chunk_frames / self.config.rate)  # Wait for one chunk duration
                        else:
                            logging.warning("Buffer full after retries, dropping audio chunk")
                            
                    logging.debug(f"Finished playing WAV file: {wav_path}")
                    
            except FileNotFoundError:
                logging.error(f"WAV file not found: {wav_path}")
                return False
            except Exception as e:
                logging.error(f"Failed to play WAV file {wav_path}: {str(e)}", exc_info=True)
                return False
                
            return True

        # Start playback in a separate thread
        import threading
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
