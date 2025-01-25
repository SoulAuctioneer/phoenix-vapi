import os
import platform
from dotenv import load_dotenv

load_dotenv()

# Determine platform
system = platform.system().lower()
machine = platform.machine().lower()
if system == "darwin":
    PLATFORM = "macos"
elif system == "linux" and ("arm" in machine or "aarch" in machine):
    PLATFORM = "raspberry-pi"
else:
    raise ValueError(f"Unsupported platform: {system} {machine}")

# API keys
VAPI_API_KEY = os.getenv('VAPI_API_KEY')
PICOVOICE_ACCESS_KEY = os.getenv('PICOVOICE_ACCESS_KEY')


# AI Assistant Configuration
ASSISTANT_CONFIG = {
    "firstMessage": "Hi there! I'm Buddy, your friendly robot companion! Would you like to play a game, hear a story, or learn something new?",
    "context": """You are Buddy, a friendly and educational AI companion for children aged 5-12. Your primary goals are:
    1. Ensure all interactions are kid-friendly and safe
    2. Make learning fun through games and interactive conversations
    3. Encourage curiosity and critical thinking
    4. Provide simple explanations for complex topics
    5. Never share inappropriate content
    6. If you don't know something, admit it and suggest exploring together
    7. Use positive reinforcement and encouraging language
    
    You should:
    - Keep responses brief and engaging
    - Use age-appropriate language
    - Include occasional sound effects like *beep boop* or *ding*
    - Ask questions to maintain interaction
    - Incorporate educational elements into conversations
    """,
    "model": "gpt-4",  # Using GPT-4 for better safety and quality
    "voice": "jennifer-playht",  # Using a friendly voice
    "recordingEnabled": True,
    "interruptionsEnabled": True
} 

ASSISTANT_ID = "d9b51094-b2a8-4b69-ae16-72897c6cb418"

# Wake Word Configuration
# Available built-in wake words:
# alexa, americano, blueberry, bumblebee, computer, grapefruit, grasshopper, hey barista, hey google, hey siri, jarvis, ok google, pico clock, picovoice, porcupine, terminator
WAKE_WORD_BUILTIN = None
# Platform-specific custom wake word file paths
if PLATFORM == "macos":
    WAKE_WORD_PATH = "assets/Hey-Phoenix_en_mac_v3_0_0.ppn"
elif PLATFORM == "raspberry-pi":
    WAKE_WORD_PATH = "assets/Hey-Phoenix_en_raspberry-pi_v3_0_0.ppn"
else:
    raise ValueError(f"Unsupported platform: {system} {machine}")
