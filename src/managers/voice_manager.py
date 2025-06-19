import logging
import numpy as np
# TODO: The import of elevenlabs.client is very slow, about 5-6 seconds! Find out why.
print("Importing elevenlabs.client. This is very slow...")
from elevenlabs.client import ElevenLabs, AsyncElevenLabs
print("Imported elevenlabs.client.")
from config import ElevenLabsConfig, AudioBaseConfig, get_filter_logger
from utils.audio_processing import pitch_shift_audio, pcm_bytes_to_numpy, PYRUBBERBAND_AVAILABLE

logger = get_filter_logger(__name__)
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

    async def generate_audio_stream(self, text: str, voice_id: str = None, model_id: str = None, stability: float = None, style: float = None, use_speaker_boost: bool = None, pitch: float = 0.0):
        """Generates audio stream from text using ElevenLabs API.

        Args:
            text: The text to convert to speech.
            voice_id: The specific voice ID to use (defaults to config).
            model_id: The specific model ID to use (defaults to config).
            stability: Voice stability. Higher values are more stable, lower are more expressive.
                       Value between 0.0 and 1.0. Defaults to None (api default).
            style: The style of the voice. A value between 0.0 and 1.0.
            use_speaker_boost: Whether to use speaker boost.
            pitch: Pitch shift in semitones. Can be positive or negative. Requires pyrubberband.

        Returns:
            An async iterator yielding audio chunks (bytes).
            Returns None if generation fails.
        """
        voice_id = voice_id or ElevenLabsConfig.DEFAULT_VOICE_ID
        model_id = model_id or ElevenLabsConfig.DEFAULT_MODEL_ID
        voice_settings = {}
        if stability is not None:
            voice_settings["stability"] = stability
        if style is not None:
            voice_settings["style"] = style
        if use_speaker_boost is not None:
            voice_settings["use_speaker_boost"] = use_speaker_boost

        if not self._async_client:
            logger.error("Async ElevenLabs client not initialized.")
            return None

        try:
            logger.info(f"Generating audio stream for text: '{text[:30]}...' using voice {voice_id}")
            
            stream_params = {
                "text": text,
                "voice_id": voice_id,
                "model_id": model_id,
                "output_format": ElevenLabsConfig.OUTPUT_FORMAT,
            }
            if voice_settings:
                stream_params["voice_settings"] = voice_settings

            audio_stream_generator = self._async_client.text_to_speech.stream(**stream_params)
            
            if pitch != 0.0 and PYRUBBERBAND_AVAILABLE:
                logger.info(f"Applying pitch shift of {pitch} semitones.")
                # Buffer the entire audio stream. This adds latency but is necessary for pitch shifting.
                audio_bytes = b"".join([chunk async for chunk in audio_stream_generator])
                
                # Convert to numpy array
                audio_array = pcm_bytes_to_numpy(audio_bytes)

                if audio_array.size == 0:
                    logger.warning("Received empty audio stream from ElevenLabs.")
                    async def empty_generator():
                        yield b''
                    return empty_generator()

                # Pitch shift
                pitch_shifted_array = pitch_shift_audio(
                    audio_array, 
                    pitch,
                    AudioBaseConfig.SAMPLE_RATE
                )

                # Convert back to bytes
                pitch_shifted_bytes = pitch_shifted_array.tobytes()
                
                # Create a new async generator for the pitch-shifted audio
                async def shifted_audio_generator():
                    # We can chunk it to simulate the original stream behavior
                    chunk_size = 4096 # A reasonable chunk size
                    for i in range(0, len(pitch_shifted_bytes), chunk_size):
                        yield pitch_shifted_bytes[i:i+chunk_size]

                logger.info("Audio stream generation with pitch shift started.")
                return shifted_audio_generator()
            else:
                if pitch != 0.0 and not PYRUBBERBAND_AVAILABLE:
                    logger.warning("Pitch shifting requested but pyrubberband is not installed. Ignoring pitch shift.")
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