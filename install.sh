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

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo "Creating .env file..."
    echo "# Add your environment variables here" > .env
    echo "PICOVOICE_ACCESS_KEY=your_key_here" >> .env
    echo "VAPI_API_KEY=your_vapi_api_key_here (private key)" >> .env
    echo "VAPI_CLIENT_KEY=your_vapi_client_key_here (public key)" >> .env
    echo "OPENAI_API_KEY=your_openai_api_key_here (optional, only needed for speech-to-intent if unable to use Picovoice Rhino)" >> .env
    echo ""
    echo "Please update .env with your API keys:"
    echo "1. Picovoice access key from console.picovoice.ai"
    echo "2. Vapi API key from dashboard.vapi.ai"
fi

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
        pkg-config
    
    # Add user to bluetooth group
    if ! groups $USER | grep -q "bluetooth"; then
        echo "Adding user to bluetooth group..."
        sudo usermod -a -G bluetooth $USER
        echo "Bluetooth group permissions will take effect after logout/login"
    fi
    
    # Raspberry Pi specific setup
    if is_raspberry_pi; then
        echo "Detected Raspberry Pi - Setting up NeoPixel requirements..."
        
        # Install additional dependencies
        sudo apt-get install -y python3-pip python3-dev
        
        # Enable Bluetooth interface
        if ! grep -q "^dtparam=bluetooth=on" /boot/config.txt; then
            echo "Enabling Bluetooth interface..."
            sudo sh -c 'echo "dtparam=bluetooth=on" >> /boot/config.txt'
            echo "Bluetooth interface will be enabled after reboot"
        fi

        # Start and enable Bluetooth service
        sudo systemctl enable bluetooth
        sudo systemctl start bluetooth
        
        # Enable SPI interface
        if ! grep -q "dtparam=spi=on" /boot/config.txt; then
            echo "Enabling SPI interface..."
            sudo sh -c 'echo "dtparam=spi=on" >> /boot/config.txt'
            echo "SPI interface will be enabled after reboot"
        fi
        
        # Add user to gpio group if not already added
        if ! groups $USER | grep -q "gpio"; then
            echo "Adding user to gpio group..."
            sudo usermod -a -G gpio $USER
            echo "Group permissions will take effect after logout/login"
        fi
        
        # Create udev rule for NeoPixel access if it doesn't exist
        if [ ! -f "/etc/udev/rules.d/99-neopixel.rules" ]; then
            echo "Setting up NeoPixel permissions..."
            sudo sh -c 'echo "SUBSYSTEM==\"gpio*\", PROGRAM=\"/bin/sh -c '\''chown -R root:gpio /sys/class/gpio && chmod -R 770 /sys/class/gpio; chown -R root:gpio /sys/devices/virtual/gpio && chmod -R 770 /sys/devices/virtual/gpio; chown -R root:gpio /sys/devices/platform/soc/*.gpio/gpio && chmod -R 770 /sys/devices/platform/soc/*.gpio/gpio'\''\"\nSUBSYSTEM==\"spi*\", PROGRAM=\"/bin/sh -c '\''chown -R root:gpio /sys/bus/spi/devices/spi0.0 && chmod -R 770 /sys/bus/spi/devices/spi0.0'\''\"" > /etc/udev/rules.d/99-neopixel.rules'
            sudo udevadm control --reload-rules
            sudo udevadm trigger
        fi

        sudo python3 -m pip install --force-reinstall adafruit-blinka        
        echo ""
        echo "NeoPixel setup complete!"
        echo "NOTE: You may need to reboot for all changes to take effect"
    fi
fi

echo ""
echo "Installation complete!"
echo "Next steps:"
echo "1. Get your free Picovoice access key from console.picovoice.ai"
echo "2. Get your Vapi API key from vapi.ai"
echo "3. Add service keys to .env file:"
echo "   PICOVOICE_ACCESS_KEY=your_key_here"
echo "   VAPI_API_KEY=your_vapi_api_key_here (private key)"
echo "   VAPI_CLIENT_KEY=your_vapi_client_key_here (public key)"
echo "   OPENAI_API_KEY=your_openai_api_key_here"
echo "4. Run the example: python src/example_wake_word.py"

# Add Raspberry Pi specific instructions if applicable
if is_raspberry_pi; then
    echo ""
    echo "Raspberry Pi specific notes:"
    echo "- If this is your first install, please REBOOT to enable SPI and Bluetooth"
    echo "- Log out and back in for GPIO and Bluetooth group changes to take effect"
    echo "- Connect NeoPixel data line to GPIO21 (pin 40 on the board) - we use this pin instead of GPIO18 to avoid conflicts with audio"
    echo "- To test LED ring: python src/led_control.py"
    echo "- To verify Bluetooth is working: sudo hciconfig"
fi 