import sys
import os
import logging
import numpy as np
import time
import threading
from pathlib import Path

# Add the parent directory to the Python path so we can import our modules
sys.path.append(str(Path(__file__).parent.parent))

# Import our optimized audio manager
from managers.optimized_audio_manager import OptimizedAudioManager, AudioConfig

# Configure logging
logging.basicConfig(
    level=logging.INFO,  # INFO level
    format='%(asctime)s - [%(filename)s.%(funcName)s:%(lineno)d] - %(levelname)s - %(message)s'
)

# Test audio consumer for receiving audio
class TestAudioConsumer:
    def __init__(self):
        self.received_chunks = 0
        self.last_audio_level = 0
        self.lock = threading.Lock()
        
    def process_audio(self, audio_data):
        with self.lock:
            self.received_chunks += 1
            # Calculate audio level (simple RMS)
            if len(audio_data) > 0:
                self.last_audio_level = np.sqrt(np.mean(audio_data.astype(np.float32)**2))
            
            # Log periodically
            if self.received_chunks % 100 == 0:
                logging.info(f"Received {self.received_chunks} chunks, last level: {self.last_audio_level:.6f}")

def list_audio_devices():
    """List all available audio devices with more details"""
    logging.info("=== AUDIO DEVICE DETAILS ===")
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        for i, dev in enumerate(devices):
            logging.info(f"Device {i}: {dev['name']}")
            logging.info(f"  - Input channels: {dev['max_input_channels']}")
            logging.info(f"  - Output channels: {dev['max_output_channels']}")
            logging.info(f"  - Default sample rate: {dev['default_samplerate']}")
            if i == sd.default.device[0]:
                logging.info(f"  - DEFAULT INPUT DEVICE")
            if i == sd.default.device[1]:
                logging.info(f"  - DEFAULT OUTPUT DEVICE")
            logging.info("---")
        
        logging.info(f"Default input device: {sd.default.device[0]}")
        logging.info(f"Default output device: {sd.default.device[1]}")
    except Exception as e:
        logging.error(f"Error listing devices: {e}")
    logging.info("=============================")

def generate_stereo_beep(frequency, duration, sample_rate):
    """Generate a stereo beep sound with a clear left-right panning effect"""
    t = np.linspace(0, duration, int(sample_rate * duration), False)
    
    # Add a slight panning effect (left to right)
    left_volume = 0.8 - 0.6 * (t / duration)
    right_volume = 0.2 + 0.6 * (t / duration)
    
    # Generate base tone at full volume - EXTRA LOUD for testing
    sine_wave = np.sin(2 * np.pi * frequency * t) * 32767 * 0.95  # 95% of max volume
    
    # Create stereo by applying panning volumes
    left_channel = (sine_wave * left_volume).astype(np.int16)
    right_channel = (sine_wave * right_volume).astype(np.int16)
    
    # Interleave left and right channels
    stereo_data = np.empty(len(sine_wave) * 2, dtype=np.int16)
    stereo_data[0::2] = left_channel  # Left channel
    stereo_data[1::2] = right_channel  # Right channel
    
    logging.info(f"Generated stereo beep: {len(stereo_data)/2} samples, {sample_rate}Hz, shaped as {stereo_data.shape}")
    return stereo_data

