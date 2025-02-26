#!/usr/bin/env python
"""
Profile the AudioManager to identify CPU usage hotspots.
This script runs the AudioManager for a specified duration while profiling
all function calls to determine which parts of the code are most CPU intensive.
"""
import os
import sys
import time
import cProfile
import pstats
import io
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
logger = logging.getLogger('profiling')

def generate_test_audio(duration_seconds=2):
    """Generate test audio data for profiling"""
    # Generate a simple sine wave at 440Hz
    samples = int(duration_seconds * AudioBaseConfig.SAMPLE_RATE)
    t = np.linspace(0, duration_seconds, samples, False)
    # Generate audio data (a 440Hz tone)
    return (np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16)

def profile_audio_manager(duration=10):
    """
    Profile the AudioManager for a specified duration.
    
    Args:
        duration: How long to run the profiling in seconds
    """
    logger.info(f"Starting AudioManager profiling for {duration} seconds...")
    
    # Create and start the audio manager
    config = AudioConfig()
    audio_manager = AudioManager.get_instance(config)
    
    # Create a profiler
    pr = cProfile.Profile()
    pr.enable()
    
    # Start the audio manager
    audio_manager.start()
    
    # Create test audio data
    test_audio = generate_test_audio(2)
    
    # Play some audio to ensure we're profiling both playback and recording
    start_time = time.time()
    try:
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
        # Stop profiling
        pr.disable()
        
        # Stop the audio manager
        audio_manager.stop()
        
        # Print profiling results sorted by cumulative time
        s = io.StringIO()
        ps = pstats.Stats(pr, stream=s).sort_stats('cumtime')
        ps.print_stats(30)  # Print top 30 functions
        logger.info(f"Profiling complete. Results:\n{s.getvalue()}")
        
        # Also save results to a file
        output_file = os.path.join(os.path.dirname(__file__), 'audio_profile_results.txt')
        with open(output_file, 'w') as f:
            ps = pstats.Stats(pr, stream=f).sort_stats('cumtime')
            ps.print_stats()
            
        logger.info(f"Detailed profiling results saved to {output_file}")
        
        # Save results that can be visualized with tools like SnakeViz
        profile_file = os.path.join(os.path.dirname(__file__), 'audio_profile.prof')
        pr.dump_stats(profile_file)
        logger.info(f"Profile data for visualization saved to {profile_file}")
        logger.info("You can visualize this with: snakeviz audio_profile.prof")

if __name__ == "__main__":
    # Get duration from command line if provided
    duration = 10
    if len(sys.argv) > 1:
        try:
            duration = int(sys.argv[1])
        except ValueError:
            logger.error(f"Invalid duration: {sys.argv[1]}. Using default of {duration} seconds.")
    
    profile_audio_manager(duration) 