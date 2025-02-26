import sys
import os
import logging
import numpy as np
import time
from pathlib import Path
import sounddevice as sd

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(filename)s.%(funcName)s:%(lineno)d] - %(levelname)s - %(message)s'
)

def list_audio_devices():
    """List all available audio devices with more details"""
    logging.info("=== AUDIO DEVICE DETAILS ===")
    try:
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

def generate_stereo_beep(frequency, duration, sample_rate, volume=0.9):
    """Generate a stereo beep sound with a clear left-right panning effect"""
    t = np.linspace(0, duration, int(sample_rate * duration), False)
    
    # Add a slight panning effect (left to right)
    left_volume = 0.8 - 0.6 * (t / duration)
    right_volume = 0.2 + 0.6 * (t / duration)
    
    # Generate base tone at specified volume
    # Note: SoundDevice expects float between -1 and 1, not int16
    sine_wave = np.sin(2 * np.pi * frequency * t) * volume
    
    # Create stereo by applying panning volumes
    left_channel = sine_wave * left_volume
    right_channel = sine_wave * right_volume
    
    # Create stereo data as [frames, channels] format
    stereo_data = np.column_stack((left_channel, right_channel))
    
    logging.info(f"Generated stereo beep: {len(stereo_data)} frames at {sample_rate}Hz")
    return stereo_data

def test_direct_audio_playback():
    """Test direct audio playback through SoundDevice"""
    print("\n" + "=" * 80)
    print(" TESTING DIRECT SOUNDDEVICE AUDIO PLAYBACK ".center(80, "="))
    print("=" * 80 + "\n")
    
    # First list all available devices
    list_audio_devices()
    
    # Get the default output device details
    device_info = sd.query_devices(sd.default.device[1])
    default_samplerate = int(device_info['default_samplerate'])
    default_channels = device_info['max_output_channels']
    
    logging.info(f"Default device sample rate: {default_samplerate}Hz, channels: {default_channels}")
    
    # Generate test tones using the device's default sample rate
    sample_rate = default_samplerate
    duration = 2.0  # seconds
    
    # Create different tones
    high_freq = 880.0  # Higher frequency (A5 note)
    
    # Generate a stereo beep (LOUD volume for testing)
    beep = generate_stereo_beep(high_freq, duration, sample_rate, volume=0.9)
    
    try:
        # Test 1: Direct playback through SoundDevice
        print("\nPlaying a 2-second beep at FULL volume through SoundDevice...")
        print("You should hear a stereo tone that pans from left to right...")
        
        # Play using default device
        sd.play(beep, sample_rate)
        
        # Wait for playback to finish
        sd.wait()
        
        print("\nDid you hear the beep? If yes, SoundDevice is working correctly.")
        print("If not, there may be an issue with your audio configuration.")
        
        # Test 2: Try with explicitly specified device
        output_device = sd.default.device[1]
        print(f"\nTrying again with explicit device {output_device}...")
        
        # Play with explicit device selection
        sd.play(beep, sample_rate, device=output_device)
        
        # Wait for playback to finish
        sd.wait()
        
        print("\nDid you hear the second beep? If yes, try the optimized AudioManager again.")
        
    except Exception as e:
        logging.error(f"Error in direct audio playback: {e}", exc_info=True)
    
    print("\n" + "=" * 80)
    print(" END OF TEST ".center(80, "="))
    print("=" * 80 + "\n")

if __name__ == "__main__":
    test_direct_audio_playback() 