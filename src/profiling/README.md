# Audio Manager Profiling Tools

This directory contains tools for profiling the AudioManager to determine CPU usage and identify bottlenecks.

## Installation

Install the required dependencies:

```bash
make install_deps
```

This will install:
- `line_profiler` - For line-by-line profiling
- `py-spy` - For sampling profiling of running processes
- `psutil` - For process management
- `snakeviz` - For visualizing cProfile results
- `memory_profiler` - For monitoring memory usage

## Available Profiling Tools

### 1. cProfile Profiling

Uses Python's built-in cProfile to provide function-level profiling:

```bash
make cprofile DURATION=30
```

This will:
- Run the AudioManager for 30 seconds (adjustable)
- Generate a text report of function calls sorted by cumulative time
- Save detailed results to `audio_profile_results.txt`
- Save profiling data to `audio_profile.prof` for visualization

To visualize the results with snakeviz:

```bash
make visualize_cprofile
```

### 2. Line-by-Line Profiling

Uses line_profiler to provide detailed line-level profiling of specific functions:

```bash
make line_profile DURATION=30
```

This profiles:
- `_audio_callback`, `_process_input`, `_process_output` and `play_audio` methods
- AudioProducer's `get` and `put` methods
- Results are saved to `audio_line_profile_results.txt`

### 3. py-spy Sampling Profiler

Attaches to a running instance of the Phoenix application (main.py) to generate a flamegraph showing CPU usage:

```bash
# Start the main application in a separate terminal
python src/main.py

# Then run py-spy profiling
make pyspy DURATION=60
```

You can also specify a PID if auto-detection doesn't work:
```bash
make pyspy DURATION=60 PID=12345
```

This will generate an SVG flamegraph in `audio_profile_flamegraph.svg`.

### 4. Memory Profiling

Monitors memory usage during AudioManager operation to identify potential memory allocation issues:

```bash
make memory_profile DURATION=30
```

This will:
- Profile memory usage in the AudioManager during normal operation
- Specifically profile memory allocations in the audio callback functions

For continuous memory tracking over time:

```bash
make track_memory DURATION=30
```

This will:
- Track memory usage over time with higher resolution
- Generate a plot of memory usage in `memory_usage_plot.png`

## Interpreting the Results

When analyzing profiling results, look for:

1. **Hot spots** - Functions or lines with high cumulative time
2. **Frequent calls** - Functions called a very high number of times
3. **Lock contention** - Time spent acquiring/releasing locks
4. **I/O operations** - Audio callbacks that may be blocking
5. **Memory allocations** - Frequent memory allocations in audio callbacks

Common CPU bottlenecks in audio processing include:
- Excessive buffer copying
- Lock contention in audio callbacks
- Audio format conversions
- Floating point operations on audio data
- Frequent memory allocations in real-time code paths

## Optimization Strategies

After identifying bottlenecks, consider:

1. **Reduce memory copying** - Minimize numpy array copying and use views where possible
2. **Optimize locks** - Use finer-grained locks or lock-free algorithms
3. **Pre-compute** data where possible rather than calculating it in the audio callback
4. **Batch processing** - Process larger chunks of audio at once
5. **Avoid allocations** in audio callbacks - Preallocate buffers
6. **C extensions** for critical paths - Consider Cython or Numba for hotspots
7. **Object pooling** - Reuse objects instead of creating new ones
8. **Buffer recycling** - Maintain a pool of pre-allocated buffers for audio data 