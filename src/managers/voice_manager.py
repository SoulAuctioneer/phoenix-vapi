import logging
import numpy as np
from elevenlabs.client import ElevenLabs, AsyncElevenLabs
from elevenlabs import stream as eleven_stream
from config import ElevenLabsConfig, AudioBaseConfig

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

class VoiceManager:
    """Manages interactions with the ElevenLabs API for TTS"""
    def __init__(self):
        if not ElevenLabsConfig.API_KEY:
            raise ValueError("ELEVENLABS_API_KEY not configured in environment variables or config.py")
            
        try:
            # Use synchronous client for initial setup/checks if needed,
            # but primarily use async client for generation.
            self._client = ElevenLabs(api_key=ElevenLabsConfig.API_KEY)
            self._async_client = AsyncElevenLabs(api_key=ElevenLabsConfig.API_KEY)
            logger.info("ElevenLabs clients initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize ElevenLabs client: {e}")
            raise

    async def generate_audio_stream(self, text: str, voice_id: str = None, model_id: str = None):
        """Generates audio stream from text using ElevenLabs API.

        Args:
            text: The text to convert to speech.
            voice_id: The specific voice ID to use (defaults to config).
            model_id: The specific model ID to use (defaults to config).

        Returns:
            An async iterator yielding audio chunks (bytes).
            Returns None if generation fails.
        """
        voice_id = voice_id or ElevenLabsConfig.DEFAULT_VOICE_ID
        model_id = model_id or ElevenLabsConfig.DEFAULT_MODEL_ID

        if not self._async_client:
            logger.error("Async ElevenLabs client not initialized.")
            return None

        try:
            logger.info(f"Generating audio stream for text: '{text[:30]}...' using voice {voice_id}")
            audio_stream_generator = self._async_client.text_to_speech.convert_as_stream(
                text=text,
                voice_id=voice_id,
                model_id=model_id,
                output_format=ElevenLabsConfig.OUTPUT_FORMAT
            )
            logger.info("Audio stream generation started.")
            return audio_stream_generator
        except Exception as e:
            logger.error(f"Error generating audio stream from ElevenLabs: {e}")
            return None

    def list_voices(self):
        """Lists available voices from ElevenLabs.

        Returns:
            A list of available voices or None if an error occurs.
        """
        if not self._client:
            logger.error("ElevenLabs client not initialized.")
            return None
        try:
            response = self._client.voices.get_all()
            return response.voices
        except Exception as e:
            logger.error(f"Error fetching voices from ElevenLabs: {e}")
            return None

    # Static method to convert PCM bytes to numpy array
    @staticmethod
    def pcm_bytes_to_numpy(pcm_bytes: bytes) -> np.ndarray:
        """Converts PCM audio bytes (expected int16) to a numpy array.

        Args:
            pcm_bytes: Raw PCM audio data as bytes.

        Returns:
            Numpy array of type int16.
        """
        try:
            # Assuming the PCM format is s16le (signed 16-bit little-endian)
            # which corresponds to np.int16
            audio_array = np.frombuffer(pcm_bytes, dtype=np.int16)
            return audio_array
        except Exception as e:
            logger.error(f"Error converting PCM bytes to numpy array: {e}")
            return np.array([], dtype=np.int16) # Return empty array on error 