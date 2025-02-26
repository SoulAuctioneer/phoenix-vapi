#!/usr/bin/env python
"""
Line-by-line profiling of the AudioManager to identify CPU usage at the line level.
This requires the line_profiler package: pip install line_profiler
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
logger = logging.getLogger('line_profiling')

def generate_test_audio(duration_seconds=2):
    """Generate test audio data for profiling"""
    # Generate a simple sine wave at 440Hz
    samples = int(duration_seconds * AudioBaseConfig.SAMPLE_RATE)
    t = np.linspace(0, duration_seconds, samples, False)
    # Generate audio data (a 440Hz tone)
    return (np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16)

def line_profile_audio_manager(duration=10):
    """
    Line profile the AudioManager for a specified duration.
    
    Args:
        duration: How long to run the profiling in seconds
    """
    try:
        # Import line_profiler at runtime
        from line_profiler import LineProfiler
    except ImportError:
        logger.error("line_profiler not installed. Install with: pip install line_profiler")
        return
    
    logger.info(f"Starting AudioManager line profiling for {duration} seconds...")
    
    # Create and start the audio manager
    config = AudioConfig()
    audio_manager = AudioManager.get_instance(config)
    
    # Create a line profiler and add functions to profile
    lp = LineProfiler()
    
    # Add AudioManager methods that are likely to be CPU intensive
    lp.add_function(audio_manager._audio_callback)
    lp.add_function(audio_manager._process_input)
    lp.add_function(audio_manager._process_output)
    lp.add_function(audio_manager.play_audio)
    
    # Add methods from AudioProducer that might be intensive
    producer_class = audio_manager._producers.get("default", None).__class__ if audio_manager._producers else None
    if producer_class:
        lp.add_function(producer_class.get)
        lp.add_function(producer_class.put)
    
    # Wrap the entire process in the line profiler
    lp_wrapper = lp(run_audio_manager_test)
    lp_wrapper(audio_manager, duration)
    
    # Save the results to a file
    output_file = os.path.join(os.path.dirname(__file__), 'audio_line_profile_results.txt')
    with open(output_file, 'w') as f:
        lp.print_stats(stream=f)
        
    logger.info(f"Line profiling complete. Results saved to {output_file}")
    
    # Print a summary to the console
    logger.info("Line profiling summary:")
    lp.print_stats()

def run_audio_manager_test(audio_manager, duration):
    """Run audio manager with test data for profiling"""
    try:
        # Start the audio manager
        audio_manager.start()
        
        # Create test audio data
        test_audio = generate_test_audio(2)
        
        # Play some audio to ensure we're profiling both playback and recording
        start_time = time.time()
        while time.time() - start_time < duration:
            # Play audio every second
            if int(time.time() - start_time) % 2 == 0:
                audio_manager.play_audio(test_audio, producer_name="test_producer")
                
            # Play a sound effect occasionally
            if int(time.time() - start_time) % 3 == 0:
                audio_manager.play_sound("CHIRP1")
                
            # Sleep a bit to avoid hammering the CPU with just test code
            time.sleep(0.1)
    except KeyboardInterrupt:
        logger.info("Profiling interrupted by user")
    finally:
        # Stop the audio manager
        audio_manager.stop()

if __name__ == "__main__":
    # Get duration from command line if provided
    duration = 10
    if len(sys.argv) > 1:
        try:
            duration = int(sys.argv[1])
        except ValueError:
            logger.error(f"Invalid duration: {sys.argv[1]}. Using default of {duration} seconds.")
    
    line_profile_audio_manager(duration) 