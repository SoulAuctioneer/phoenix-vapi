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
    echo "" >> .env
    echo "# Picovoice access key" >> .env
    echo "PICOVOICE_ACCESS_KEY=your_key_here" >> .env
    echo "" >> .env
    echo "# Picovoice wake word file path" >> .env
    echo "PORCUPINE_MODEL_PATH=assets/models/wake-word-mac.ppn" >> .env
    echo "" >> .env
    echo "# PicoVoice Rhino context file path" >> .env
    echo "RHINO_MODEL_PATH=assets/models/text-to-intent-mac.rhn" >> .env
    echo "" >> .env
    echo "# Vapi private key" >> .env
    echo "VAPI_API_KEY=your_vapi_api_key_here" >> .env
    echo "" >> .env
    echo "# Vapi public key" >> .env
    echo "VAPI_CLIENT_KEY=your_vapi_client_key_here" >> .env
    echo "" >> .env
    echo "# OpenAI API key (optional, only needed for speech-to-intent if unable to use Picovoice Rhino)" >> .env
    echo "OPENAI_API_KEY=your_openai_api_key_here" >> .env
    echo "" >> .env
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

        sudo python3 -m pip install --force-reinstall adafruit-blinka        
        echo ""
        echo "NeoPixel setup complete!"
        echo "NOTE: You may need to reboot for all changes to take effect"
    fi
fi

echo ""
echo "Installation complete!"
echo "Next steps:"
echo "1. Get your Picovoice access key from console.picovoice.ai and download Porcupine and Rhino models"
echo "2. Get your Vapi API key from vapi.ai"
echo "3. Get your OpenAI API key from openai.com"
echo "4. Add service keys to .env file"
echo "5. Run the app: ./run.sh"

# Add Raspberry Pi specific instructions if applicable
if is_raspberry_pi; then
    echo ""
    echo "Raspberry Pi specific notes:"
    echo "- If this is your first install, please REBOOT to enable I2C, SPI and Bluetooth"
    echo "- Log out and back in for GPIO, I2C and Bluetooth group changes to take effect"
    echo "- Connect BNO085 sensor to I2C pins: SDA (GPIO2/Pin3), SCL (GPIO3/Pin5), 3.3V, GND"
    echo "- Connect NeoPixel data line to GPIO21 (pin 40 on the board) - we use this pin instead of GPIO18 to avoid conflicts with audio"
    echo "- To test I2C devices: sudo i2cdetect -y 1 (BNO085 should appear at address 0x4a or 0x4b)"
    echo "- To diagnose BNO085 sensor: python3 src/diagnostics/i2c_test.py"
    echo "- To test LED ring: python src/led_control.py"
    echo "- To verify Bluetooth is working: sudo hciconfig"
fi 