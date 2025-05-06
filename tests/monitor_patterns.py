#!/usr/bin/env python3
"""
Simplified monitor for AccelerometerManager that displays only key information.

This script initializes the accelerometer hardware and displays the
detected simplified motion state, stability status, and most likely activity.
"""

import sys
import os
import time
import logging
import csv
from colorama import Fore, Style, init
from datetime import datetime
from math import sqrt

# Add src directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../src')))

from managers.accelerometer_manager import AccelerometerManager, SimplifiedState

# Initialize colorama
init()

# Configure minimal logging
logging.basicConfig(
    level=logging.INFO, # Changed from DEBUG to INFO for cleaner output
    format='%(levelname)s: %(message)s'
)

# Create logs directory if it doesn't exist
LOGS_DIR = "logs"
if not os.path.exists(LOGS_DIR):
    os.makedirs(LOGS_DIR)

def setup_csv_logger():
    """Setup CSV logging with headers for simplified state."""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = os.path.join(LOGS_DIR, f"accelerometer_simplified_{timestamp}.csv")

    # Define simplified CSV headers
    headers = [
        'timestamp', 'current_state', 'energy', 'accel_magnitude',
        'accel_x', 'accel_y', 'accel_z', 'gyro_magnitude',
        'gyro_x', 'gyro_y', 'gyro_z',
        'stability', 'activity', 'activity_confidence',
        'heading' # Added heading
        # Removed pattern/duration columns: 'patterns', 'free_fall_duration', 'throw_duration', 'last_patterns', 'last_pattern_time'
    ]

    # Create and open CSV file
    csvfile = open(filename, 'w', newline='')
    writer = csv.DictWriter(csvfile, fieldnames=headers)
    writer.writeheader()

    return csvfile, writer

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

    # Calculate confidence as percentage (handle potential non-numeric values)
    numeric_values = [v for k, v in activity_dict.items() if isinstance(v, (int, float)) and k != 'most_likely']
    total = sum(numeric_values) if numeric_values else 0

    if total > 0 and isinstance(confidence, (int, float)):
        confidence_pct = int((confidence / total) * 100)
        return f"{color}{most_likely} ({confidence_pct}%){Style.RESET_ALL}"
    else:
        return f"{color}{most_likely}{Style.RESET_ALL}"

def format_simplified_state(state_name):
    """Format simplified state name with color."""
    color_map = {
        'STATIONARY': Fore.GREEN,
        'HELD_STILL': Fore.MAGENTA,
        'FREE_FALL': Fore.CYAN,
        'IMPACT': Fore.RED + Style.BRIGHT,
        'SHAKE': Fore.YELLOW + Style.BRIGHT,
        'MOVING': Fore.WHITE,
        'UNKNOWN': Fore.WHITE + Style.DIM
    }
    color = color_map.get(state_name, Fore.WHITE)
    return f"{color}{state_name}{Style.RESET_ALL}"

def format_energy(energy):
    """Format energy value with color based on intensity."""
    # Choose color based on energy level
    if not isinstance(energy, (int, float)): energy = 0.0 # Handle None or invalid type
    if energy < 0.1:
        color = Fore.WHITE
    elif energy < 0.3:
        color = Fore.CYAN
    elif energy < 0.6:
        color = Fore.YELLOW
    else:
        color = Fore.RED

    return f"{color}{energy:.2f}{Style.RESET_ALL}"

def clear_line():
    """Clear the current line in the terminal."""
    print('\r' + ' ' * 120 + '\r', end='', flush=True) # Increased width slightly

