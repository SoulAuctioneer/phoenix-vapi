import logging
import numpy as np
from config import AudioBaseConfig, get_filter_logger

logger = get_filter_logger(__name__)

try:
    import pyrubberband as pyrb
    PYRUBBERBAND_AVAILABLE = True
    logger.info("pyrubberband found, pitch shifting is available.")
except ImportError:
    PYRUBBERBAND_AVAILABLE = False
    logger.warning("pyrubberband not found, pitch shifting is disabled. To enable, run: pip install pyrubberband")

try:
    from stftpitchshift import StftPitchShift
    STFTPITCHSHIFT_AVAILABLE = True
    logger.info("stftpitchshift found, streaming pitch shifting is available.")
except ImportError:
    STFTPITCHSHIFT_AVAILABLE = False
    logger.warning("stftpitchshift not found, streaming pitch shifting is disabled. To enable, run: pip install stftpitchshift")

def pcm_bytes_to_numpy(pcm_bytes: bytes) -> np.ndarray:
    """Converts PCM audio bytes (expected int16) to a numpy array."""
    try:
        audio_array = np.frombuffer(pcm_bytes, dtype=np.int16)
        return audio_array
    except Exception as e:
        logger.error(f"Error converting PCM bytes to numpy array: {e}")
        return np.array([], dtype=np.int16)

def pitch_shift_audio(audio_array: np.ndarray, n_steps: float, sample_rate: int = AudioBaseConfig.SAMPLE_RATE) -> np.ndarray:
    """
    Shifts the pitch of an audio array.
    This is a blocking, memory-intensive operation.
    """
    if not PYRUBBERBAND_AVAILABLE:
        logger.warning("pyrubberband not installed. Cannot pitch shift.")
        return audio_array
    if n_steps == 0.0:
        return audio_array

    if audio_array.size == 0:
        return audio_array

    logger.info(f"Applying pitch shift of {n_steps} semitones.")
    pitch_shifted_array = pyrb.pitch_shift(
        y=audio_array,
        sr=sample_rate,
        n_steps=n_steps
    )
    return pitch_shifted_array.astype(np.int16)

class StreamingPitchShifter:
    """A wrapper for stftpitchshift to handle streaming audio data."""
    def __init__(self, pitch_factor: float, sample_rate: int = AudioBaseConfig.SAMPLE_RATE, chunk_size: int = AudioBaseConfig.CHUNK_SIZE):
        if not STFTPITCHSHIFT_AVAILABLE:
            raise ImportError("stftpitchshift library not found.")
            
        self.pitch_factor = pitch_factor
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        
        # stftpitchshift expects float32 input
        self.pitchshifter = StftPitchShift(
            framesize=chunk_size,
            hopsize=chunk_size // 4, # A common overlap for STFT
            samplerate=sample_rate
        )
        self._input_buffer = np.array([], dtype=np.float32)

    def process_chunk(self, audio_chunk: np.ndarray) -> np.ndarray:
        """
        Process a chunk of audio, returning the pitch-shifted chunk.
        Handles internal buffering to ensure continuous processing.
        Args:
            audio_chunk (np.ndarray): Input audio chunk (int16).
        Returns:
            np.ndarray: Pitch-shifted audio chunk (int16).
        """
        if audio_chunk.dtype != np.int16:
            raise ValueError("Input audio chunk must be of type np.int16")

        # Convert to float32 for processing
        audio_chunk_float = audio_chunk.astype(np.float32) / 32768.0
        
        # Perform pitch shifting
        shifted_chunk_float = self.pitchshifter.shiftpitch(
            audio_chunk_float, 
            factors=self.pitch_factor,
            normalize=True
        )
        
        # Convert back to int16
        shifted_chunk_int16 = (shifted_chunk_float * 32767).astype(np.int16)
        
        return shifted_chunk_int16

    def clear(self):
        """Clear the internal buffer."""
        self._input_buffer = np.array([], dtype=np.float32) 