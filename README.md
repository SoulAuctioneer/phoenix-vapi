# phoenix-vapi
Vapi Implementation of Phoenix Companion

To install on Raspberry Pi:
- Install 64-bit Raspberry Pi Lite Legacy (Bullseye) OS
- Install git, python3, pip3, and pipx
  `sudo apt install git python3 python3-pip python3-venv`
- Install python3-venv
- Clone this repo
  `git clone https://github.com/phoenix-vapi/phoenix-vapi.git`
- Run `./install.sh`
- Edit .env file with your Vapi API key
- Start venv: `source venv/bin/activate`
- Run `python3 src/main.py`