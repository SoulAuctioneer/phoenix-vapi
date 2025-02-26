import sys
import os
import logging
import numpy as np
import time
import threading
from pathlib import Path
import sounddevice as sd

# Add the parent directory to the Python path so we can import our modules
sys.path.append(str(Path(__file__).parent.parent))

# Import our optimized audio manager
from managers.optimized_audio_manager import OptimizedAudioManager, AudioConfig

# Configure logging with DEBUG level
logging.basicConfig(
    level=logging.DEBUG,  # Change to DEBUG for more detailed logs
    format='%(asctime)s - [%(filename)s.%(funcName)s:%(lineno)d] - %(levelname)s - %(message)s'
)

# Show audio configuration information
chunk_size = 1024  # Adjust this to match your desired chunk size
buffer_count = 5
print(f"Audio chunk duration: {chunk_size/48000*1000:.1f}ms, Buffer size: {buffer_count}, Likely latency: {chunk_size/48000*1000*buffer_count:.1f}ms")

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

def generate_stereo_beep(frequency, duration, sample_rate, volume=0.95):
    """Generate a stereo beep sound with a clear left-right panning effect"""
    t = np.linspace(0, duration, int(sample_rate * duration), False)
    
    # Add a slight panning effect (left to right)
    left_volume = 0.8 - 0.6 * (t / duration)
    right_volume = 0.2 + 0.6 * (t / duration)
    
    # Generate base tone at specified volume
    # SoundDevice expects float between -1 and 1
    sine_wave = np.sin(2 * np.pi * frequency * t) * volume
    
    # Create stereo by applying panning volumes
    left_channel = sine_wave * left_volume
    right_channel = sine_wave * right_volume
    
    # Create stereo data in [frames, channels] format for SoundDevice
    stereo_data = np.column_stack((left_channel, right_channel))
    
    logging.info(f"Generated stereo beep: {len(stereo_data)} frames at {sample_rate}Hz")
    return stereo_data

def enhanced_test():
    """Enhanced test with extra debugging for both direct SoundDevice and AudioManager"""
    print("\n" + "=" * 80)
    print(" ENHANCED AUDIO TEST WITH DEBUGGING ".center(80, "="))
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
    duration = 1.0  # seconds
    
    # Create tone
    high_freq = 880.0  # A5 note
    
    # Generate beep with VERY HIGH volume for testing
    high_beep = generate_stereo_beep(high_freq, duration, sample_rate, volume=0.95)
    
    # Log details about the generated audio
    logging.debug(f"Generated audio: shape={high_beep.shape}, dtype={high_beep.dtype}, min={np.min(high_beep):.4f}, max={np.max(high_beep):.4f}")
    
    try:
        print("\n=== PART 1: DIRECT SOUNDDEVICE TEST ===")
        print("Playing a high-pitched beep through direct SoundDevice...")
        
        # Play using default device
        sd.play(high_beep, sample_rate)
        sd.wait()  # Wait for playback to finish
        
        print("\nDid you hear the direct SoundDevice beep? (You should!)")
        time.sleep(0.5)
        
        print("\n=== PART 2: OPTIMIZED AUDIO MANAGER DEBUG TEST ===")
        
        # Create config matching device settings
        config = AudioConfig(
            output_channels=default_channels,
            rate=sample_rate,
            chunk=chunk_size  # Use the defined chunk size
        )
        
        print("\nInitializing AudioManager...")
        audio_manager = OptimizedAudioManager.get_instance(config)
        
        # Clear any existing producers
        with audio_manager._producers_lock:
            audio_manager._producers.clear()
        
        # Register producers BEFORE starting
        print("Registering producer 'high_tone'...")
        producer = audio_manager.add_producer("high_tone")
        
        print("\nStarting AudioManager...")
        audio_manager.start()
        
        # Wait for the stream to stabilize
        time.sleep(0.5)
        
        # Play the test sound
        print("\nPlaying HIGH VOLUME test tone through AudioManager...")
        logging.debug(f"Playing audio data: shape={high_beep.shape}, dtype={high_beep.dtype}, max={np.max(np.abs(high_beep)):.4f}")
        
        # Set max volume
        audio_manager.set_producer_volume("high_tone", 1.0)
        
        # Play and track time
        start_time = time.time()
        audio_manager.play_audio(high_beep, producer_name="high_tone")
        
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
    print(" END OF ENHANCED TEST ".center(80, "="))
    print("=" * 80 + "\n")

if __name__ == "__main__":
    enhanced_test() 