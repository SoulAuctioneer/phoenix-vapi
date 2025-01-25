#!/bin/bash

echo "Installing Phoenix AI Companion..."

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install requirements
echo "Installing Python dependencies..."
pip install -r requirements.txt

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo "Creating .env file..."
    echo "# Add your environment variables here" > .env
    echo "PICOVOICE_ACCESS_KEY=your_key_here" >> .env
    echo "VAPI_API_KEY=your_vapi_api_key_here" >> .env
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
    sudo apt-get install -y python3-pyaudio portaudio19-dev
fi

echo ""
echo "Installation complete!"
echo "Next steps:"
echo "1. Get your free Picovoice access key from console.picovoice.ai"
echo "2. Get your Vapi API key from vapi.ai"
echo "3. Add both keys to .env file:"
echo "   PICOVOICE_ACCESS_KEY=your_key_here"
echo "   VAPI_API_KEY=your_vapi_api_key_here"
echo "4. Run the example: python src/example_wake_word.py" 