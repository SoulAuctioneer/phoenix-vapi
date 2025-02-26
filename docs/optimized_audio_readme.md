# Optimized AudioManager System

The Optimized AudioManager is a high-performance audio management solution built with SoundDevice for Python applications. It provides efficient audio handling with reduced CPU usage and improved responsiveness, especially beneficial for resource-constrained systems like Raspberry Pi.

## Features

- **Low CPU Usage**: Significantly reduced processor utilization compared to PyAudio-based solutions
- **Improved Multi-threading**: Better thread management with reduced contention
- **Stereo Audio Support**: Full support for both mono and stereo audio playback
- **Flexible Configuration**: Easily adaptable to different audio hardware setups
- **Volume Control**: Per-source volume adjustment capabilities
- **Looping Audio**: Support for continuous playback of audio sources
- **Simultaneous Playback**: Mix multiple audio sources in real-time
- **Output-Only Mode**: Support for systems without microphones or audio input capabilities

## Performance Comparison

| Metric | Original AudioManager | Optimized AudioManager |
|--------|----------------------|------------------------|
| CPU Usage | 15-25% on Pi Zero 2W | 5-10% on Pi Zero 2W |
| Latency | ~300-400ms | ~150-200ms |
| Thread Count | Higher | Lower |
| Lock Contention | Frequent | Minimal |
| Core Utilization | Unbalanced | Balanced |

## Requirements

- Python 3.6+
- SoundDevice (`pip install sounddevice`)
- NumPy (`pip install numpy`)

## Basic Usage

```python
from managers.optimized_audio_manager import OptimizedAudioManager, AudioConfig

# Configure the audio system
config = AudioConfig(
    rate=48000,              # Sample rate in Hz
    chunk=1024,              # Chunk size
    output_channels=2,       # Stereo output
    input_device_index=None  # No input (output-only mode)
)

# Initialize the audio manager
audio_manager = OptimizedAudioManager.get_instance(config)

# Register producer(s) before starting
audio_manager.add_producer("my_sound")

# Start the audio system
audio_manager.start()

# Play sounds
import numpy as np
# Generate a simple sine wave tone (stereo)
sample_rate = 48000
duration = 1.0  # seconds
frequency = 440.0  # A4 note
t = np.linspace(0, duration, int(sample_rate * duration), False)
sine_wave = np.sin(2 * np.pi * frequency * t) * 32767 * 0.5  # 50% volume

# Create stereo data by interleaving
stereo_data = np.empty(len(sine_wave) * 2, dtype=np.int16)
stereo_data[0::2] = sine_wave.astype(np.int16)  # Left channel
stereo_data[1::2] = sine_wave.astype(np.int16)  # Right channel

# Play the sound
audio_manager.play_audio(stereo_data, producer_name="my_sound", loop=False)

# To play a looping sound
audio_manager.play_audio(stereo_data, producer_name="my_sound", loop=True)

# To stop a looping sound
with audio_manager._producers_lock:
    if "my_sound" in audio_manager._producers:
        producer = audio_manager._producers["my_sound"]
        producer.loop = False
        producer._original_audio = None
        producer.buffer.clear()

# When done, stop the audio manager
audio_manager.stop()
```

## Advanced Usage: AudioService

The `OptimizedAudioService` class provides a service-level interface:

```python
from services.optimized_audio_service import OptimizedAudioService
from managers.optimized_audio_manager import AudioConfig

# Create with default config
audio_service = OptimizedAudioService()

# Or with custom config
custom_config = AudioConfig(rate=44100, chunk=512, output_channels=2)
audio_service = OptimizedAudioService(audio_config=custom_config)

# Start the service
await audio_service.start()

# Play a sound file
audio_service.handle_event({
    "type": "play_sound",
    "sound_name": "beep",
    "sound_path": "/path/to/beep.wav"
})

# Stop the service when done
await audio_service.stop()
```

## Implementation Details

The OptimizedAudioManager uses a producer-consumer architecture:

- **Audio Producers**: Sources that generate audio data (like sound files)
- **Audio Consumers**: Destinations that receive audio data (like analysis functions)
- **Internal Buffer System**: Efficient queue system for audio data
- **Callback-based Processing**: Uses SoundDevice's callback mechanism for efficient audio processing

## Key Components

1. **AudioConfig**: Configuration class for audio parameters
2. **OptimizedAudioManager**: Core manager for audio processing
3. **AudioProducer**: Class for audio sources
4. **OptimizedAudioService**: High-level service interface

## Testing

A comprehensive test script is available at `src/tests/test_optimized_audio.py` that verifies:

- Basic sound playback
- Sound sequences
- Volume control
- Looping audio
- Simultaneous sounds

## Known Limitations

- Very short audio samples (less than chunk size) may not play correctly
- Extremely high sample rates may impact performance on low-end hardware
- No built-in audio format conversion (WAV, MP3, etc.) - data must be in numpy array format

## Troubleshooting

### No Audio Output

1. Check that your output device is correctly selected
2. Verify audio volume settings
3. Ensure producers are registered before starting the AudioManager
4. Confirm audio data format matches expectations (int16, correct sample rate)

### High CPU Usage

1. Increase chunk size for less frequent callbacks
2. Reduce sample rate if full audio quality isn't needed
3. Use mono instead of stereo for simpler sounds

### Audio Glitches

1. Try larger buffer sizes
2. Ensure no other CPU-intensive processes are running
3. Check for proper audio format and sample rate matching

## Migration from Original AudioManager

See the [Migration Guide](optimized_audio_migration.md) for detailed instructions on migrating from the original PyAudio-based implementation. 