#!/usr/bin/env python
"""
Line-by-line profiling of the Phoenix main application including AudioManager and services.
This requires the line_profiler package: pip install line_profiler
"""
import os
import sys
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
logger = logging.getLogger('main_line_profiling')

def line_profile_main_app(duration=60):
    """
    Line profile the main application including AudioManager and all services.
    
    Args:
        duration: How long to run the profiling in seconds
    """
    try:
        # Import line_profiler at runtime
        from line_profiler import LineProfiler
    except ImportError:
        logger.error("line_profiler not installed. Install with: pip install line_profiler")
        return
    
    logger.info(f"Starting Phoenix main application line profiling for {duration} seconds...")
    
    try:
        # Import main module and other required modules
        spec = importlib.util.spec_from_file_location("main", 
                                                     os.path.abspath(os.path.join(os.path.dirname(__file__), '../main.py')))
        main_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(main_module)
        
        # Import audio manager module
        from managers.audio_manager import AudioManager
        
        # Import audio service
        from services.audio_service import AudioService
        
        # Create a line profiler and add functions to profile
        lp = LineProfiler()
        
        # Profile the main function
        lp.add_function(main_module.main)
        
        # Profile PhoenixApp methods
        lp.add_function(main_module.PhoenixApp.run)
        lp.add_function(main_module.PhoenixApp.initialize_services)
        
        # Profile AudioManager methods
        lp.add_function(AudioManager._audio_callback)
        lp.add_function(AudioManager._process_input)
        lp.add_function(AudioManager._process_output)
        lp.add_function(AudioManager.play_audio)
        
        # Profile AudioService methods
        lp.add_function(AudioService.handle_event)
        lp.add_function(AudioService._play_sound)
        
        # Profile ServiceManager
        from services.service import ServiceManager
        lp.add_function(ServiceManager.publish)
        
        # Create wrapper function to run with timeout
        import asyncio
        
        async def run_main_with_timeout():
            # Set up the main application
            app = main_module.PhoenixApp()
            
            # Create a task for the app.run method
            task = asyncio.create_task(app.run())
            
            try:
                # Run for the specified duration
                await asyncio.sleep(duration)
                logger.info(f"Reached profiling duration of {duration} seconds, stopping application...")
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            finally:
                # Save the profiling results
                output_file = os.path.join(os.path.dirname(__file__), 'main_app_line_profile_results.txt')
                with open(output_file, 'w') as f:
                    lp.print_stats(stream=f)
                
                logger.info(f"Line profiling complete. Results saved to {output_file}")
                
                # Print a summary to the console
                logger.info("Line profiling summary:")
                lp.print_stats()
                
        # Wrap the run function with the line profiler
        async def profiled_run():
            await run_main_with_timeout()
            
        # Run the profiled function
        lp_wrapper = lp(profiled_run)
        asyncio.run(lp_wrapper())
            
    except KeyboardInterrupt:
        logger.info("Profiling interrupted by user")
        # Results will be printed/saved by the finally block
    except Exception as e:
        logger.error(f"Error during line profiling: {e}", exc_info=True)

def main():
    """Parse command line arguments and run the line profiler"""
    parser = argparse.ArgumentParser(description='Line profile the Phoenix main application')
    parser.add_argument('--duration', type=int, default=60, 
                       help='Duration in seconds to run profiling (default: 60)')
    
    args = parser.parse_args()
    line_profile_main_app(args.duration)

if __name__ == "__main__":
    main() 