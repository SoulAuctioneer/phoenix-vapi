# Phoenix AI Companion Toy

The Phoenix is an interactive, smart, beautiful, and screen-free AI-powered companion and toy for children. It provides emotional, social, and cognitive engagement and support via dynamic nurturing mechanics, guided play, tutoring, and wellness practices. 

It is run on a Raspberry Pi that is embedded in a bouncy ball toy.

Physical Design
- A soft, tennis-ball-sized plush ball with a glowing exterior featuring vibrant, detailed LED patterns.
- Highly context-aware via motion, sound, and touch sensors.
- Haptic feedback.

Key Functionality
- AI voice chat.
- Stroking and purring.
- Intelligent: Highly context-aware, interactive, and smart.
- Guided Play: Offers collaborative quests, puzzles, and storytelling activities that stimulate creativity and critical thinking.
- Nurture Mechanics: Enables children to care for and bond with their Phoenix through interactions that promote empathy and responsibility.
- Adaptive Personalization: Phoenix evolves and unlocks new capabilities based on the child’s interaction patterns. It develops a personality and memory tied to the child’s traits and choices, and their shared experiences.
- Adaptive Teaching.
- Emotional Regulation.
- Private and Secure.


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

## Wiring 
Raspberry Pi
- I2C Qwiic: bottom left: red, blue, yellow, skip, black
- Power: top left: skip, red, black
- LED data: top right
Powerboost From Right:
- Rightmost: 5V
- 2nd rightmost: GND
- 4th rightmost: PWR SWITCH
- 5th rightmost: PWR SWITCH


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

3. Reboot the device (maybe?)

4. Get your API keys:
   - Picovoice access key:
     - Go to [console.picovoice.ai](https://console.picovoice.ai)
     - Sign up for a free account
     - Create a new access key
     - Copy the access key
   - Vapi API key:
     - Go to [vapi.ai](https://vapi.ai)
     - Sign up and get your API key

5. Configure your API keys:
   - Open the `.env` file in the project root
   - Add your keys:
     ```
     PICOVOICE_ACCESS_KEY=your_key_here
     VAPI_API_KEY=your_vapi_api_key_here
     ```

## Usage

1. Run the main application:
```bash
python src/main.py
```

2. Say the wake word to activate the assistant
3. Speak your command or question: one of "wake up", "play catch", "cuddle", hide and seek".
4. The assistant will respond using Vapi's voice AI

### Customizing Voice Interaction

You can customize the Vapi AI behavior by modifying the configuration in `src/config.py`.

## Acknowledgments

- [Picovoice](https://picovoice.ai) for their excellent Porcupine wake word engine
- [Vapi](https://vapi.ai) for their advanced voice AI platform
- The open-source community for various audio processing tools and libraries