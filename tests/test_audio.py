import sys
import os
import logging
import numpy as np
import time
import threading
from pathlib import Path

# Add the parent directory to the Python path so we can import our modules
sys.path.append(str(Path(__file__).parent.parent))

# Import our audio manager
from managers.audio_manager import AudioManager, AudioConfig

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(filename)s.%(funcName)s:%(lineno)d] - %(levelname)s - %(message)s'
)

def list_audio_devices():
    """List all available audio devices with details"""
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

def generate_stereo_beep(frequency, duration, sample_rate, volume=0.95):
    """Generate a stereo beep sound with a clear left-right panning effect"""
    t = np.linspace(0, duration, int(sample_rate * duration), False)
    
    # Add a slight panning effect (left to right)
    left_volume = 0.8 - 0.6 * (t / duration)
    right_volume = 0.2 + 0.6 * (t / duration)
    
    # Generate base tone at specified volume
    sine_wave = np.sin(2 * np.pi * frequency * t) * volume
    
    # Create stereo by applying panning volumes
    left_channel = sine_wave * left_volume
    right_channel = sine_wave * right_volume
    
    # Create stereo data in [frames, channels] format for SoundDevice
    stereo_data = np.column_stack((left_channel, right_channel))
    
    logging.info(f"Generated stereo beep: {len(stereo_data)} frames at {sample_rate}Hz")
    return stereo_data

def test_audio():
    """Test the AudioManager implementation"""
    print("\n" + "=" * 80)
    print(" AUDIO MANAGER TEST ".center(80, "="))
    print("=" * 80 + "\n")
    
    # First list all available devices
    list_audio_devices()
    
    # Get the default output device details
    import sounddevice as sd
    device_info = sd.query_devices(sd.default.device[1])
    default_samplerate = int(device_info['default_samplerate'])
    default_channels = device_info['max_output_channels']
    
    logging.info(f"Default device sample rate: {default_samplerate}Hz, channels: {default_channels}")
    
    # Generate test tones using the device's default sample rate
    sample_rate = default_samplerate
    duration = 1.0  # seconds
    
    # Create tone
    high_freq = 880.0  # A5 note
    
    # Generate beep with high volume for testing
    high_beep = generate_stereo_beep(high_freq, duration, sample_rate, volume=0.95)
    
    try:
        # Create config matching device settings
        config = AudioConfig(
            channels=default_channels,
            chunk=1024  # Use a standard chunk size
        )
        
        print("\nInitializing AudioManager...")
        audio_manager = AudioManager.get_instance(config)
        
        # Clear any existing producers
        with audio_manager._producers_lock:
            audio_manager._producers.clear()
        
        # Register a producer
        print("Registering producer 'test_tone'...")
        producer = audio_manager.add_producer("test_tone")
        
        print("\nStarting AudioManager...")
        audio_manager.start()
        
        # Wait for the stream to stabilize
        time.sleep(0.5)
        
        # Play the test sound
        print("\nPlaying test tone through AudioManager...")
        logging.debug(f"Playing audio data: shape={high_beep.shape}, dtype={high_beep.dtype}, max={np.max(np.abs(high_beep)):.4f}")
        
        # Extract first channel for mono processing
        if high_beep.ndim == 2 and high_beep.shape[1] > 1:
            # Extract left channel only (our simplified implementation expects mono)
            mono_beep = high_beep[:, 0]
            logging.debug(f"Extracted mono from stereo data: {len(mono_beep)} samples")
        else:
            mono_beep = high_beep
        
        # Set max volume
        audio_manager.set_producer_volume("test_tone", 1.0)
        
        # Play and track time
        start_time = time.time()
        audio_manager.play_audio(mono_beep, producer_name="test_tone")
        
        # Wait for duration
        time.sleep(duration * 1.5)
        end_time = time.time()
        
        print(f"\nPlayback took approximately {end_time - start_time:.2f} seconds")
        print("You should have heard a beep through the AudioManager!")
        
        # Give time for any remaining audio to play
        time.sleep(0.5)
        
    except Exception as e:
        logging.error(f"Error in audio tests: {e}", exc_info=True)
        
    finally:
        # Stop the audio manager if it exists and is running
        if 'audio_manager' in locals() and hasattr(audio_manager, '_running') and audio_manager._running:
            print("\nStopping AudioManager...")
            audio_manager.stop()
            
    print("\n" + "=" * 80)
    print(" END OF TEST ".center(80, "="))
    print("=" * 80 + "\n")

if __name__ == "__main__":
    test_audio() 