#!/bin/bash

echo "Installing Phoenix AI Companion..."

# Detect operating system
if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS
    echo "Detected macOS system..."
    
    # Check if Homebrew is installed
    if ! command -v brew &> /dev/null; then
        echo "Installing Homebrew..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    fi
    
    # Install system dependencies
    echo "Installing system dependencies..."
    brew install portaudio

    # Install Rust if not present
    if ! command -v rustc &> /dev/null; then
        echo "Installing Rust..."
        curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
        source $HOME/.cargo/env
    fi
    
elif [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "win32" ]]; then
    # Windows
    echo "Detected Windows system..."
    echo "Please ensure you have Python 3.8+ installed from python.org"
    echo "Also ensure you have the Microsoft Visual C++ Build Tools installed"
    
    # Install Rust if not present
    if ! command -v rustc &> /dev/null; then
        echo "Installing Rust..."
        curl --proto '=https' --tlsv1.2 -sSf https://win.rustup.rs -o rustup-init.exe
        ./rustup-init.exe -y
        source $HOME/.cargo/env
    fi
    
else
    # Linux
    echo "Detected Linux system..."
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
        build-essential \
        pkg-config \
        libssl-dev

    # Install Rust if not present
    if ! command -v rustc &> /dev/null; then
        echo "Installing Rust..."
        curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
        source $HOME/.cargo/env
    fi
fi

# Create virtual environment
echo "Setting up Python virtual environment..."
if [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "win32" ]]; then
    python -m venv venv
    ./venv/Scripts/activate
else
    python3 -m venv venv
    source venv/bin/activate
fi

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

# Make main.py executable (not needed for Windows)
if [[ "$OSTYPE" != "msys" ]] && [[ "$OSTYPE" != "win32" ]]; then
    chmod +x main.py
fi

echo "Installation complete!"
echo "To start Phoenix AI Companion:"
echo "1. Edit .env file and add your Vapi API key"
if [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "win32" ]]; then
    echo "2. Run: venv\\Scripts\\activate && python main.py"
else
    echo "2. Run: source venv/bin/activate && python main.py"
fi 