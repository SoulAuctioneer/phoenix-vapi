#!/usr/bin/env python
"""
Script to monitor the main Phoenix application using py-spy for CPU sampling profiling.
This allows for low-overhead sampling of a running application.

Usage:
1. Install py-spy: pip install py-spy
2. Start the main Phoenix application: python src/main.py
3. Run this script: python src/profiling/pyspy_monitor.py

This will generate a flamegraph showing where CPU time is being spent.
"""
import os
import sys
import subprocess
import time
import logging
import argparse
import psutil

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(filename)s.%(funcName)s:%(lineno)d] - %(levelname)s - %(message)s'
)
logger = logging.getLogger('pyspy_monitor')

def find_phoenix_pid():
    """Find the PID of the running Phoenix main.py process"""
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = proc.info['cmdline']
            if cmdline and len(cmdline) > 1 and 'python' in cmdline[0] and 'main.py' in cmdline[1]:
                logger.info(f"Found Phoenix process: PID {proc.info['pid']}")
                return proc.info['pid']
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return None

def run_pyspy(pid, duration=60, output_file=None, format='flamegraph'):
    """
    Run py-spy on the specified process
    
    Args:
        pid: Process ID to monitor
        duration: Duration in seconds to sample
        output_file: Output file path (defaults to audio_profile_flame.svg in profiling dir)
        format: Output format (flamegraph, speedscope, raw)
    """
    if not output_file:
        output_file = os.path.join(os.path.dirname(__file__), f'audio_profile_{format}.svg')
        
    logger.info(f"Starting py-spy sampling on PID {pid} for {duration} seconds...")
    
    # Build the py-spy command
    # Adding --native flag to avoid Python version detection issues in virtual environments
    cmd = [
        'py-spy', 'record',
        '--pid', str(pid),
        '--duration', str(duration),
        '--format', format,
        '--output', output_file,
        '--native'  # Added native flag to work around Python version detection issues
    ]
    
    try:
        # Run py-spy with elevated privileges if needed
        subprocess.run(cmd, check=True)
        logger.info(f"Profiling complete. Results saved to {output_file}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Error running py-spy: {e}")
    except FileNotFoundError:
        logger.error("py-spy not found. Install with: pip install py-spy")

def main():
    """Main function to run py-spy monitoring"""
    parser = argparse.ArgumentParser(description='Monitor Phoenix application CPU usage with py-spy')
    parser.add_argument('--pid', type=int, help='PID of the Phoenix process (if not specified, will try to detect)')
    parser.add_argument('--duration', type=int, default=60, help='Duration in seconds to sample (default: 60)')
    parser.add_argument('--output', type=str, help='Output file path')
    parser.add_argument('--format', type=str, default='flamegraph', 
                       choices=['flamegraph', 'speedscope', 'raw'],
                       help='Output format (default: flamegraph)')
    
    args = parser.parse_args()
    
    # If PID not specified, try to find it
    pid = args.pid
    if not pid:
        pid = find_phoenix_pid()
        if not pid:
            logger.error("Could not find Phoenix process. Please start src/main.py first, or specify --pid")
            sys.exit(1)
    
    # Run py-spy
    run_pyspy(pid, args.duration, args.output, args.format)

if __name__ == "__main__":
    main() 