def test_all_audio_features():
    """Comprehensive test of all audio features"""
    print("\n" + "=" * 80)
    print(" TESTING OPTIMIZED AUDIO MANAGER ".center(80, "="))
    print("=" * 80 + "\n")
    
    # First list all available devices
    list_audio_devices()
    
    # Generate test tones with the default system sample rate
    sample_rate = 48000       # Match default device sample rate
    short_beep_duration = 0.3 # seconds
    long_beep_duration = 1.0  # seconds
    
    # Create different tones
    high_freq = 880.0   # Higher frequency (A5 note)
    mid_freq = 440.0    # Medium frequency (A4 note)
    low_freq = 220.0    # Lower frequency (A3 note)
    
    # Generate our test tones
    high_tone = generate_stereo_beep(high_freq, short_beep_duration, sample_rate)
    mid_tone = generate_stereo_beep(mid_freq, short_beep_duration, sample_rate)
    low_tone = generate_stereo_beep(low_freq, long_beep_duration, sample_rate)
    
    try:
        # Create the configuration with stereo output
        config = AudioConfig(
            output_channels=2,      # Use stereo output
            rate=sample_rate,       # Match system sample rate
            chunk=1024,             # Standard chunk size
            input_device_index=None # No input - output only mode
        )
        
        print("\nInitializing AudioManager...")
        audio_manager = OptimizedAudioManager.get_instance(config)
        
        # Force clear any existing producers in case of previous tests
        with audio_manager._producers_lock:
            audio_manager._producers.clear()
            
        # IMPORTANT: Register producers *before* starting the AudioManager
        # This is crucial for the AudioManager to initialize correctly
        audio_manager.add_producer("high_tone")
        audio_manager.add_producer("mid_tone")
        audio_manager.add_producer("low_tone")
        audio_manager.add_producer("loop_tone")
        
        print("\nStarting AudioManager...")
        audio_manager.start()
        
        # Wait briefly to ensure the stream is fully started
        time.sleep(0.5)
        
        # Test 1: Simple sound playback
        print("\nTEST 1: Playing high-pitched beep...")
        audio_manager.play_audio(high_tone, producer_name="high_tone")
        time.sleep(short_beep_duration + 0.2)
        
        # Test 2: Multiple sounds in sequence
        print("\nTEST 2: Playing sequence of tones (high, mid, low)...")
        audio_manager.play_audio(high_tone, producer_name="high_tone")
        time.sleep(short_beep_duration + 0.1)
        audio_manager.play_audio(mid_tone, producer_name="mid_tone")
        time.sleep(short_beep_duration + 0.1)
        audio_manager.play_audio(low_tone, producer_name="low_tone")
        time.sleep(long_beep_duration + 0.2)
        
        # Test 3: Volume control
        print("\nTEST 3: Testing volume control (same tone at different volumes)...")
        # Full volume
        audio_manager.set_producer_volume("high_tone", 1.0)
        audio_manager.play_audio(high_tone, producer_name="high_tone")
        time.sleep(short_beep_duration + 0.2)
        
        # Half volume
        audio_manager.set_producer_volume("high_tone", 0.5)
        audio_manager.play_audio(high_tone, producer_name="high_tone")
        time.sleep(short_beep_duration + 0.2)
        
        # Quarter volume
        audio_manager.set_producer_volume("high_tone", 0.25)
        audio_manager.play_audio(high_tone, producer_name="high_tone")
        time.sleep(short_beep_duration + 0.2)
        
        # Reset volume to full
        audio_manager.set_producer_volume("high_tone", 1.0)
        
        # Test 4: Looping audio
        print("\nTEST 4: Testing looping audio (will loop for 3 seconds)...")
        audio_manager.play_audio(mid_tone, producer_name="loop_tone", loop=True)
        
        # Let it loop a few times
        time.sleep(3.0)
        
        # Stop the looping audio
        print("\nStopping looped audio...")
        with audio_manager._producers_lock:
            if "loop_tone" in audio_manager._producers:
                producer = audio_manager._producers["loop_tone"]
                producer.loop = False
                producer._original_audio = None
                producer.buffer.clear()
                
        # Test 5: Simultaneous sounds
        print("\nTEST 5: Testing simultaneous sounds (will play high and low tones together)...")
        audio_manager.play_audio(high_tone, producer_name="high_tone")
        audio_manager.play_audio(low_tone, producer_name="low_tone")
        time.sleep(long_beep_duration + 0.2)
        
        print("\nAll tests complete!")
            
    except Exception as e:
        logging.error(f"Error in audio tests: {e}", exc_info=True)
        
    finally:
        # Stop the audio manager if it was started
        if 'audio_manager' in locals() and hasattr(audio_manager, '_running') and audio_manager._running:
            print("\nStopping audio manager...")
            audio_manager.stop()
            
    print("\n" + "=" * 80)
    print(" END OF TESTS ".center(80, "="))
    print("=" * 80 + "\n")

if __name__ == "__main__":
    test_all_audio_features() 