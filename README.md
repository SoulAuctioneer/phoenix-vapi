# Phoenix AI Companion Toy

The Phoenix is an interactive, smart, beautiful, and screen-free AI-powered companion and toy for children. It provides emotional, social, and cognitive engagement and support via dynamic nurturing mechanics, guided play, tutoring, and wellness practices. 

It is run on a Raspberry Pi that is embedded in a bouncy ball toy.


# Physical Design
- A soft, tennis-ball-sized plush ball with a glowing exterior featuring vibrant, detailed LED patterns.
- Highly context-aware via motion, sound, and touch sensors.
- Haptic feedback.


# Key Functionality
- AI voice chat.
- Stroking and purring.
- Intelligent: Highly context-aware, interactive, and smart.
- Guided Play: Offers collaborative quests, puzzles, and storytelling activities that stimulate creativity and critical thinking.
- Nurture Mechanics: Enables children to care for and bond with their Phoenix through interactions that promote empathy and responsibility.
- Adaptive Personalization: Phoenix evolves and unlocks new capabilities based on the child’s interaction patterns. It develops a personality and memory tied to the child’s traits and choices, and their shared experiences.
- Adaptive Teaching.
- Emotional Regulation.
- Private and Secure.


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
- Amplifier shutdown pin: GPIO 17 (bottom, 6th from left, right after the I2C Qwiic)
Powerboost From Right:
- Rightmost: 5V
- 2nd rightmost: GND
- 4th rightmost: PWR SWITCH
- 5th rightmost: PWR SWITCH


## Setting up Raspberry Pi

1. Install the Raspberry Pi Imager on your computer: https://www.raspberrypi.com/software/
2. Install Raspberry Pi OS: Bookworm Lite 64 bit image onto an SD card
  Device name: pizero[some integer]
  Other settings you'll need: 
  Device: Raspberry Pi Zero 2 W
  OS: "Other" > Lite 64 bit (first one)
  ...Click next... 
  Settings: 
  Device name is pizero3 etc.
  Wifi is NuHaus Unified.
  WiFi region is US
  Username is "ash"
  Password is "xdara"
  Next tab: Use SSH enabled
  Click SAVE
  Apply OS customization settings: YES, continue, yes, etc etc

3. SSH into the Pi
4. Install Git: `sudo apt install git`
5. Install the sound card driver if necessary (for Respeaker Lite, not needed for Respeaker Mic Array)


## Installation

6. Clone the repository:
```bash
git clone https://github.com/SoulAuctioneer/phoenix-vapi.git
cd phoenix-vapi
```

7. Run the install script:
```bash
# On macOS/Linux/Rasperry Pi OS:
scripts/install.sh

# On Windows (UNTESTED!):
# First ensure you have Python and Visual C++ Build Tools installed
scripts/install.sh
```

8. Reboot the device (maybe?)

9. Get and configure your API keys. 
  - Open the `.env` file in the project root to see what you need.
  - Get the keys.
  - Add your keys.

10. To install as a service to run on device boot, run `scripts/install_service.sh`

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
