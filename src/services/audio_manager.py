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
    format: int = pyaudio.paFloat32
    channels: int = 1
    rate: int = 16000
    chunk: int = 1024
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
    def __init__(self, callback: Callable[[np.ndarray], None]):
        self.callback = callback
        self.buffer = AudioBuffer()
        self.active = True

class AudioProducer:
    """Represents a producer of audio output data"""
    def __init__(self, name: str):
        self.name = name
        self.buffer = AudioBuffer()
        self.volume = 1.0
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
        
    def add_consumer(self, callback: Callable[[np.ndarray], None]) -> AudioConsumer:
        """Add a new audio consumer"""
        consumer = AudioConsumer(callback)
        with self._consumers_lock:
            self._consumers.append(consumer)
        return consumer
        
    def remove_consumer(self, consumer: AudioConsumer):
        """Remove an audio consumer"""
        with self._consumers_lock:
            if consumer in self._consumers:
                consumer.active = False
                self._consumers.remove(consumer)
                
    def add_producer(self, name: str) -> AudioProducer:
        """Add a new audio producer"""
        producer = AudioProducer(name)
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
                return
                
            try:
                self._py_audio = pyaudio.PyAudio()
                self._setup_streams()
                self._running = True
                
                # Start input and output threads
                self._input_thread = threading.Thread(target=self._input_loop, name="AudioInputThread")
                self._output_thread = threading.Thread(target=self._output_loop, name="AudioOutputThread")
                self._input_thread.daemon = True
                self._output_thread.daemon = True
                self._input_thread.start()
                self._output_thread.start()
                
            except Exception as e:
                logging.error(f"Failed to start audio: {e}")
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
            return
            
        # Setup input stream
        self._input_stream = self._py_audio.open(
            format=self.config.format,
            channels=self.config.channels,
            rate=self.config.rate,
            input=True,
            input_device_index=self.config.input_device_index,
            frames_per_buffer=self.config.chunk
        )
        
        # Setup output stream
        self._output_stream = self._py_audio.open(
            format=self.config.format,
            channels=self.config.channels,
            rate=self.config.rate,
            output=True,
            output_device_index=self.config.output_device_index,
            frames_per_buffer=self.config.chunk
        )
        
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
        while self._running:
            try:
                # Read from input stream
                data = self._input_stream.read(self.config.chunk, exception_on_overflow=False)
                audio_data = np.frombuffer(data, dtype=np.float32)
                
                # Distribute to all active consumers
                with self._consumers_lock:
                    for consumer in self._consumers:
                        if consumer.active:
                            consumer.callback(audio_data)
                            
            except Exception as e:
                logging.error(f"Error in audio input loop: {e}")
                
    def _output_loop(self):
        """Main output processing loop"""
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
                                mixed_audio += data * producer.volume
                                active_producers += 1
                    
                    # Normalize if we have multiple producers
                    if active_producers > 1:
                        mixed_audio /= active_producers
                        
                # Write to output stream
                if active_producers > 0:
                    self._output_stream.write(mixed_audio.tobytes())
                    
            except Exception as e:
                logging.error(f"Error in audio output loop: {e}")
                
    def play_audio(self, audio_data: np.ndarray, producer_name: str = "default"):
        """Play audio data through a specific producer"""
        if not self._running:
            return
            
        with self._producers_lock:
            if producer_name not in self._producers:
                self.add_producer(producer_name)
            producer = self._producers[producer_name]
            if producer.active:
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