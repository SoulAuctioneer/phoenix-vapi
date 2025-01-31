import pyaudio
import wave
import numpy as np
import threading
import queue
import logging
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass
from contextlib import contextmanager

@dataclass
class AudioConfig:
    """Audio configuration parameters"""
    format: int = pyaudio.paInt16
    channels: int = 1
    rate: int = 16000
    chunk: int = 512
    input_device_index: Optional[int] = None
    output_device_index: Optional[int] = None

class AudioBuffer:
    """Thread-safe circular buffer for audio data"""
    def __init__(self, maxsize: int = 10):
        self.buffer = queue.Queue(maxsize=maxsize)
        self._lock = threading.Lock()
        
    def put(self, data: np.ndarray) -> bool:
        """Put data into buffer, returns False if buffer is full"""
        try:
            self.buffer.put_nowait(data)
            return True
        except queue.Full:
            return False
            
    def get(self) -> Optional[np.ndarray]:
        """Get data from buffer, returns None if buffer is empty"""
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
    def __init__(self, name: str, chunk_size: Optional[int] = None):
        self.name = name
        self.buffer = AudioBuffer()
        self.volume = 1.0
        self.active = True
        self.chunk_size = chunk_size
        self._remainder = np.array([], dtype=np.int16)

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

    def apply_volume(self, audio_data: np.ndarray) -> np.ndarray:
        """Apply volume control to int16 audio data"""
        if self.volume == 1.0:
            return audio_data
        # Convert to float32 temporarily for volume adjustment to prevent integer overflow
        audio_float = audio_data.astype(np.float32) * self.volume
        # Clip to int16 range and convert back
        return np.clip(audio_float, -32768, 32767).astype(np.int16)

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
                
    def add_producer(self, name: str, chunk_size: Optional[int] = None) -> AudioProducer:
        """Add a new audio producer"""
        producer = AudioProducer(name, chunk_size)
        with self._producers_lock:
            self._producers[name] = producer
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
                self._input_thread.daemon = True
                self._output_thread.daemon = True
                self._input_thread.start()
                self._output_thread.start()
                logging.info("AudioManager started successfully")
                
            except Exception as e:
                logging.error(f"Failed to start audio: {e}", exc_info=True)
                self.stop()
                raise
                
    def stop(self):
        """Stop audio processing and cleanup resources"""
        with self._lock:
            self._running = False
            
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
                                resized_chunks = AudioProducer("temp", consumer.chunk_size).resize_chunk(audio_data)
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
        while self._running:
            try:
                # Mix audio from all active producers
                mixed_audio = np.zeros(self.config.chunk, dtype=np.float32)
                
                with self._producers_lock:
                    active_producers = 0
                    for producer in self._producers.values():
                        if producer.active:
                            data = producer.buffer.get()
                            if data is not None:
                                if producer.chunk_size and producer.chunk_size != self.config.chunk:
                                    resized_chunks = producer.resize_chunk(data)
                                    if resized_chunks:
                                        data = resized_chunks[0]
                                        for chunk in resized_chunks[1:]:
                                            producer.buffer.put(chunk)
                                    else:
                                        continue
                                
                                if len(data) == self.config.chunk:
                                    # Convert to float32 for mixing to prevent integer overflow
                                    audio_float = data.astype(np.float32)
                                    if producer.volume != 1.0:
                                        audio_float *= producer.volume
                                    mixed_audio += audio_float
                                    active_producers += 1
                    
                    # Normalize if we have multiple producers
                    if active_producers > 1:
                        mixed_audio /= active_producers
                        
                    # Convert back to int16 and clip to prevent overflow
                    mixed_audio = np.clip(mixed_audio, -32768, 32767).astype(np.int16)
                        
                # Write to output stream
                if active_producers > 0:
                    self._output_stream.write(mixed_audio.tobytes())
                    
            except Exception as e:
                if self._running:  # Only log if we haven't stopped intentionally
                    logging.error(f"Error in output loop: {e}", exc_info=True)
        logging.info("Output processing loop stopped")
                
    def play_audio(self, audio_data: np.ndarray, producer_name: str = "default"):
        """Play audio data through a specific producer"""
        if not self._running:
            return
            
        with self._producers_lock:
            if producer_name not in self._producers:
                self.add_producer(producer_name)
            producer = self._producers[producer_name]
            if producer.active:
                # Ensure audio data is int16
                if audio_data.dtype != np.int16:
                    audio_data = np.clip(audio_data * 32767, -32768, 32767).astype(np.int16)
                producer.buffer.put(audio_data)
                
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