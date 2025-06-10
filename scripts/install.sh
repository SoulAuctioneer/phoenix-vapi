#!/bin/bash

echo "Installing Phoenix AI Companion..."

# Function to check if running on Raspberry Pi
is_raspberry_pi() {
    if [ -f /proc/device-tree/model ]; then
        if grep -q "Raspberry Pi" /proc/device-tree/model; then
            return 0
        fi
    fi
    return 1
}

# Install system dependencies for audio
if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS
    echo "Installing audio dependencies for macOS..."
    brew install portaudio
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    # Linux
    echo "Installing audio dependencies for Linux..."
    sudo apt-get update
    sudo apt-get install -y python3-pyaudio portaudio19-dev \
        libglib2.0-dev \
        dbus \
        libdbus-1-dev \
        pkg-config \
        python3-dev \
        python3-pip
    
    # Add user to bluetooth group
    if ! groups $USER | grep -q "bluetooth"; then
        echo "Adding user to bluetooth group..."
        sudo usermod -a -G bluetooth $USER
        echo "Bluetooth group permissions will take effect after logout/login"
    fi
    
    # Raspberry Pi specific setup
    if is_raspberry_pi; then
        echo "Detected Raspberry Pi - Setting up requirements..."
        
        # Determine config.txt location
        if [ -f "/boot/firmware/config.txt" ]; then
            CONFIG_PATH="/boot/firmware/config.txt"
        else
            CONFIG_PATH="/boot/config.txt"
        fi
        
        # Install I2C tools
        sudo apt-get install -y i2c-tools
        
        # Enable I2C interface with proper configuration for BNO085
        if ! grep -q "^dtparam=i2c_arm=on" "$CONFIG_PATH"; then
            echo "Enabling I2C interface..."
            sudo sh -c "echo 'dtparam=i2c_arm=on' >> $CONFIG_PATH"
            REBOOT_REQUIRED=1
        fi
        
        # Set I2C clock speed to 400kHz (fast mode) to mitigate clock stretching issues on Raspberry Pi
        # See: https://learn.adafruit.com/raspberry-pi-i2c-clock-stretching-fixes
        if ! grep -q "^dtparam=i2c_arm_baudrate=" "$CONFIG_PATH"; then
            echo "Setting I2C clock speed to 400kHz to mitigate clock stretching..."
            sudo sh -c "echo 'dtparam=i2c_arm_baudrate=400000' >> $CONFIG_PATH"
            REBOOT_REQUIRED=1
        fi
        
        # Enable I2C1 interface as backup
        if ! grep -q "^dtparam=i2c1=on" "$CONFIG_PATH"; then
            echo "Enabling I2C1 interface..."
            sudo sh -c "echo 'dtparam=i2c1=on' >> $CONFIG_PATH"
            REBOOT_REQUIRED=1
        fi
        
        # Enable Bluetooth interface
        if ! grep -q "^dtparam=bluetooth=on" "$CONFIG_PATH"; then
            echo "Enabling Bluetooth interface..."
            sudo sh -c "echo 'dtparam=bluetooth=on' >> $CONFIG_PATH"
            REBOOT_REQUIRED=1
        fi

        # Enable SPI interface
        if ! grep -q "^dtparam=spi=on" "$CONFIG_PATH"; then
            echo "Enabling SPI interface..."
            sudo sh -c "echo 'dtparam=spi=on' >> $CONFIG_PATH"
            REBOOT_REQUIRED=1
        fi
        
        # Add user to gpio group if not already added
        if ! groups $USER | grep -q "gpio"; then
            echo "Adding user to gpio group..."
            sudo usermod -a -G gpio $USER
            echo "Group permissions will take effect after logout/login"
        fi
        
        # Add user to i2c group for BNO085 sensor access
        if ! groups $USER | grep -q "i2c"; then
            echo "Adding user to i2c group for sensor access..."
            sudo usermod -a -G i2c $USER
            echo "I2C group permissions will take effect after logout/login"
        fi
        
        # Create udev rule for NeoPixel access if it doesn't exist
        if [ ! -f "/etc/udev/rules.d/99-neopixel.rules" ]; then
            echo "Setting up NeoPixel permissions..."
            sudo sh -c 'echo "SUBSYSTEM==\"gpio*\", PROGRAM=\"/bin/sh -c '\''chown -R root:gpio /sys/class/gpio && chmod -R 770 /sys/class/gpio; chown -R root:gpio /sys/devices/virtual/gpio && chmod -R 770 /sys/devices/virtual/gpio; chown -R root:gpio /sys/devices/platform/soc/*.gpio/gpio && chmod -R 770 /sys/devices/platform/soc/*.gpio/gpio'\''\"\nSUBSYSTEM==\"spi*\", PROGRAM=\"/bin/sh -c '\''chown -R root:gpio /sys/bus/spi/devices/spi0.0 && chmod -R 770 /sys/bus/spi/devices/spi0.0'\''\"" > /etc/udev/rules.d/99-neopixel.rules'
            sudo udevadm control --reload-rules
            sudo udevadm trigger
        fi

        echo ""
        echo "NeoPixel setup complete!"
        echo "NOTE: You may need to reboot for all changes to take effect"
    fi
fi

# Create virtual environment if it doesn't exist
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

# Activate virtual environment
source .venv/bin/activate

# Install requirements
echo "Installing Python dependencies..."
pip install -r requirements.txt

# Create .env file from example if it doesn't exist
if [ ! -f ".env" ]; then
    echo "Creating .env file from .env.example..."
    cp .env.example .env
fi

# Recreate memories.json with an initial memory
echo "Recreating memories.json with initial memory..."
python3 -c '
import json
import datetime
import os

os.makedirs("data", exist_ok=True)

now_utc = datetime.datetime.now(datetime.timezone.utc)
now_local = now_utc.astimezone()

created_at = f"{now_local.strftime(''%B'')} {now_local.day}, {now_local.strftime(''%Y at %I:%M %p %Z'')}"

memory_data = {
    "memories": [
        {
            "content": "You first woke up on Earth.",
            "topic": "event",
            "importance": "medium",
            "timestamp": now_utc.isoformat(),
            "created_at": created_at,
        }
    ]
}

with open("data/memories.json", "w") as f:
    json.dump(memory_data, f, indent=2)
    f.write("\n")
'

echo ""
echo "PHOENIX INSTALLATION COMPLETE!"
echo ""
echo "----------------------------------------"
echo "NEXT STEPS"
echo "----------------------------------------"
echo "1. Edit the .env file with your API keys and model paths:"
echo ""
echo "  - PICOVOICE_ACCESS_KEY: Get from https://console.picovoice.ai"
echo "  - VAPI_API_KEY & VAPI_CLIENT_KEY: Get from https://dashboard.vapi.ai"
echo "  - OPENAI_API_KEY: Get from https://platform.openai.com/api-keys"
echo "  - ELEVENLABS_API_KEY: Get from https://elevenlabs.io/api-keys"
echo "  - TWILIO_ACCOUNT_SID & TWILIO_AUTH_TOKEN: Get from https://www.twilio.com/console"
echo "  - NGROK_AUTH_TOKEN: Get from https://dashboard.ngrok.com/get-started/your-authtoken"
echo ""
echo "2. To run the application, use the command:"
echo "   ./run.sh"
echo ""

# Add Raspberry Pi specific instructions if applicable
if is_raspberry_pi; then
    echo "----------------------------------------"
    echo "RASPBERRY PI NOTES"
    echo "----------------------------------------"
    echo "- A REBOOT IS RECOMMENDED to apply system changes (I2C, SPI, Bluetooth)."
    echo "- Run `sudo reboot now` to apply system changes."
    echo "- For detailed hardware assembly, see the 'Wiring' section in README.md"
    echo ""
    echo "To install as a service to run on device boot, run `scripts/install-service.sh`"
    echo ""
    echo "If using Respeaker sound card:"
    echo "- Run 'sudo scripts/setup_respeaker_only.sh' to disable other audio devices"
    echo "- This will eliminate ALSA errors and significantly speed up app startup"
    echo ""
fi
