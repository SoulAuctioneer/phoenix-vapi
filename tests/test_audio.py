import numpy as np
import time
import sys
from pathlib import Path

# Add the project root to Python path
project_root = str(Path(__file__).parent.parent)
if project_root not in sys.path:
    sys.path.append(project_root)

from src.managers.audio_manager import AudioManager, AudioConfig
from src.config import AudioBaseConfig

class AudioTest:
    """Base class for audio tests with proper setup/teardown"""
    def setup(self):
        self.audio_manager = AudioManager.get_instance()
        self.audio_manager.start()
        
    def teardown(self):
        if self.audio_manager:
            self.audio_manager.stop()
            AudioManager._instance = None  # Reset singleton for next test

def test_basic_audio_playback():
    """Test basic audio playback functionality"""
    test = AudioTest()
    test.setup()
    
    try:
        # Create a simple sine wave
        duration = 2.0  # seconds
        frequency = 440.0  # Hz (A4 note)
        sample_rate = AudioBaseConfig.SAMPLE_RATE
        t = np.linspace(0, duration, int(sample_rate * duration))
        audio_data = np.sin(2 * np.pi * frequency * t)
        
        # Play the sine wave
        print("Playing sine wave...")
        test.audio_manager.play_audio(audio_data, "test_sine")
        time.sleep(duration + 0.5)  # Wait for playback to complete
        
    finally:
        test.teardown()

def test_sound_effect_playback():
    """Test sound effect playback functionality"""
    test = AudioTest()
    test.setup()
    
    try:
        # Play a test sound effect
        print("Playing sound effect...")
        success = test.audio_manager.play_sound("tada")
        assert success, "Failed to play sound effect"
        time.sleep(2.0)  # Wait for sound effect to complete
        
    finally:
        test.teardown()

def test_multiple_producers():
    """Test multiple audio producers playing simultaneously"""
    test = AudioTest()
    test.setup()
    
    try:
        # Create two different sine waves
        duration = 2.0
        sample_rate = AudioBaseConfig.SAMPLE_RATE
        t = np.linspace(0, duration, int(sample_rate * duration))
        
        # 440 Hz sine wave (A4 note)
        audio1 = np.sin(2 * np.pi * 440 * t)
        # 554.37 Hz sine wave (C#5 note - creating a major third interval)
        audio2 = np.sin(2 * np.pi * 554.37 * t)
        
        # Play both sine waves simultaneously
        print("Playing two sine waves simultaneously...")
        test.audio_manager.play_audio(audio1, "sine1")
        test.audio_manager.play_audio(audio2, "sine2")
        time.sleep(duration + 0.5)
        
    finally:
        test.teardown()

def test_volume_control():
    """Test volume control functionality"""
    test = AudioTest()
    test.setup()
    
    try:
        # Create a sine wave
        duration = 2.0
        frequency = 440.0
        sample_rate = AudioBaseConfig.SAMPLE_RATE
        t = np.linspace(0, duration, int(sample_rate * duration))
        audio_data = np.sin(2 * np.pi * frequency * t)
        
        producer_name = "volume_test"
        
        print("Playing at full volume...")
        test.audio_manager.play_audio(audio_data, producer_name)
        time.sleep(duration + 0.5)
        
        print("Playing at half volume...")
        test.audio_manager.set_producer_volume(producer_name, 0.5)
        test.audio_manager.play_audio(audio_data, producer_name)
        time.sleep(duration + 0.5)
        
    finally:
        test.teardown()

if __name__ == "__main__":
    # Run tests manually
    print("Testing basic audio playback...")
    test_basic_audio_playback()
    
    print("\nTesting sound effect playback...")
    test_sound_effect_playback()
    
    print("\nTesting multiple producers...")
    test_multiple_producers()
    
    print("\nTesting volume control...")
    test_volume_control()
    
    print("\nAll tests completed!") 