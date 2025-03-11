# Phoenix Voice Assistant

A voice-enabled AI assistant using Porcupine for wake word detection and Vapi for voice interaction.

## Features

- Efficient wake word detection using Picovoice Porcupine
- Advanced voice interaction powered by Vapi AI
- Low CPU and memory usage
- Support for multiple wake words
- Cross-platform compatibility (macOS, Linux, Windows)
- Easy integration with other voice processing systems

## Prerequisites

- Python 3.8 or higher
- PortAudio (for audio input)
- A free Picovoice access key (get one from [console.picovoice.ai](https://console.picovoice.ai))
- A Vapi API key (get one from [vapi.ai](https://vapi.ai))

## Setting up Raspberry Pi

1. Install Raspberry Pi OS: Bookworm Lite 64 bit image
2. SSH into the Pi
3. Install Git: `sudo apt install git`
4. Install the sound card driver if necessary (for Respeaker Lite, not needed for Respeaker Mic Array)

## Installation

1. Clone the repository:
```bash
git clone https://github.com/SoulAuctioneer/phoenix-vapi.git
cd phoenix-vapi
```

2. Run the install script:
```bash
# On macOS/Linux/Rasperry Pi OS:
./install.sh

# On Windows (UNTESTED!):
# First ensure you have Python and Visual C++ Build Tools installed
./install.sh
```

3. Get your API keys:
   - Picovoice access key:
     - Go to [console.picovoice.ai](https://console.picovoice.ai)
     - Sign up for a free account
     - Create a new access key
     - Copy the access key
   - Vapi API key:
     - Go to [vapi.ai](https://vapi.ai)
     - Sign up and get your API key

4. Configure your API keys:
   - Open the `.env` file in the project root
   - Add your keys:
     ```
     PICOVOICE_ACCESS_KEY=your_key_here
     VAPI_API_KEY=your_vapi_api_key_here
     ```

## Usage

### Wake Word Detection

1. Run the example wake word detector:
```bash
python src/example_wake_word.py
```

2. Say one of the available wake words. The default wake word is "Porcupine"

Alternatively, you can use a custom wake word by passing the path to a ppn file to the WakeWordDetector constructor, or set in the config.py file.

3. Press Ctrl+C to exit

### Full Voice Assistant

1. Run the main application:
```bash
python src/main.py
```

2. Say the wake word to activate the assistant
3. Speak your command or question
4. The assistant will respond using Vapi's voice AI

## Customization

### Using Different Wake Words

You can modify the wake word in `src/wake_word.py`:

```python
# Use a different built-in wake word
detector = WakeWordDetector(keyword="alexa")

# Or use a custom wake word (requires enterprise access key)
detector = WakeWordDetector(keyword_path="/path/to/custom_wake_word.ppn")
```

### Adjusting Sensitivity

The wake word detector's sensitivity can be adjusted in the Picovoice console.

### Customizing Voice Interaction

You can customize the Vapi AI behavior by modifying the configuration in `src/config.py`.

## Troubleshooting

### Audio Issues
- Ensure your microphone is properly connected and selected as the default input device
- Install PortAudio if you get audio-related errors:
  ```bash
  # macOS
  brew install portaudio

  # Linux
  sudo apt-get install python3-pyaudio portaudio19-dev
  ```

### Access Key Issues
- Verify both API keys are correctly set in the `.env` file
- Check that the Picovoice access key is valid in the Picovoice console
- Verify your Vapi API key in the Vapi dashboard
- Make sure you're using the latest versions of both SDKs

## Raspberry Pi Installation

To install on Raspberry Pi:
1. Install 64-bit Raspberry Pi Lite Legacy (Bullseye) OS
2. Install the Respeaker if you're using one
3. Install git: `sudo apt install git`
4. Clone this repo
5. Run `./install.sh`
6. Edit `.env` file with both API keys
7. Start venv: `source venv/bin/activate`
8. Run `python src/main.py`

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- [Picovoice](https://picovoice.ai) for their excellent Porcupine wake word engine
- [Vapi](https://vapi.ai) for their advanced voice AI platform
- The open-source community for various audio processing tools and libraries