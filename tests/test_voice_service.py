import os
import asyncio
import unittest
from unittest.mock import MagicMock, patch, AsyncMock # Keep AsyncMock for specific cases
import numpy as np

# Ensure the src directory is in the path for imports
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from services.voice_service import VoiceService
from services.service import ServiceManager
from managers.voice_manager import VoiceManager
from managers.audio_manager import AudioManager, AudioConfig
from config import AudioBaseConfig, ElevenLabsConfig
import queue # For checking queue.Empty

# Conditional skip for tests requiring API key
ELEVENLABS_API_KEY_AVAILABLE = bool(ElevenLabsConfig.API_KEY)

@unittest.skipIf(not ELEVENLABS_API_KEY_AVAILABLE, "ELEVENLABS_API_KEY not set, skipping integration test.")
class TestVoiceServiceIntegration(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.service_manager_mock = MagicMock(spec=ServiceManager)
        
        # --- AudioManager Setup ---
        # Stop any existing instance first to ensure a clean state for the test
        if AudioManager._instance:
            if AudioManager._instance.is_running:
                try:
                    AudioManager._instance.stop()
                    # Allow time for threads to join if stop is not fully synchronous
                    await asyncio.sleep(0.2) 
                except Exception as e:
                    print(f"Warning: Error stopping existing AudioManager instance: {e}")
            AudioManager._instance = None # Force re-creation

        self.audio_manager = AudioManager.get_instance(AudioConfig()) # Use default config
        try:
            self.audio_manager.start()
            if not self.audio_manager.is_running:
                # Additional check as start() might not raise but fail silently in some edge cases
                raise RuntimeError("AudioManager failed to confirm it is running after start() call.")
        except Exception as e:
            self.fail(f"AudioManager failed to start: {e}. This test requires a functional audio environment (e.g., PyAudio with PortAudio). Skipping further tests in this class might be preferable if this setup fails consistently.")

        # --- Instantiate VoiceService ---
        self.voice_service = VoiceService(self.service_manager_mock)

    async def asyncTearDown(self):
        if self.voice_service and hasattr(self.voice_service, 'stop') and asyncio.iscoroutinefunction(self.voice_service.stop):
            await self.voice_service.stop()
        
        if self.audio_manager:
            if self.audio_manager.is_running:
                try:
                    self.audio_manager.stop()
                    await asyncio.sleep(0.2) # Allow time for cleanup
                except Exception as e:
                    print(f"Warning: Error stopping AudioManager during teardown: {e}")
            AudioManager._instance = None

    async def test_start_and_stop_service_integration(self):
        await self.voice_service.start()
        self.assertIsNotNone(self.voice_service.voice_manager)
        self.assertIsInstance(self.voice_service.voice_manager, VoiceManager)
        self.assertTrue(self.voice_service.audio_manager is self.audio_manager)
        
        self.assertIn(VoiceService.TTS_PRODUCER_NAME, self.audio_manager._producers)
        tts_producer = self.audio_manager._producers[VoiceService.TTS_PRODUCER_NAME]
        self.assertIsNotNone(tts_producer)
        self.assertTrue(tts_producer.active)

        await self.voice_service.stop()
        # VoiceService.stop() should remove the producer
        # Accessing _producers directly is for testing; consider if a getter is needed in AudioManager for prod scenarios
        self.assertNotIn(VoiceService.TTS_PRODUCER_NAME, self.audio_manager._producers) 
        self.assertIsNone(self.voice_service.voice_manager)

    async def test_speak_audio_event_hits_elevenlabs_and_queues_to_audiomanager(self):
        await self.voice_service.start()

        test_text = "Hello from the integration test using ElevenLabs."

        event = {
            "type": "speak_audio",
            "text": test_text,
        }

        await self.voice_service.handle_event(event)
        await asyncio.sleep(5) # Allow time for API call, streaming, and processing

        self.assertIn(VoiceService.TTS_PRODUCER_NAME, self.audio_manager._producers, "TTS producer not found in AudioManager.")
        tts_producer = self.audio_manager._producers[VoiceService.TTS_PRODUCER_NAME]
        
        data_was_queued = False
        queued_chunks_count = 0
        try:
            # Drain the queue to check what was put, assuming _output_loop might also be consuming
            while not tts_producer.buffer.buffer.empty():
                chunk = tts_producer.buffer.buffer.get_nowait()
                if chunk is not None and isinstance(chunk, np.ndarray) and chunk.size > 0:
                    data_was_queued = True
                    queued_chunks_count +=1
                tts_producer.buffer.buffer.task_done()
        except queue.Empty:
            pass # Expected if buffer becomes empty
        except Exception as e:
            self.fail(f"Error checking TTS producer queue: {e}")

        self.assertTrue(data_was_queued, "Audio data was not queued into the AudioManager's TTS producer buffer.")
        self.assertGreater(queued_chunks_count, 0, "Expected one or more audio chunks to be queued.")

    async def test_speak_audio_event_no_text(self):
        await self.voice_service.start()
        event = {"type": "speak_audio", "text": ""}
        
        # Temporarily mock generate_audio_stream on the actual voice_manager instance
        # to ensure no external API call is made for this specific test case.
        original_generate_audio_stream = self.voice_service.voice_manager.generate_audio_stream
        self.voice_service.voice_manager.generate_audio_stream = AsyncMock()
        
        with self.assertLogs(logger='services.voice_service', level='WARNING') as cm:
            await self.voice_service.handle_event(event)
        self.assertIn("'speak_audio' event received without 'text'", cm.output[0])
        self.voice_service.voice_manager.generate_audio_stream.assert_not_called()
        
        self.voice_service.voice_manager.generate_audio_stream = original_generate_audio_stream # Restore

    async def test_speak_audio_event_voice_manager_fails_to_initialize(self):
        # This test checks how VoiceService.start() handles VoiceManager init failure.
        # We patch VoiceManager at the class level for the scope of this test method.
        with patch('services.voice_service.VoiceManager', side_effect=ValueError("Test VoiceManager init failure")) as MockVoiceManagerClass_local:
            # Instantiate VoiceService within the patch context so its start() uses the failing mock
            vs_test_init_fail = VoiceService(self.service_manager_mock)
            with self.assertRaisesRegex(ValueError, "Test VoiceManager init failure"):
                await vs_test_init_fail.start()
            # Ensure the audio_manager set on vs_test_init_fail is the one we created (or None if start failed early)
            # This part depends on VoiceService's internal logic of when audio_manager is set.
            # Given current VoiceService.start(), audio_manager is set before VoiceManager instantiation.
            self.assertTrue(vs_test_init_fail.audio_manager is self.audio_manager)


if __name__ == '__main__':
    unittest.main() 