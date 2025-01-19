#!/bin/bash

echo "Installing AI Companion for Kids..."

# Update system packages
echo "Updating system packages..."
sudo apt-get update
sudo apt-get upgrade -y

# Install system dependencies
echo "Installing system dependencies..."
sudo apt-get install -y \
    python3-pip \
    python3-venv \
    portaudio19-dev \
    python3-rpi.gpio

# Create virtual environment
echo "Setting up Python virtual environment..."
python3 -m venv venv
source venv/bin/activate

# Install Python dependencies
echo "Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Create .env file if it doesn't exist
if [ ! -f .env ]; then
    echo "Creating .env file..."
    echo "VAPI_API_KEY=your_vapi_api_key_here" > .env
    echo "Please edit .env file and add your Vapi API key"
fi

# Make main.py executable
chmod +x main.py

echo "Installation complete!"
echo "To start the AI Companion:"
echo "1. Edit .env file and add your Vapi API key"
echo "2. Connect button to GPIO 18 and LED to GPIO 24"
echo "3. Run: source venv/bin/activate && python main.py" 