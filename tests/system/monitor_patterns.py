#!/usr/bin/env python3
"""
Simplified monitor for AccelerometerManager that displays only key information.

This script initializes the accelerometer hardware and displays only the 
detected motion patterns, stability status, and most likely activity.
"""

import sys
import os
import time
import logging
from colorama import Fore, Style, init
from datetime import datetime

# Add src directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../src')))

from managers.accelerometer_manager import AccelerometerManager, MotionPattern

# Initialize colorama
init()

# Configure minimal logging
logging.basicConfig(
    level=logging.WARNING,  # Only show warnings and above
    format='%(levelname)s: %(message)s'
)

def format_pattern(pattern_name):
    """Format pattern name with color."""
    color_map = {
        'THROW': Fore.CYAN,
        'CATCH': Fore.GREEN,
        'ARC_SWING': Fore.YELLOW,
        'SHAKE': Fore.MAGENTA,
        'ROLLING': Fore.BLUE,
        'DROP': Fore.RED
    }
    color = color_map.get(pattern_name, Fore.WHITE)
    return f"{color}{pattern_name}{Style.RESET_ALL}"

def format_stability(stability):
    """Format stability with color."""
    color_map = {
        'On table': Fore.GREEN,
        'Stable': Fore.CYAN,
        'In motion': Fore.YELLOW,
        'Unknown': Fore.WHITE
    }
    color = color_map.get(stability, Fore.WHITE)
    return f"{color}{stability}{Style.RESET_ALL}"

def format_activity(activity_dict):
    """Format activity with color and confidence."""
    if not activity_dict or 'most_likely' not in activity_dict:
        return f"{Fore.WHITE}Unknown{Style.RESET_ALL}"
    
    most_likely = activity_dict['most_likely']
    confidence = activity_dict.get(most_likely, 0)
    
    # Choose color based on activity type
    color_map = {
        'Still': Fore.CYAN,
        'Walking': Fore.GREEN,
        'Running': Fore.YELLOW,
        'In-Vehicle': Fore.BLUE,
        'On-Bicycle': Fore.MAGENTA,
        'Tilting': Fore.RED,
    }
    color = color_map.get(most_likely, Fore.WHITE)
    
    # Calculate confidence as percentage
    total = sum(v for k, v in activity_dict.items() if isinstance(v, (int, float)) and k != 'most_likely')
    if total > 0:
        confidence_pct = int((confidence / total) * 100)
        return f"{color}{most_likely} ({confidence_pct}%){Style.RESET_ALL}"
    else:
        return f"{color}{most_likely}{Style.RESET_ALL}"

def clear_line():
    """Clear the current line in the terminal."""
    print('\r' + ' ' * 100 + '\r', end='', flush=True)

def main():
    """Main function to run the monitor."""
    print("Initializing accelerometer monitor...")
    manager = AccelerometerManager()
    
    if not manager.initialize():
        print("Failed to initialize accelerometer hardware!")
        return 1
    
    print("AccelerometerManager initialized successfully.")
    print("Monitoring for motion patterns. Press Ctrl+C to exit.")
    print("-" * 80)
    
    try:
        while True:
            # Read data
            data = manager.read_sensor_data()
            
            # Extract relevant info
            patterns = data.get('detected_patterns', [])
            stability = data.get('stability', 'Unknown')
            activity = data.get('activity', {'most_likely': 'Unknown'})
            
            # Format timestamp
            timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
            
            # Clear current line
            clear_line()
            
            # Format the patterns
            pattern_str = "None"
            if patterns:
                pattern_str = ", ".join(format_pattern(p) for p in patterns)
            
            # Display only the key information
            print(f"\r[{timestamp}] Pattern: {pattern_str} | Stability: {format_stability(stability)} | Activity: {format_activity(activity)}", end='', flush=True)
            
            # Wait a bit before next reading
            time.sleep(0.1)
            
    except KeyboardInterrupt:
        print("\nMonitoring stopped.")
    finally:
        manager.deinitialize()
        print("\nAccelerometer hardware deinitialized.")
    
    return 0

if __name__ == "__main__":
    sys.exit(main()) 