def main():
    """Main function to run the monitor."""
    print("Initializing simplified accelerometer monitor...")
    manager = AccelerometerManager()

    if not manager.initialize():
        print("Failed to initialize accelerometer hardware!")
        return 1

    print("AccelerometerManager initialized successfully.")
    print("Monitoring for simplified motion states. Press Ctrl+C to exit.")
    print("-" * 80)

    # Setup CSV logging
    csvfile, csvwriter = setup_csv_logger()
    print(f"Logging data to {csvfile.name}")

    # Keep track of previous state to detect changes
    prev_current_state = None # Changed from prev_motion_state
    line_printed = False
    output_prefix = "" # Initialize prefix

    # CSV Batching
    csv_batch = []
    CSV_BATCH_SIZE = 100 # Write every 100 rows

    # Enable manager debug logging if needed
    # logging.getLogger('src.managers.accelerometer_manager').setLevel(logging.DEBUG)

    try:
        while True:
            # Read data
            data = manager.read_sensor_data()

            # Format timestamp (always get current time)
            timestamp_str = datetime.now().strftime('%H:%M:%S.%f')[:-3]

            # Extract relevant info
            # patterns = data.get('detected_patterns', []) # Removed patterns
            stability = data.get('stability', 'Unknown')
            activity = data.get('activity', {'most_likely': 'Unknown'})
            energy = data.get('energy', 0.0)
            # motion_state = manager.get_motion_state() # Old method
            current_state = manager.get_current_state() # Use new method and variable name
            heading = data.get('heading', 0.0)

            # Extract raw data for debugging
            accel = data.get('linear_acceleration', (0, 0, 0))
            gyro = data.get('gyro', (0, 0, 0))

            # Calculate magnitudes
            accel_magnitude = 0.0
            if isinstance(accel, tuple) and len(accel) == 3:
                try: # Add try-except for safety
                    accel_magnitude = sqrt(accel[0]**2 + accel[1]**2 + accel[2]**2)
                except TypeError:
                    accel_magnitude = 0.0

            gyro_magnitude = 0.0
            if isinstance(gyro, tuple) and len(gyro) == 3:
                 try: # Add try-except for safety
                     gyro_magnitude = sqrt(gyro[0]**2 + gyro[1]**2 + gyro[2]**2)
                 except TypeError:
                     gyro_magnitude = 0.0

            # Removed code accessing manager.free_fall_start_time, throw_in_progress, pattern_history etc.

            # Prepare row data for CSV
            row_data = {
                'timestamp': timestamp_str,
                'current_state': current_state, # Renamed column
                'energy': f"{energy:.3f}" if isinstance(energy, (int, float)) else '0.000',
                'accel_magnitude': f"{accel_magnitude:.3f}",
                'accel_x': f"{accel[0]:.3f}" if isinstance(accel, tuple) and len(accel) > 0 else '0.000',
                'accel_y': f"{accel[1]:.3f}" if isinstance(accel, tuple) and len(accel) > 1 else '0.000',
                'accel_z': f"{accel[2]:.3f}" if isinstance(accel, tuple) and len(accel) > 2 else '0.000',
                'gyro_magnitude': f"{gyro_magnitude:.3f}",
                'gyro_x': f"{gyro[0]:.3f}" if isinstance(gyro, tuple) and len(gyro) > 0 else '0.000',
                'gyro_y': f"{gyro[1]:.3f}" if isinstance(gyro, tuple) and len(gyro) > 1 else '0.000',
                'gyro_z': f"{gyro[2]:.3f}" if isinstance(gyro, tuple) and len(gyro) > 2 else '0.000',
                'stability': stability,
                'activity': activity.get('most_likely', 'Unknown'),
                'activity_confidence': activity.get(activity.get('most_likely', 'Unknown'), 0),
                'heading': f"{heading:.2f}" if isinstance(heading, (int, float)) else '0.00'
                # Removed pattern/duration columns
            }

            # Add to CSV batch
            csv_batch.append(row_data)

            # Write batch if size reached
            if len(csv_batch) >= CSV_BATCH_SIZE:
                try:
                    csvwriter.writerows(csv_batch)
                    csv_batch = [] # Clear batch
                except Exception as e:
                    logging.error(f"Error writing CSV batch: {e}")

            # Check if state changed
            # patterns_changed = set(patterns) != set(prev_patterns) # Removed pattern check
            state_changed = current_state != prev_current_state

            # Start a new line ONLY if state changed
            if state_changed: # Simplified condition
                if line_printed:
                    print("")  # Start a new line before printing the updated state
                output_prefix = f"[{timestamp_str}] " # Update prefix ONLY when state changes
                line_printed = True

            # Removed pattern formatting logic
            # pattern_str = "None"
            # if patterns:
            #    pattern_str = ", ".join(format_pattern(p) for p in patterns)

            # Debug info based on state
            raw_accel_str = f"Ax:{accel[0]:.2f} Ay:{accel[1]:.2f} Az:{accel[2]:.2f}" if isinstance(accel, tuple) and len(accel) == 3 else "Ax:0.00 Ay:0.00 Az:0.00"
            debug_info = f"A:{accel_magnitude:.2f} {raw_accel_str} G:{gyro_magnitude:.2f}"

            # Removed state-specific debug info related to removed attributes

            # Construct the data part of the line (without the prefix)
            data_line = (
                # f"Pattern: {pattern_str} | " # Removed Pattern display
                f"State: {format_simplified_state(current_state)} | " # Changed formatting function
                f"Energy: {format_energy(energy)} | {debug_info} | "
                f"Stability: {format_stability(stability)} | "
                f"Activity: {format_activity(activity)}"
            )

            # Display the information: Overwrite current line unless state changed
            clear_line() # Clear line before printing
            print(f"{output_prefix}{data_line}", end='', flush=True)

            # Update previous state
            # prev_patterns = patterns.copy() if patterns else [] # Removed
            prev_current_state = current_state # Changed variable name

            # Wait a bit before next reading? No, read as fast as possible.
            # time.sleep(0.01)

    except KeyboardInterrupt:
        print("\nMonitoring stopped.")
    finally:
        # Write any remaining data in the batch before closing
        if csv_batch:
            try:
                csvwriter.writerows(csv_batch)
                logging.info(f"Wrote final {len(csv_batch)} records to CSV.")
            except Exception as e:
                logging.error(f"Error writing final CSV batch: {e}")

        if 'csvfile' in locals() and csvfile and not csvfile.closed: # Check if csvfile exists and is open
            csvfile.close()

        manager.deinitialize()
        print("\nAccelerometer hardware deinitialized.")

    return 0

if __name__ == "__main__":
    sys.exit(main()) 