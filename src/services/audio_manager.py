import pyaudio
import wave
import numpy as np
import threading
import queue
import logging
from typing import Optional, Dict, Any
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

class AudioManager:
    """Manages audio resources and provides thread-safe access"""
    def __init__(self, config: AudioConfig = AudioConfig()):
        self.config = config
        self._py_audio: Optional[pyaudio.PyAudio] = None
        self._input_stream: Optional[pyaudio.Stream] = None
        self._output_stream: Optional[pyaudio.Stream] = None
        self._lock = threading.Lock()
        self.input_buffer = AudioBuffer()
        self._running = False
        self._input_thread: Optional[threading.Thread] = None
        
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
                self._input_thread = threading.Thread(target=self._input_loop)
                self._input_thread.daemon = True
                self._input_thread.start()
            except Exception as e:
                logging.error(f"Failed to start audio: {e}")
                self.stop()
                raise
                
    def stop(self):
        """Stop audio processing and cleanup resources"""
        with self._lock:
            self._running = False
            
            if self._input_thread and self._input_thread.is_alive():
                self._input_thread.join(timeout=1.0)
                
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
            frames_per_buffer=self.config.chunk,
            stream_callback=self._input_callback
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
            self._input_stream.stop_stream()
            self._input_stream.close()
            self._input_stream = None
            
        if self._output_stream:
            self._output_stream.stop_stream()
            self._output_stream.close()
            self._output_stream = None
            
    def _input_callback(self, in_data, frame_count, time_info, status):
        """Callback for input stream"""
        if status:
            logging.warning(f"Audio input status: {status}")
        
        try:
            # Convert to numpy array
            audio_data = np.frombuffer(in_data, dtype=np.float32)
            
            # Put in buffer, drop if buffer is full
            if not self.input_buffer.put(audio_data):
                logging.warning("Audio input buffer full, dropping frame")
                
        except Exception as e:
            logging.error(f"Error in audio input callback: {e}")
            
        return (None, pyaudio.paContinue)
        
    def _input_loop(self):
        """Main input processing loop"""
        while self._running:
            try:
                data = self.input_buffer.get()
                if data is not None:
                    # Process audio data here
                    # For now, we just pass it through
                    pass
            except Exception as e:
                logging.error(f"Error in audio input loop: {e}")
                
    def play_audio(self, audio_data: np.ndarray):
        """Play audio data"""
        if not self._output_stream or not self._running:
            return
            
        try:
            self._output_stream.write(audio_data.tobytes())
        except Exception as e:
            logging.error(f"Error playing audio: {e}")
            
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