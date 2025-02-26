#!/usr/bin/env python
"""
Memory profiling of the AudioManager to identify memory allocation patterns.
This script monitors memory usage during audio processing, which can help 
identify excessive memory allocations that might impact CPU performance.

This requires memory_profiler: pip install memory_profiler
"""
import os
import sys
import time
import logging
import numpy as np

# Add the src directory to the path so we can import modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from managers.audio_manager import AudioManager, AudioConfig
from config import AudioBaseConfig, SoundEffect

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(filename)s.%(funcName)s:%(lineno)d] - %(levelname)s - %(message)s'
)
logger = logging.getLogger('memory_profiling')

try:
    from memory_profiler import profile as memory_profile
except ImportError:
    logger.error("memory_profiler not installed. Install with: pip install memory_profiler")
    # Create a dummy decorator if memory_profiler is not available
    def memory_profile(func):
        return func

def generate_test_audio(duration_seconds=2):
    """Generate test audio data for profiling"""
    # Generate a simple sine wave at 440Hz
    samples = int(duration_seconds * AudioBaseConfig.SAMPLE_RATE)
    t = np.linspace(0, duration_seconds, samples, False)
    # Generate audio data (a 440Hz tone)
    return (np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16)

@memory_profile
def run_audio_test(duration=10):
    """
    Run audio manager with memory profiling
    
    Args:
        duration: How long to run the test in seconds
    """
    logger.info(f"Starting AudioManager memory profiling for {duration} seconds...")
    
    # Create and start the audio manager
    config = AudioConfig()
    audio_manager = AudioManager.get_instance(config)
    
    try:
        # Start the audio manager
        audio_manager.start()
        
        # Create test audio data (preallocate to avoid affecting memory measurements during the test)
        test_audio = generate_test_audio(2)
        
        # Prepare for monitoring memory
        start_time = time.time()
        memory_samples = []
        timestamps = []
        
        # Track memory usage over time
        logger.info("Starting memory sampling...")
        while time.time() - start_time < duration:
            # Play audio to exercise memory allocation paths
            if int(time.time() - start_time) % 2 == 0:
                audio_manager.play_audio(test_audio, producer_name="test_producer")
                
            # Play sound effects occasionally 
            if int(time.time() - start_time) % 3 == 0:
                audio_manager.play_sound("CHIRP1")
            
            # Sleep a bit to avoid hammering the CPU
            time.sleep(0.1)
            
    except KeyboardInterrupt:
        logger.info("Profiling interrupted by user")
    finally:
        # Stop the audio manager
        audio_manager.stop()
        
    logger.info("Memory profiling complete")
    
@memory_profile
def profile_audio_callbacks():
    """Profile memory allocations specifically in the audio callback functions"""
    # Create and start the audio manager
    config = AudioConfig()
    audio_manager = AudioManager.get_instance(config)
    
    # Create test data
    test_audio = generate_test_audio(2)
    
    # Memory profile the process_output function with simulated data
    frames = config.chunk
    outdata = np.zeros((frames, config.get_channels()), dtype=np.int16)
    
    # Add a test producer
    producer = audio_manager.add_producer("test_producer")
    for i in range(0, len(test_audio), frames):
        end = min(i + frames, len(test_audio))
        chunk = test_audio[i:end]
        if len(chunk) < frames:
            chunk = np.pad(chunk, (0, frames - len(chunk)), mode='constant')
        producer.put(chunk)
    
    # Profile the output processing function
    for _ in range(10):  # Process 10 frames
        audio_manager._process_output(outdata, frames)
    
    # Profile the input processing function with simulated data
    indata = np.zeros((frames, 1), dtype=np.int16)
    indata[:, 0] = test_audio[:frames]
    
    # Add a test consumer
    received_data = []
    audio_manager.add_consumer(lambda data: received_data.append(data))
    
    # Profile the input processing function
    for _ in range(10):  # Process 10 frames
        audio_manager._process_input(indata, frames)
    
    # Clean up
    audio_manager.remove_producer("test_producer")

def main():
    """Main function to run memory profiling"""
    try:
        # Import memory_profiler at runtime to check if it's available
        import memory_profiler
    except ImportError:
        logger.error("memory_profiler not installed. Install with: pip install memory_profiler")
        return
    
    # Get duration from command line if provided
    duration = 10
    if len(sys.argv) > 1:
        try:
            duration = int(sys.argv[1])
        except ValueError:
            logger.error(f"Invalid duration: {sys.argv[1]}. Using default of {duration} seconds.")
    
    # Run full audio test with memory profiling
    logger.info("Running full audio test with memory profiling...")
    run_audio_test(duration)
    
    # Profile specific audio callbacks
    logger.info("Profiling specific audio callbacks...")
    profile_audio_callbacks()
    
    logger.info("Memory profiling complete. Check the output for memory usage information.")
    logger.info("To generate a more detailed memory profile, run with: mprof run memory_profile_audio.py")
    logger.info("Then visualize with: mprof plot")

if __name__ == "__main__":
    main() 