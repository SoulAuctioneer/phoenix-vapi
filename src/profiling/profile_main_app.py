#!/usr/bin/env python
"""
Profile the entire Phoenix application (including the AudioManager and all services).
This script wraps the main application with cProfile to identify overall CPU usage.
"""
import os
import sys
import cProfile
import pstats
import io
import logging
import argparse
import importlib.util

# Add the src directory to the path so we can import modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(filename)s.%(funcName)s:%(lineno)d] - %(levelname)s - %(message)s'
)
logger = logging.getLogger('main_profiling')

def profile_main_app(duration=60):
    """
    Profile the main application for a specified duration.
    
    Args:
        duration: How long to run the profiling in seconds
    """
    logger.info(f"Starting Phoenix main application profiling for {duration} seconds...")
    
    # Create a profiler
    pr = cProfile.Profile()
    pr.enable()
    
    try:
        # Import main module
        spec = importlib.util.spec_from_file_location("main", 
                                                     os.path.abspath(os.path.join(os.path.dirname(__file__), '../main.py')))
        main_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(main_module)
        
        # Set a timeout for the main application
        import asyncio
        from functools import partial
        
        async def run_with_timeout():
            # Create a new event loop
            loop = asyncio.get_event_loop()
            
            # Run the main function with a timeout
            main_task = loop.create_task(main_module.main())
            
            try:
                # Wait for specified duration then cancel
                await asyncio.sleep(duration)
                logger.info(f"Reached profiling duration of {duration} seconds, stopping application...")
                main_task.cancel()
                try:
                    await main_task
                except asyncio.CancelledError:
                    pass
            finally:
                pr.disable()
                
                # Print profiling results sorted by cumulative time
                s = io.StringIO()
                ps = pstats.Stats(pr, stream=s).sort_stats('cumtime')
                ps.print_stats(30)  # Print top 30 functions
                logger.info(f"Profiling complete. Results:\n{s.getvalue()}")
                
                # Also save results to a file
                output_file = os.path.join(os.path.dirname(__file__), 'main_app_profile_results.txt')
                with open(output_file, 'w') as f:
                    ps = pstats.Stats(pr, stream=f).sort_stats('cumtime')
                    ps.print_stats()
                    
                logger.info(f"Detailed profiling results saved to {output_file}")
                
                # Save results that can be visualized with tools like SnakeViz
                profile_file = os.path.join(os.path.dirname(__file__), 'main_app_profile.prof')
                pr.dump_stats(profile_file)
                logger.info(f"Profile data for visualization saved to {profile_file}")
                logger.info("You can visualize this with: snakeviz main_app_profile.prof")
        
        # Run the async function
        asyncio.run(run_with_timeout())
            
    except KeyboardInterrupt:
        logger.info("Profiling interrupted by user")
        pr.disable()
        
        # Print profiling results
        s = io.StringIO()
        ps = pstats.Stats(pr, stream=s).sort_stats('cumtime')
        ps.print_stats(30)
        logger.info(f"Profiling complete. Results:\n{s.getvalue()}")
        
        # Save results to a file
        output_file = os.path.join(os.path.dirname(__file__), 'main_app_profile_results.txt')
        with open(output_file, 'w') as f:
            ps = pstats.Stats(pr, stream=f).sort_stats('cumtime')
            ps.print_stats()
        
        logger.info(f"Detailed profiling results saved to {output_file}")
    except Exception as e:
        logger.error(f"Error during profiling: {e}", exc_info=True)
        pr.disable()

def main():
    """Parse command line arguments and run the profiler"""
    parser = argparse.ArgumentParser(description='Profile the Phoenix main application')
    parser.add_argument('--duration', type=int, default=60, 
                       help='Duration in seconds to run profiling (default: 60)')
    
    args = parser.parse_args()
    profile_main_app(args.duration)

if __name__ == "__main__":
    main() 