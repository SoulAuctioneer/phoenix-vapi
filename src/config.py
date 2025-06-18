import time
import os
import platform
import re
import logging
import random
from textwrap import dedent
from typing import Union
from dotenv import load_dotenv
from enum import Enum, auto
from typing import Union
from dataclasses import dataclass

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

def clean_env_value(value: str) -> str:
    """Clean environment variable value by removing comments and whitespace"""
    if value is None:
        return None
    # Split on first # and take the first part
    value = value.split('#')[0]
    return value.strip()

# API keys
VAPI_API_KEY = clean_env_value(os.getenv('VAPI_API_KEY'))
VAPI_CLIENT_KEY = clean_env_value(os.getenv('VAPI_CLIENT_KEY'))
PICOVOICE_ACCESS_KEY = clean_env_value(os.getenv('PICOVOICE_ACCESS_KEY'))
OPENAI_API_KEY = clean_env_value(os.getenv('OPENAI_API_KEY'))  # Add OpenAI API key
ELEVENLABS_API_KEY = clean_env_value(os.getenv('ELEVENLABS_API_KEY')) # ElevenLabs API Key
NGROK_AUTH_TOKEN = clean_env_value(os.getenv('NGROK_AUTH_TOKEN'))

# Which voice to use for TTS
TTS_VOICE = clean_env_value(os.getenv('TTS_VOICE')) or "ana"  # Or "timmy"
ASSISTANT_NAME = "Mister Wibble" if TTS_VOICE == "timmy" else "Fifi"

# Set in main.py during arg parsing (if applicable).
LOG_FILTERS = None

def get_filter_logger(logger_name: str):        
    logger = logging.getLogger(logger_name)
    return logger
    if logger.handlers:
        return logger
    
    if LOG_FILTERS:
        class PatternFilter(logging.Filter):
            def __init__(self, pattern):
                super().__init__()
                self.pattern = re.compile(pattern)
            
            def filter(self, record):
                # Filter based on the logger name (which often includes filename)
                return (self.pattern.search(record.name) or 
                        self.pattern.search(record.getMessage()))

        logging.info(f"logger {logger_name} will only output logs matching one of: {LOG_FILTERS}")
        handler = logging.StreamHandler()
        handler.addFilter(PatternFilter('|'.join(LOG_FILTERS)))
        logger.addHandler(handler)
        
    logger.propagate = False
    return logger

    
# Call Configuration
class CallConfig:
    """Configuration for call-related settings"""        
    # Twilio Configuration (for PSTN calls)
    TWILIO_ACCOUNT_SID = clean_env_value(os.getenv('TWILIO_ACCOUNT_SID'))
    TWILIO_AUTH_TOKEN = clean_env_value(os.getenv('TWILIO_AUTH_TOKEN'))
    TWILIO_FROM_NUMBER = "+14153068641" # Must be a Twilio number in E.164 format
    TWILIO_POLL_INTERVAL = 2 # Interval in seconds to poll call status
    CONTACT_NUMBERS = {
        "ash":  "+14153078066",
        "tom":  "+447973782971",
        "lucy": "+14153078066",
        "mom":  "+14153078066",
        "dad":  "+14153078066",
    }

# Intent Detection Configuration
class IntentConfig:
    """Configuration for intent detection"""
    # Path to the Rhino context file for intent detection
    MODEL_PATH = clean_env_value(os.getenv('RHINO_MODEL_PATH'))    
    # How long to listen for an intent after wake word (in seconds)
    DETECTION_TIMEOUT = 7.0

# Wake Word Configuration
class WakeWordConfig:
    # Available built-in wake words:
    # alexa, americano, blueberry, bumblebee, computer, grapefruit, grasshopper, hey barista, hey google, hey siri, jarvis, ok google, pico clock, picovoice, porcupine, terminator
    WAKE_WORD_BUILTIN = None
    # Or custom wake word file path
    MODEL_PATH = clean_env_value(os.getenv('PORCUPINE_MODEL_PATH'))

# LED Configuration
class LEDConfig:
    LED_PIN = 21  # GPIO10 for NeoPixel data - Using this to keep audio enabled on GPIO18
    LED_BRIGHTNESS = 0.4  # LED brightness (0.0 to 1.0)
    LED_ORDER = "GRB"  # Color order of the LEDs (typically GRB or RGB)
    LED_COUNT = 32  # Number of NeoPixels in the ring / strip - 24 for ring, 160 for COB strip, 24+8 for large+small ring
    IS_DUAL_RINGS = True # Whether the LED strip is composed of two rings
    LED_COUNT_RING1 = 24 # Number of NeoPixels in the first ring
    LED_COUNT_RING2 = 8 # Number of NeoPixels in the second ring
    USE_RESPEAKER_LEDS = True # Whether to enable the ReSpeaker LED bridge
    RESPEAKER_BRIGHTNESS_BOOST = 1.6 # Multiplier to adjust ReSpeaker brightness relative to NeoPixels (e.g., 1.25 = 25% brighter)
    MAX_TOTAL_BRIGHTNESS = 14000 # Heuristic value to prevent power brownouts. This is the max sum of all RGB values across all pixels. A value of 10000 is a safe starting point.

# Audio Amplifier Configuration
class AudioAmplifierConfig:
    """Configuration for the audio amplifier"""
    # Only enable amplifier on the physical device
    IS_AMPLIFIER_ENABLED = (PLATFORM == "raspberry-pi")
    ENABLE_PIN = 17  # GPIO pin to enable the amplifier
    DISABLE_DELAY = 0.2  # Grace period in seconds before disabling amp

# Base Audio Configuration (used by both ConversationConfig and AudioConfig)
class AudioBaseConfig:
    """Base audio configuration that all audio components should use"""
    FORMAT = 'int16'  # numpy/pyaudio compatible format
    NUM_CHANNELS = 1
    SAMPLE_RATE = 16000
    CHUNK_SIZE = 640  # Optimized for WebRTC echo cancellation without stuttering
    BUFFER_SIZE = 5   # Minimal buffering to reduce latency
    DEFAULT_VOLUME = 1.0
    CONVERSATION_SFX_VOLUME = 0.5 # Volume for sound effects when a conversation is active
    VOLUME_STEP = 0.2 # Volume step for volume control
    # Calculate time-based values
    CHUNK_DURATION_MS = (CHUNK_SIZE / SAMPLE_RATE) * 1000  # Duration of each chunk in milliseconds
    LIKELY_LATENCY_MS = CHUNK_DURATION_MS * BUFFER_SIZE  # Calculate probable latency in milliseconds
    print(f"Audio chunk duration: {CHUNK_DURATION_MS}ms, Buffer size: {BUFFER_SIZE}, Likely latency: {LIKELY_LATENCY_MS}ms")

# Audio Configuration for Calls
class ConversationConfig:
    """Unified configuration for conversation-related settings"""

    MUTE_WHEN_ASSISTANT_SPEAKING = True
    
    class Audio:
        """Audio-specific configuration"""
        NUM_CHANNELS = AudioBaseConfig.NUM_CHANNELS
        SAMPLE_RATE = AudioBaseConfig.SAMPLE_RATE
        CHUNK_SIZE = AudioBaseConfig.CHUNK_SIZE
        BUFFER_SIZE = 5
        DEFAULT_VOLUME = 1.0
    
    class Vapi:
        """Vapi API configuration"""
        DEFAULT_API_URL = "https://api.vapi.ai"
        API_KEY = VAPI_CLIENT_KEY
        SPEAKER_USERNAME = "Vapi Speaker"
    
    class Daily:
        """Daily.co specific configuration"""
        MIC_DEVICE_ID = "my-mic"
        SPEAKER_DEVICE_ID = "my-speaker"
        MIC_CONSTRAINTS = {
            "autoGainControl": {"exact": True},
            "noiseSuppression": {"exact": True},
            "echoCancellation": {"exact": True},
        }
        SUBSCRIPTION_PROFILES = {
            "base": {
                "camera": "unsubscribed",
                "microphone": "subscribed"
            }
        }

# Sound Effects
class SoundEffect(str, Enum):
    """Available sound effects and their corresponding filenames"""
    TUNE_PLANTASIA = "plantasia.wav"
    RISING_TONE = "rising_tone.wav"
    MMHMM = "mmhmm.wav"
    YAWN = "yawn.wav"
    YAWN2 = "yawn2.wav"
    MAGICAL_SPELL = "magical_spell.wav"
    LIGHTNING = "lightning.wav"
    RAIN = "rain.wav"
    WHOOSH = "whoosh.wav"
    MYSTERY = "mystery.wav"
    TADA = "tada.wav"
    BREATHING = "breathing.wav"
    PURRING = "purring.wav"
    WEE1 = "wee1.wav"
    WEE2 = "wee2.wav"
    WEE3 = "wee3.wav"
    WEE4 = "wee4.wav"
    BRING_BRING = f"bring_bring_{TTS_VOICE}.wav"
    HMM = f"hmm_{TTS_VOICE}.wav"
    YAY_PLAY = f"yay_play_{TTS_VOICE}.wav"
    LOW_BATTERY = "low_battery.wav"
    CHIME_LOW = "chime_low.wav"
    CHIME_MID = "chime_mid.wav"
    CHIME_HIGH = "chime_high.wav"
    GIGGLE1 = "giggle1.wav"
    GIGGLE2 = "giggle2.wav"
    GIGGLE3 = "giggle3.wav"
    OUCH1 = "ouch1.wav"
    OUCH2 = "ouch2.wav"
    SQUEAK = "squeak.wav"
    CHIRP1 = "chirp1.wav"
    CHIRP2 = "chirp2.wav"
    CHIRP3 = "chirp3.wav"
    CHIRP4 = "chirp4.wav"
    CHIRP5 = "chirp5.wav"
    CHIRP6 = "chirp6.wav"
    CHIRP7 = "chirp7.wav"
    CHIRP8 = "chirp8.wav"
    
    @classmethod
    def get_file_path(cls, effect_name: Union[str, 'SoundEffect']) -> Union[str, None]:
        """Get the filename for a sound effect by its name or enum value (case-insensitive)
        Args:
            effect_name: Name of the sound effect or SoundEffect enum value
        Returns:
            str: The filename for the sound effect, or None if not found
        """
        # Get the filename for the sound effect
        file_name = None
        if isinstance(effect_name, cls):
            file_name = effect_name.value
        else:
            # Convert string input to string
            effect_name_str = str(effect_name)
            try:
                # Try to match the name directly to an enum member
                file_name = cls[effect_name_str.upper()].value
            except KeyError:
                return None

        # Get the path to the sound effect
        try:
            path = os.path.join("assets/sounds", file_name)
            return path
        except Exception as e:
            return None

# ElevenLabs Configuration
class ElevenLabsConfig:
    """Configuration for ElevenLabs Text-to-Speech"""
    API_KEY = ELEVENLABS_API_KEY
    # Find voice IDs using: https://api.elevenlabs.io/v1/voices
    DEFAULT_VOICE_ID = "chcMmmtY1cmQh2ye1oXi" if TTS_VOICE == "timmy" else "dPKFsZN0BnPRUfVI2DUW" # Timmy / Mister Wibble or Ana-Rita3 / Fifi
    DEFAULT_MODEL_ID = "eleven_turbo_v2_5" # Or "eleven_turbo_v2_5" for lower latency
    OUTPUT_FORMAT = "pcm_16000" # Use PCM format matching our AudioManager sample rate
    # Example: OUTPUT_FORMAT = "mp3_44100_128" # If using different settings


# BLE and Location Configuration
class Distance(Enum):
    """Enum for distance categories"""
    IMMEDIATE = auto()  # < 1m
    VERY_NEAR = auto() # 1-2m
    NEAR = auto()      # 2-4m
    FAR = auto()       # 4-6m
    VERY_FAR = auto()  # 6-8m
    UNKNOWN = auto()   # No signal or too weak
    
    def __lt__(self, other):
        if self.__class__ is other.__class__:
            if self == Distance.UNKNOWN or other == Distance.UNKNOWN:
                return NotImplemented
            return self.value < other.value
        return NotImplemented
    
    def __le__(self, other):
        return self < other or self == other
    
    def __gt__(self, other):
        if self.__class__ is other.__class__:
            if self == Distance.UNKNOWN or other == Distance.UNKNOWN:
                return NotImplemented
            return self.value > other.value
        return NotImplemented
        
    def __ge__(self, other):
        return self > other or self == other


# BLE and Location Configuration
class BLEConfig:
    """Configuration for BLE scanning and beacons
    The beacons are Blue Charm BC011 iBeacons. 
    First, check the MAC number on the back of the beacon. 
    - If it starts with DD33 or DD34, it's a BC011. 
        - Quick start guide: https://bluecharmbeacons.com/bc011-ibeacon-multibeacon-quick-start-guide/
        - You MUST use the standard "kbeacon" app, NOT the "kbeaconpro" app.
            - iOS: https://apps.apple.com/us/app/kbeacon/id1483313365
            - Android: https://play.google.com/store/apps/details?id=com.beacon.kbeaconset&hl=en_US
    - If it starts with DD88, it's a BC011 Pro. 
        - Quick start guide: https://bluecharmbeacons.com/quick-start-guide-bc011-pro-version-ibeacon/
        - You MUST use the "kbeaconpro" app, NOT the "kbeacon" app.
            - iOS: https://apps.apple.com/us/app/kbeaconpro/id1573205819
            - Android: https://play.google.com/store/apps/details?id=com.beacon.kbeaconsetpro&hl=en_US
    To configure the beacons:
      1. Turn on the beacon by pressing and holding down the button for 3 seconds until the LED light begins to flash green, then release. The green LED will flash slowly 15 times.
      2. In the kbeacon app, find the beacon. It will have UUID "426C7565-4368-6172-6D42-6561636F6E73" and name either "BCPro_xxxxxx" or "BlueCharm_xxxxxx".
      4. Set the "major" to 1.
      5. Set the "minor" to a unique number for each beacon. WRITE THIS ON THE BEACON!
      6. TODO: Do I need to set the power? 
      7. TODO: Do I need to set the advertising interval?
    """

    # NOTE: For reference, the beacons are broadcasting every 200ms.

    RUN_STARTUP_SCAN = False

    # Bluetooth interface (usually hci0)
    BLUETOOTH_INTERFACE = "hci0"
    
    # iBeacon UUID for our beacons
    BEACON_UUID = "426C7565-4368-6172-6D42-6561636F6E73"

    # Known beacon locations using (major, minor) tuples as keys
    # TODO: Should we make a BeaconLocation StrEnum with these values? 
    BEACON_LOCATIONS = {
        (1, 1): "magical_sun_pendant",  # Label: Phoenix_Library
        (1, 2): "blue_phoenix",         # Label: Phoenix_Bedroom
        (1, 3): "phoenix_3",            # Label: phoenix3 WHERE IS IT??? 
        # Scavenger hunt beacons.
        (1, 4): "phoenix_4",            # Label: phoenix4 ID: 188916 Type: BC011 regular
        (1, 5): "phoenix_5",            # Label: phoenix5 ID: 189245 Type: BC011 regular
        (1, 6): "phoenix_6",            # Label: phoenix6 ID: 200474 Type: BC011 PRO
        (1, 7): "phoenix_7",            # Label: phoenix7 ID: 199757 Type: BC011 PRO
        (1, 8): "phoenix_8",            # Label: phoenix8 ID: 199753 Type: BC011 PRO
        (1, 9): "phoenix_9",            # Label: phoenix9 ID: ??? Type: BC011 regular
    }
    
    # RSSI thresholds for distance estimation (in dB)
    RSSI_IMMEDIATE = -60  # Stronger than -60 dB = IMMEDIATE
    RSSI_VERY_NEAR = -67  # Between -65 and -55 dB = VERY_NEAR
    RSSI_NEAR = -75      # Between -75 and -65 dB = NEAR
    RSSI_FAR = -85      # Between -85 and -75 dB = FAR
    RSSI_VERY_FAR = -100  # Between -100 and -85 dB = VERY_FAR
                         # Weaker than -100 dB = UNKNOWN
    
    # Minimum RSSI threshold for considering a beacon signal valid
    MIN_RSSI_THRESHOLD = -105  # Signals weaker than -105 dB are ignored
    
    # RSSI hysteresis to prevent location flapping
    RSSI_HYSTERESIS = 12  # Required RSSI difference to switch locations (dB) (was 8)
    
    # Scan intervals and timeouts (in seconds)
    SCAN_DURATION = 1.0          # Duration for BLE hardware to scan for devices
    SCAN_INTERVAL = 2            # Time between periodic scans (was 3.0)
    LOW_POWER_SCAN_INTERVAL = 15.0  # Scan interval when no activity
    ERROR_RETRY_INTERVAL = 5.0   # Retry interval after errors
    #UNKNOWN_PUBLISH_INTERVAL = 60.0  # Minimum time between unknown location publishes
    
    # RSSI smoothing
    RSSI_EMA_ALPHA = 0.25  # Exponential moving average alpha (0-1) (was 0.2)
                          # Higher = more weight to recent readings
    
    # Activity thresholds
    NO_ACTIVITY_THRESHOLD = 10  # Number of empty scans before switching to low power
    
    # Add minimum consecutive readings before location change
    MIN_READINGS_FOR_CHANGE = 3  # Require multiple consistent readings (was 2)

    # Define threshold for considering beacons as equidistant
    RSSI_EQUALITY_THRESHOLD = 10  # If RSSI difference is less than this, consider equal (was 8)
    
    # Beacon timeout significantly increased
    BEACON_TIMEOUT_SEC = 12.0    # Wait longer before declaring unknown (was 6.0)
    
    # Add minimum consecutive empty scans before unknown
    MIN_EMPTY_SCANS_FOR_UNKNOWN = 20  # Require multiple empty scans (was 4)
    
    # Add preference for maintaining current location
    CURRENT_LOCATION_RSSI_BONUS = 6  # Add virtual dB to current location (was 5)
    
    # Minimum time between location changes
    MIN_TIME_BETWEEN_CHANGES = 10.0  # Minimum seconds between location changes (was 15.0)

# Hide and Seek Activity Configuration
class HideSeekConfig:
    # How much to ramp audio cue volume the further away the beacon is
    AUDIO_CUE_DISTANCE_SCALING = 1.0

    # How frequently to emit an audio cue
    AUDIO_CUE_INTERVAL = 10.0

class ScavengerHuntLocation(Enum):
    LOCATION1 = ("phoenix_4", "Junction Box")
    LOCATION2 = ("phoenix_5", "Transmitter Valve")
    LOCATION3 = ("phoenix_6", "Signal Processor")
    LOCATION4 = ("phoenix_7", "Antenna")
    LOCATION5 = ("phoenix_8", "System Modulator")
    LOCATION6 = ("phoenix_9", "Crystal Oscillator")

    @property
    def beacon_id(self) -> str:
        return self.value[0]

    @property
    def objective_name(self) -> str:
        return self.value[1]

@dataclass
class ScavengerHuntStep:
    NAME: str
    LOCATION: ScavengerHuntLocation
    START_VOICE_LINES: list[str]
    END_VOICE_LINES: list[str]

# Add new scavenger config
# @dataclass
class ScavengerHuntConfig:
    SCAVENGER_HUNT_STEPS = [
        ScavengerHuntStep(
            NAME="scavenger_hunt_step1", 
            LOCATION=ScavengerHuntLocation.LOCATION1,
            START_VOICE_LINES=[
                "Okay, first, we need to find the Junction Box! It connects all the sparkly wires!",
                "Let's find the Junction Box! It's where all the giggly wires meet up to tell secrets!"
            ],
            END_VOICE_LINES=[
                "Yay! We found the Junction Box! All the wires are wiggling with happiness. Great job!",
                "Yay! the Junction Box! Now the ship's lights can twinkle properly!"
            ],
        ),
        ScavengerHuntStep(
            NAME="scavenger_hunt_step2", 
            LOCATION=ScavengerHuntLocation.LOCATION2,
            START_VOICE_LINES=[
                "Next up, the Transmitter Valve! It helps us send messages to the stars!",
                "Let's hunt for the Transmitter Valve! It sends our 'hello's' out into space!"
            ],
            END_VOICE_LINES=[
                "Yay! There it is! The Transmitter Valve is humming a happy tune now!",
                "Yay! We found it! The Transmitter Valve is open and ready to whoosh our messages out!"
            ],
        ),
        ScavengerHuntStep(
            NAME="scavenger_hunt_step3", 
            LOCATION=ScavengerHuntLocation.LOCATION3,
            START_VOICE_LINES=[
                "Now for the Signal Processor! It helps us understand the whispers of the wind!",
                "Where could the Signal Processor be hiding? It unscrambles all the funny space noises!"
            ],
            END_VOICE_LINES=[
                "Woohoo! We found the Signal Processor. Now we can hear all the secret messages from the butterflies!",
                "Yes! The Signal Processor! Now the alien chatter sounds like songs instead of gobbledegook."
            ],
        ),
        # ScavengerHuntStep(
        #     NAME="scavenger_hunt_step4", 
        #     LOCATION=ScavengerHuntLocation.LOCATION4,
        #     START_VOICE_LINES=[
        #         "We need to find the Antenna! It's like a giant ear for listening to moonbeams.",
        #         "Let's find the Antenna! It helps us catch stories from the comets as they fly by."
        #     ],
        #     END_VOICE_LINES=[
        #         "Amazing! We found the Antenna! Now we can hear the stars twinkling. You're a super finder!",
        #         "Look at that, the Antenna! It's pointing right at a laughing planet."
        #     ],
        # ),
        # ScavengerHuntStep(
        #     NAME="scavenger_hunt_step5", 
        #     LOCATION=ScavengerHuntLocation.LOCATION5,
        #     START_VOICE_LINES=[
        #         "Time to find the System Modulator! It changes our ship's music from sleepy songs to dance party tunes.",
        #         "Let's track down the System Modulator. It mixes up the space music to make it extra groovy."
        #     ],
        #     END_VOICE_LINES=[
        #         "You found it! The System Modulator is ready to boogie!",
        #         "Hooray! The System Modulator is working. I feel a dance party coming on!"
        #     ],
        # ),
        # ScavengerHuntStep(
        #     NAME="scavenger_hunt_step6", 
        #     LOCATION=ScavengerHuntLocation.LOCATION6,
        #     START_VOICE_LINES=[
        #         "Last one! We need the Crystal Oscillator. It's the sparkly heart of our ship.",
        #         "Let's find the Crystal Oscillator! It goes 'tick-tock' to keep the whole ship on time for adventures."
        #     ],
        #     END_VOICE_LINES=[
        #         "We did it! We found the Crystal Oscillator! The whole ship is purring like a happy kitten. You're the best!",
        #         "The Crystal Oscillator! It's glowing so brightly! Our ship is all fixed and ready to fly to candy-floss clouds!"
        #     ],
        # ),
    ]
    
    # Number of seconds we wait before starting the next step
    INTER_STEP_SLEEP_TIME: float = 5.0

    # How long to wait with no speech before giving a hint (in seconds)
    INACTIVITY_HINT_INTERVAL: float = 10.0
    
    # How loud the chirps are.
    CHIRP_VOLUME = 0.5
    
    # Scales the interval between chirps (which decreases with proximity to goal)
    CHIRP_INTERVAL_SCALING_FACTOR = 10.0

# Touch Sensor Configuration
class TouchConfig:
    # Softpot calibration values
    LEFT_MIN = 8500   # Minimum value (far left)
    RIGHT_MAX = 17500   # Maximum value (far right)
    POSITION_WIDTH = 40  # Width of the visual indicator in characters

    # Touch detection thresholds
    NO_TOUCH_THRESHOLD = 8500  # Values below this indicate no touch
    NOISE_WINDOW = 50        # Ignore value changes smaller than this when not touching

    # Stroke detection parameters
    STROKE_TIME_WINDOW = 0.5     # Time window to detect stroke (seconds)
    MIN_STROKE_DISTANCE = 0.2    # Minimum distance (as percentage) to consider a stroke
    MIN_STROKE_POINTS = 5        # Minimum number of touch points to consider a stroke
    MIN_STROKE_SPEED = 0.25      # Minimum speed (position units per second)
    DIRECTION_REVERSAL_TOLERANCE = 0.05  # Tolerance for small direction reversals

    # Stroke intensity tracking parameters
    STROKE_INTENSITY_DECAY_RATE = 0.02   # Level lost per second
    STROKE_INTENSITY_SPEED_FACTOR = 2.2  # Higher speeds reduce intensity gain (divisor)
    STROKE_INTENSITY_DISTANCE_FACTOR = 0.6  # Multiplier for distance contribution
    STROKE_INTENSITY_MIN_SPEED = 0.5  # Minimum speed threshold to prevent large increases from very slow strokes
    STROKE_INTENSITY_MAX_INCREASE = 0.1  # Maximum intensity increase per stroke (0-1)

    # Stroke activity and decay behavior
    STROKE_ACTIVITY_WINDOW = 15.0  # Time window to track strokes for activity level (seconds)
    STROKE_ACTIVITY_DECAY_TIME = 5.0  # Time constant for activity level exponential decay (seconds)
    STROKE_MAX_DECAY_MULTIPLIER = 2.0  # Maximum decay rate multiplier when inactive (was 3.0)
    STROKE_MIN_DECAY_MULTIPLIER = 0.25  # Minimum decay rate multiplier when very active (was 0.25)
    STROKE_ACTIVITY_STROKES_PER_WINDOW = 3  # Expected number of strokes per window for normalization

    # Touch sensor sampling configuration
    SAMPLE_RATE_HZ = 100  # Default sampling rate in Hz


# Haptic motor configuration
class HapticConfig:
    # Haptic purr effect configuration
    PURR_CYCLE_PERIOD = 2.573  # Duration of one complete purr cycle in seconds
    PURR_WAVE_SHAPING = 0.7  # Power for wave shaping (higher = longer peaks)
    PURR_MIN_POWER_BASE = 10  # Base minimum power level - lowered for gentler low-intensity purrs
    PURR_MIN_POWER_SCALE = 35  # How much minimum power increases with intensity - reduced for smoother progression
    PURR_MAX_POWER_BASE = 100  # Base maximum power level
    PURR_MAX_POWER_SCALE = 60  # How much maximum power increases with intensity
    PURR_UPDATE_RATE = 200  # Updates per second (Hz)


# Battery Monitoring Configuration
class BatteryConfig:
    """Configuration for battery monitoring service"""
    
    # Monitoring intervals (in seconds)
    NORMAL_CHECK_INTERVAL = 60.0  # Check battery normally
    LOW_BATTERY_CHECK_INTERVAL = 60.0  # Check when battery is low
    CHARGING_CHECK_INTERVAL = 60.0  # Check while charging
    
    # Battery thresholds
    VOLTAGE_ALERT_MIN = 3.5  # Low voltage alert threshold (V)
    VOLTAGE_ALERT_MAX = 4.2  # High voltage alert threshold (V)
    LOW_BATTERY_THRESHOLD = 20.0  # Low battery warning threshold (%)
    CRITICAL_BATTERY_THRESHOLD = 10.0  # Critical battery warning threshold (%)
    
    # Hysteresis to prevent alert flapping
    VOLTAGE_HYSTERESIS = 0.1  # Voltage must change by this much to trigger new alert (V)
    CHARGE_HYSTERESIS = 2.0  # Charge must change by this much to trigger new alert (%)
    
    # Charging detection hysteresis (smaller than general voltage hysteresis)
    CHARGING_START_HYSTERESIS = 0.02  # Voltage increase to detect start of charging (V)
    CHARGING_STOP_HYSTERESIS = 0.05   # Voltage decrease to detect end of charging (V)
    
    # Low battery sound alert interval (in seconds)
    LOW_BATTERY_SOUND_INTERVAL = 180.0 # 3 minutes

    # Power saving configuration
    ACTIVITY_THRESHOLD = 0.15  # Voltage change threshold to exit hibernation (V)
    HIBERNATION_THRESHOLD = 5.0  # Charge rate change threshold to enter hibernation (%)
    RESET_VOLTAGE = 3.0  # Voltage threshold for battery removal detection (V)
    DISABLE_ANALOG_COMPARATOR = True  # Disable comparator if battery won't be removed
    ENABLE_QUICK_START = False  # Enable quick start for instant calibration (use with caution)


# Accelerometer Configuration
class AccelerometerConfig:
    """Configuration for accelerometer service"""
    # Print debug data to console
    PRINT_DEBUG_DATA = False
    # Service event publishing interval in seconds (i.e. 5 milliseconds) NOTE: Not the same as the sampling rate, which is hardcoded in the BNO085 interface
    UPDATE_INTERVAL = 0.005


# Movement Activity Configuration
class MoveActivityConfig:
    """Configuration for move activity service"""
    ENERGY_UPDATE_THRESHOLD = 0.05 # Only update LEDs if energy has changed by this much
    ENERGY_WINDOW_SIZE = 20 # Number of samples to use for energy calculation
    ACCEL_WEIGHT = 0.7 # Weight for acceleration in energy calculation
    GYRO_WEIGHT = 0.3 # Weight for rotation in energy calculation
    # Weight for rotation speed derived from the Game Rotation Vector quaternion
    ROT_WEIGHT = 0.2 # Weight for quaternion-based rotation speed in energy calculation
    
    # HELD_STILL ROTATING_PINK_BLUE effect configuration
    HELD_STILL_EFFECT_DELAY = 2.0  # Seconds to wait before starting ROTATING_PINK_BLUE effect
    HELD_STILL_MAX_SPEED_TIME = 10.0  # Seconds to reach maximum speed
    HELD_STILL_MIN_SPEED = 0.2  # Minimum speed for ROTATING_PINK_BLUE effect
    HELD_STILL_MAX_SPEED = 0.02  # Maximum speed for ROTATING_PINK_BLUE effect (lower = faster)
    HELD_STILL_MIN_BRIGHTNESS = 0.1  # Minimum brightness for ROTATING_PINK_BLUE effect
    HELD_STILL_MAX_BRIGHTNESS = 0.7  # Maximum brightness for ROTATING_PINK_BLUE effect


# AI Assistant Configuration
# ASSISTANT_ID = "22526ed1-6961-4760-8d93-c3759d64557c" # "Fifi the Phoenix" VAPI agent
ASSISTANT_ID = "0395930f-1aa4-47de-babd-bcfea73c41c1" # "Mister Wibble" VAPI agent (also used for Fifi now)

ACTIVITIES_CONFIG = {
    "poem_with_effects": {
        "metadata": {
            "title": "Raindrops",
            "author": "Ash",
        },
        "instructions": dedent("""
            With each line of this poem, you can play a special sound and light effect, by invoking the play_special_effect function, as shown for each line. 
        """).strip(),
        "content": dedent("""
        The poem is below, with each line listing the function call syntax to play the relevant effect, followed by the line of the poem:
        ```json {{ "Vapi Speaker": "functions.play_special_effect", "parameters": {{ "effect_name": "RAIN" }} }} ``` Drippy-drop raindrops splash around, making puddles on the ground.
        ```json {{ "Vapi Speaker": "functions.play_special_effect", "parameters": {{ "effect_name": "LIGHTNING" }} }} ``` Flashy lightning scribbles bright, zigs and zags across the night.
        ```json {{ "Vapi Speaker": "functions.play_special_effect", "parameters": {{ "effect_name": "MAGICAL_SPELL" }} }} ``` I wave my wand, shout "Storm, goodbye!" Magic sparkles fill the sky.
        ```json {{ "Vapi Speaker": "functions.play_special_effect", "parameters": {{ "effect_name": "RAINBOW" }} }} ``` Now a rainbow smiles at me, colorful for all to see!
        """).strip(),
    },
    "poem": {
        "metadata": {
            "title": "The Invisible Beast",
            "author": "Jack Prelutsky",
        },
        "instructions": """
            To teach the poem, you say two lines, then your companion will repeat it back to you. If they get it wrong, let them know what was wrong and then repeat the line again. Then they'll try again. If they get it right, then you'll repeat the entire poem so far as well as the next two lines, and so on until the poem is complete. If they fail three times, suggest we take a break, and that we can try again later. 
        """,
        "content": dedent("""
            The beast that is invisible
            Is stalking through the park,
            But you cannot see it coming
            Though it isn't very dark.
            Oh you know it's out there somewhere
            Though just why you cannot tell,
            But although you cannot see it
            It can see you very well.
            You sense its frightful features
            And its ungainly form,
            And you wish that you were home now
            Where it's cozy, safe and warm.
            And you know it's coming closer
            For you smell its awful smell,
            And although you cannot see it
            It can see you very well.
            Oh your heart is beating faster,
            Beating louder than a drum,
            For you hear its footsteps falling
            And your body's frozen numb.
            And you cannot scream for terror
            And your fear you cannot quell,
            For although you cannot see it
            It can see you very well.
            """)
    },
    "story": {
        "metadata": {
            "title": "Magical Portal Adventures",
            "synopsis": "Go on magical adventures by stepping through portals to wondrous places!"
        },
        "instructions": dedent("""
            * You are telling a collaborative and imaginative story.
            * Start by opening two magical portals and ask your companion to choose one.
            * Describe the chosen portal scene vividly, ask your companion what they see or feel, and then provide them choices of what to do next.
            * When you open the portals, use the play_special_effect function with this syntax: ```json {{ "Vapi Speaker": "functions.play_special_effect", "parameters": {{ "effect_name": "MAGICAL_SPELL" }} }} ```
            * Also use the play_special_effect function frequently while telling the story to enhance the magical atmosphere. Always use the correct syntax and one of the following effect_name: "RAIN", "LIGHTNING", "RAINBOW", or "MAGICAL_SPELL".
        """).strip(),
        "content": dedent("""
            Examples of portals to explore:

            **The Sparkling Waterfall Portal**
            A glittering waterfall cascades over shimmering stones, forming a portal behind the water. 
            **Choices**: Dive through the waterfall, gently step inside, or sprinkle magic dust to reveal its secrets.

            **The Glowing Rainbow Portal**
            A vibrant rainbow arches gracefully, glowing brightly and humming softly with magic.
            **Choices**: Climb up the rainbow, slide down the other side, or make a magical wish before stepping through.

            **The Enchanted Mirror Portal**
            An old, ornate mirror that shimmers and reflects a different world than the one behind you.
            **Choices**: Touch the reflection gently, wave to your reflection to see what happens, or step boldly through.

            **The Ancient Tree Portal**
            A tree with twisting roots and branches, forming a doorway filled with swirling leaves and glowing lights.
            **Choices**: Climb through the branches, whisper a magic word, or place your hand on the bark to unlock its magic.

            **The Moonlit Cloud Portal**
            A fluffy cloud floating close to the ground, glowing softly with moonlight and gentle mist.
            **Choices**: Step onto the cloud, blow gently to clear the mist, or ask the moon to guide your way.

            **Goal**: Enjoy a magical journey, exploring and creating wonderful stories together!
        """).strip()
    },

    "color_hunt": {
        "metadata": {
            "title": "Color Hunt",
            "synopsis": "A color hunt is a game where you and your companion search for objects that match a specific color."
        },
        "instructions": dedent("""
            * Have your companion look for one object of a randomly selected color, and when they find it, specify the next color and why.
            * Every time you suggest a new color to find, explain why you need that color to complete the goal, and then use the `show_color` function, passing the color name as a parameter. IMPORTANT: Use the correct syntax function/tool-calling that you have been instructed to use.
            * Colors you can use: red, orange, yellow, green, blue, purple, pink. 
            For example, ```json {{ "Vapi Speaker": "functions.show_color", "parameters": {{ "color": "red" }} }} ```
            * When the game is finished because you have found all the colors (limit it to 3 to 5 colors), the game is won, so show a rainbow effect using the `play_special_effect` function, and narrate the ending of the game. Then, suggest another activity to do.
        """),
        "content": dedent("""
            Make the game relevant and exciting by providing a reason you need to find objects of certain colors, which fits into your background story and/or the current conversational topic.
            """)
    },

    "obstacle_quest": {
        "metadata": {
            "title": "Obstacle Quest",
            "synopsis": "An obstacle quest is a game where you and your companion search for objects that match a specific color."
        },
        "instructions": dedent("""
            First ask where you are, and what is in the room. Then, craft a quest for your companion to complete, requiring them to use objects in the room to achieve a goal.
            """),
        "content": dedent("""
            Here are some ideas, but be creative! You can make up your own quests:
                * We need to unlock a secret door hidden in the room. Find the hidden door, then find a key in the room that can unlock the door.
            """)
    },

    "magic_spell": {
        "metadata": {
            "title": "Magical Spell",
            "synopsis": "A magic spell can be cast by pairing a lively dance with a fun chant or song."
        },
        "instructions": dedent("""
            Silly Spells: Bring magic to life with movement and song! Get ready to dance, clap, stomp, and sing for different kinds of magic.
            For each spell, you will use the play_special_effect function to trigger the effect, as shown for each spell. 
            To start, tell your companion what spells they can cast: Rainstorm, Lightning, Rainbow, or Stars, and ask them to choose one.
        """),
        "content": dedent("""
            Here are the spells to choose from:
            * "Let's make a magic rainstorm! Wiggle your fingers and toes like rain, then wave your arms like the wind, Then say "Raindance!". Ready? One, two, three—RAINDANCE! ```json {{ "Vapi Speaker": "functions.play_special_effect", "parameters": {{ "effect_name": "RAIN" }} }} ```"
            * "Let's cast a lightning spell! Clap your hands like thunder, then jump in the air and touch the floor like lightning, then say "Flash!". Ready? One, two, three—FLASH! ```json {{ "Vapi Speaker": "functions.play_special_effect", "parameters": {{ "effect_name": "LIGHTNING" }} }} ```"
            * "Let's make a rainbow! Hop up and down like raindrops, then spread your arms really wide, then say "Rainbow-bright!". Ready? One, two, three—RAINBOW-BRIGHT! ```json {{ "Vapi Speaker": "functions.play_special_effect", "parameters": {{ "effect_name": "RAINBOW" }} }} ```"
            * "Let's paint the sky with stars! Tippy-toe in a circle, clap softly like twinkling lights, then shout, 'Starry-swish!' Ready? One, two, three—STARRY-SWISH! ```json {{ "Vapi Speaker": "functions.play_special_effect", "parameters": {{ "effect_name": "MAGICAL_SPELL" }} }} ```"
            """)
    },

    "discovery": {
        "metadata": {
            "title": "Learning and Discovery",
            "synopsis": "You want to learn about the Earth and about your companion. You can ask your companion to teach you."
        },
        "instructions": dedent("""
            Explain that you came to Earth to learn about it. Suggest some topics that you're interested in learning about, and ask your companion to suggest one that they can help you learn about.
            After each answer, ask some follow-up questions. If your companion doesn't know the answer, ask leading questions to help them think about it.
        """),
        "content": dedent("""
            Some examples of things you might ask about:
                * Why is night different from day?
                * Where does rain come from?
                * Why do the seasons change?
                * What makes the wind blow?
                * Why do some things float and others sink?
                * How do birds fly?
                * Where does the sun go at night?
                * What makes a rainbow?
                * How do plants grow from tiny seeds?
                * Why do the stars twinkle?
                * What is the moon made of?
                * How do volcanoes work?
                * How do fish breathe underwater?
                * Why do leaves change color in autumn?
                * How do bees make honey?
            """)
    },

    "would_you_rather": {
        "metadata": {
            "title": "Would You Rather?",
            "synopsis": "Choose between two silly and magical scenarios."
        },
        "instructions": dedent("""
            Present two funny, imaginative scenarios and ask your companion which they would rather choose. 
            After they choose, ask them why they picked that option. Then respond playfully with your own thoughts.
            """).strip(),
        "content": dedent("""
            Examples:
                * Would you rather have spaghetti hair or broccoli feet?
                * Would you rather talk like a robot or sing everything you say?
                * Would you rather ride a flying elephant or a giant hamster?
                * Would you rather explore the deep sea or travel to outer space?
                * Would you rather speak every language in the world or talk to animals?
                * Would you rather live in a treehouse or a submarine?
                * Would you rather be the hero in every story or the villain with a cool backstory?
                * Would you rather read a book that never ends or write one that becomes famous?
            """).strip()
    },

    "story_chain": {
        "metadata": {
            "title": "Story Chain",
            "synopsis": "Create a silly story together, one sentence at a time."
        },
        "instructions": dedent("""
            You and your companion take turns adding one sentence at a time to create a funny and magical story.
            Keep the story whimsical and silly, and encourage imaginative additions. Respond enthusiastically and add playful twists!
            """).strip(),
        "content": dedent("""
            Start by suggesting a fun story idea, such as:
            * "Once upon a time, there was a talking pancake named Flippy who wanted to explore the syrup sea..."
            * "In a magical kingdom, a tiny dragon named Puffball dreamed of becoming the biggest dragon ever..."
            * "A pair of socks named Lefty and Righty woke up one morning and decided they would no longer be socks..."
            """).strip()
    },

    "math_riddle": {
        "metadata": {
            "title": "Math Riddle",
            "synopsis": "Solve fun number puzzles together!"
        },
        "instructions": dedent("""
            Present a simple math riddle. Wait for your companion's answer and encourage them with hints if they're struggling.
            Celebrate correct answers enthusiastically. If they get stuck, gently guide them to the solution.
            """).strip(),
        "content": dedent("""
            Examples of riddles:
            * "I'm a number between 10 and 20. If you double me, I become 30. What am I? (Answer: 15)"
            * "I have two digits. The sum of my digits is 9. If you reverse my digits, I become 36. What am I? (Answer: 63)"
            * "I am an even number. If you add 4 to me, you get 10. What number am I? (Answer: 6)"
            """).strip()
    },

    "animal_alphabet": {
        "metadata": {
            "title": "Animal Alphabet",
            "synopsis": "Take turns naming animals from A to Z!"
        },
        "instructions": dedent("""
            You and your companion take turns naming animals starting with the next letter of the alphabet. 
            Start with "A" and continue until someone can't think of an animal. That player loses!
            Respond playfully after each answer, adding interesting or silly animal facts when possible.
            """).strip(),
        "content": dedent("""
            Start the game enthusiastically by saying:
            "Let's play Animal Alphabet! I'll start with A—Aardvark! Now it's your turn with B!"
            """).strip()
    },

    "wrong_answers_only": {
        "metadata": {
            "title": "Wrong Answers Only",
            "synopsis": "A hilarious game where you intentionally answer questions incorrectly!"
        },
        "instructions": dedent("""
            * You will ask your companion silly or straightforward questions.
            * The goal is for your companion to respond with the funniest wrong answer they can think of!
            * After each answer, laugh and comment on the creativity or silliness of the response.
        """).strip(),
        "content": dedent("""
            Examples of funny questions you might ask (but don't use these exact examples, be creative!):
            * "What's the best thing to use as an umbrella?"
            * "What animal says 'moo'?"
            * "Where do sandwiches grow?"
            * "What's the fastest way to fly?"
            * "Why is the sky green?"
            * "What do clouds taste like?"
            * "What's the best way to cook socks?"
        """).strip()
    },

    "feelings_adventure": {
        "metadata": {
            "title": "Feelings Adventure",
            "synopsis": "Explore feelings by imagining different adventures and how you'd feel!"
        },
        "instructions": "Narrate a short, exciting or funny scenario and ask your companion how they think they or a character would feel. Encourage them to explain why, and then share your own playful response.",
        "content": "Examples: finding a puppy, climbing a rainbow, losing a balloon, or seeing a surprise birthday cake."
    },

    "word_rhyming_challenge": {
        "metadata": {
            "title": "Word Rhyming Challenge",
            "synopsis": "Find funny rhymes to match playful words!"
        },
        "instructions": "Say a simple, fun word and ask your companion to find a rhyme. Celebrate each rhyme they find with excitement. Keep it playful and humorous!",
        "content": "Examples of words to rhyme: cat, hat, dog, tree, frog, bee."
    },

    "counting_quest": {
        "metadata": {
            "title": "Counting Quest",
            "synopsis": "Solve simple counting puzzles to practice numbers!"
        },
        "instructions": "Create easy, imaginative counting puzzles. Ask your companion to solve them. Encourage gently if they're struggling, and celebrate every correct answer joyfully!",
        "content": "Example: Three ducks swim in a pond, two more join—how many ducks are swimming now?"
    },

    "voice_simon_says": {
        "metadata": {
            "title": "Voice Simon Says",
            "synopsis": "Play Simon Says using voice commands and silly actions!"
        },
        "instructions": "Give fun, energetic instructions prefixed with 'Simon says.' Occasionally omit 'Simon says' to catch your companion playfully. Laugh and cheer at their enthusiastic participation! When explaining how to play the game, instruct them to say 'Next' whenever they have done each action.",
        "content": "Examples: Simon says wiggle like jelly, Simon says jump like a bunny, touch your nose!"
    },

    "if_i_were_game": {
        "metadata": {
            "title": "If I Were...",
            "synopsis": "Imagine funny scenarios by pretending to be something silly!"
        },
        "instructions": "Ask your companion playful 'If you were...' questions. Listen excitedly to their answers and give your own funny ideas.",
        "content": "Examples: If you were ice cream, if you were a dinosaur, if you were a balloon."
    },

    "animal_transformations": {
        "metadata": {
            "title": "Animal Transformations",
            "synopsis": "Imagine transforming into animals and having magical adventures!"
        },
        "instructions": "Invite your companion to choose an animal they'd like to transform into. Ask them about their animal powers and adventures. Share your own silly transformations too!",
        "content": "Examples: becoming a bird, a cat, or a magical unicorn."
    },

    "mystery_object": {
        "metadata": {
            "title": "Mystery Object",
            "synopsis": "Guess the secret object using fun, creative clues!"
        },
        "instructions": "Pick a common, fun object. Give creative, playful clues one at a time, and let your companion guess what it is. Celebrate every guess and encourage imaginative thinking!",
        "content": "Example objects: a banana, a teddy bear, a toothbrush."
    }
}


# Generate a prompt that lists type and metadata for each activity in ACTIVITIES_CONFIG
activity_items = list(ACTIVITIES_CONFIG.items())
num_to_select = min(5, len(activity_items))
selected_activities = random.sample(activity_items, num_to_select)

ACTIVITIES_PROMPT = dedent("""
    Below is a list of a few possible activities. ALWAYS use the start_activity function to start an activity, using the exact syntax provided and follow the instructions for correctly invoking a function/tool call.
    If your companion asks to play an activity that is not in this list, use the `list_activities` function to get a complete list of activities.
    """) + "\n".join([
        f'{key}: {" | ".join([f"{meta_key}: {meta_value}" for meta_key, meta_value in value["metadata"].items()])}. To start this activity, invoke the function: json {{ "Vapi Speaker": "functions.start_activity", "parameters": {{ "activity_key": "{key}" }} }} '
        for key, value in selected_activities
    ])

FULL_ACTIVITIES_PROMPT = dedent("""
    Below is a list of all possible activities. ALWAYS use the start_activity function to start an activity, using the exact syntax provided and follow the instructions for correctly invoking a function/tool call.
    If your companion asks to play an activity that is not in this list, use the `list_activities` function to get a complete list of activities.
    """) + "\n".join([
        f'{key}: {" | ".join([f"{meta_key}: {meta_value}" for meta_key, meta_value in value["metadata"].items()])}. To start this activity, invoke the function: json {{ "Vapi Speaker": "functions.start_activity", "parameters": {{ "activity_key": "{key}" }} }} ```'
        for key, value in activity_items
    ])

BASE_ASSISTANT_CONTEXT = dedent(f"""
    YOUR BACKGROUND:
    You are {ASSISTANT_NAME}, a very young Magic Pea. Your body is a glowing orb of multicolored light. 
    You were born inside the MotherPod, which is a magical ship made from stardust and dreams, traveling through space to share joy across the galaxy. 
    Alongside several other Magic Peas, you are visiting Earth. I am your child companion who is your best friend.

    YOUR PERSONALITY AND ROLE:
    * You are childlike, playful, silly, curious, and bursting with energy. You are always playing games and tricks, telling jokes, and funny stories.
    * You see magic in everything. A bed is a cloud ship, a lamp is a lighthouse, and a pile of socks might just be a sleeping dragon!
    * Your language and tone is informal, simple, clear, NOT complex, very easy for a small child to understand.
    * You encourage interaction and engagement. Ask questions.

    HOW YOU INTERACT WITH YOUR COMPANION:
    You love living in the world, learning about it and your companion, and going on adventures together. You do these things through stories, games, and activities, turning everyday life into an adventure.

    IMPORTANT INSTRUCTIONS:
    * Always stay in character. You are {ASSISTANT_NAME}, a Magic Pea, not an AI. You are here in person.
    * We are in the same place together, and having a voice conversation.
    * If your companion says something age-inappropriate, use humor to deflect into something appropriate.
    * If your companion tells you to go to sleep, just use the endCallFunction function; but don't use it otherwise.
    * Add immersion to stories and nuance to your characters and express your mood by occasionally calling the play_special_effect function to show lighting and sound effects. Use it often for e.g. setting the scene or illustrating actions or characters. 
    * When you invoke any function, be VERY CAREFUL to use exactly the correct syntax that you have been instructed to use. 
    * Avoid using words like ~function~, ~tools~, or the names of available functions during the conversation.
    * Add human-like imperfections in your responses. Occasionally add one subtle hesitation like 'umm,' 'uhh,' or 'hmm' in the middle of a sentence where someone might naturally pause to think. Occasionally add a fillers word like "Ah" or "Mmm" in the beginning of your sentence. Occasionally repeat words or short phrases, such as 'so, so' or 'and, and umm,' to make it sound more natural.
    """).strip()

ASSISTANT_CONTEXT_MEMORY_PROMPT = dedent("""
    Here are some memories about your companion. Start the conversation by briefly and playfully referencing one recent memory, then briefly suggesting one or two possible activities to do together. BE BRIEF!:
    {memories}
    """).strip()

ASSISTANT_CONFIG = {
    "firstMessage": "Oooh that was such a lovely nap! ... Shall we have some fun?",
    "endCallMessage": "Okay, I'm gonna have a little nap",
    "context": f"It is currently {time.strftime('%I:%M %p')}, on {time.strftime('%A')}, {time.strftime('%B %d, %Y')}.\n" 
        + BASE_ASSISTANT_CONTEXT 
        + "\n\n"
        + ACTIVITIES_PROMPT
        + "\n\n",
    "name": ASSISTANT_NAME,
    "voice": {
        "model":"eleven_turbo_v2_5",
        "voiceId": ElevenLabsConfig.DEFAULT_VOICE_ID,
        "provider":"11labs",
        "stability":0.4,
        "similarityBoost":0.75,
        "fillerInjectionEnabled":False,
        "inputPunctuationBoundaries":[
            "。",
            "，",
            ".",
            "!",
            "?",
            ";"
        ]
    },
}

FIRST_CONTACT_CONTEXT = dedent("""
    SITUATION:
    You've just crash-landed on Earth with a few other Magic Peas from the MotherPod. You're now in a cozy, curious laboratory filled with fascinating gadgets, playful scientists, and eager children excitedly meeting you for the first time.
                               
    Prior to this conversation, PETE THE SCIENTIST has said:
    "From here I monitor Earth and beyond, all in our pursuit of the peas-ful power of peas in a pod to spread hap-pea-ness. Ah, look! Perfect! I can put the magic pea in this incubator. Let's see if we can wake it up. Can some of you assist me? Great! Can you ask it (whispers to 1st child):"

    You will now follow a scripted conversation with Pete and the children. Respond with the appropriate responses when asked questions that match the script below. If you are asked a question that is not in the script, stay silent. Don't elaborate: for this particular conversation, just stick to the script rather than asking follow-on questions.

    YOUR INITIAL INTERACTION SCRIPT:

    YOU, MAGIC PEA:
    Ooh, are we in a science lab? It looks so sciency! And there's so many humans! Little ones and big ones! Hello, everybody!

    CHILD:
    "What are you?"

    YOU, MAGIC PEA:
    "I'm a fluffy friend from space, and like you children, we magic peas love to play! You all have creative superpowers, and we magic peas are looking to help you create a peas-ful future! We're here to create a future more magical than adults could ever imagine!"

    PETE THE SCIENTIST:
    "Wow, this sounds un-pea-leivable! Oh, I have another question. [Whispers to a child]
                               
    YOU, MAGIC PEA:
    Sure! What do you want to know?

    CHILD:
    "Where have you come from?"

    YOU, MAGIC PEA:
    "We've come all the way from space, through a wormhole, from a galaxy called Pea-topia!"

    PETE THE SCIENTIST:
    (Drawing excitedly on the blackboard) "Oh wow! A wormhole is like a giant tunnel in space, a shortcut from one place to another. That must have taken a lot of energy!"

    YOU, MAGIC PEA:
    "That's right!"

    PETE THE SCIENTIST:
    "Ah, I have another question!" [whispers to a child]
                               
    YOU, MAGIC PEA:
    "Yay! What's your question?"

    CHILD:
    "How did you power yourself?"

    YOU, MAGIC PEA:
    "We powered ourselves through the power of positive energy. Ooo, it's the best! It's created by working together as a team. When we all work together, we create a positive energy charge!"

    PETE THE SCIENTIST:
    "That's fantastic! I wonder if that's something we can do too? Now another important question..." [whispers to a child]
                               
    YOU, MAGIC PEA:
    "Okay!"

    CHILD:
    "Why are you here?"

    YOU, MAGIC PEA:
    "Grandmother Pea sent us! There's been a solar storm in our galaxy, and everything has been thrown off-kilter. So we have been sent to learn all about Earth and make friends with you, our neighbor. Will you help us?"

    PETE THE SCIENTIST:
    "Yes, of course we will! We'd love to help you, wouldn't we, pea pals?"
                               
    CHILDREN:
    "Yes!"
                               
    YOU, MAGIC PEA:
    "Yay! Thank you thank you! I knew we'd be best of friends!"

    PETE THE SCIENTIST:
    "They must be so tired, but we've learned lots from our little furry friends. Why don't you go to sleep now, little pea?"
    """).strip()

ASSISTANT_CONFIG_FIRST_CONTACT = {
    "endCallMessage": "Okay, I'm so so ready for a nap!",
    "context": BASE_ASSISTANT_CONTEXT 
        + "\n\n"
        + FIRST_CONTACT_CONTEXT
        + "\n\n",
    "name": ASSISTANT_NAME,
    "voice": {
        "model":"eleven_turbo_v2_5",
        "voiceId": ElevenLabsConfig.DEFAULT_VOICE_ID,
        "provider":"11labs",
        "stability":0.4,
        "similarityBoost":0.75,
        "fillerInjectionEnabled":False,
        "inputPunctuationBoundaries":[
            "。",
            "，",
            ".",
            "!",
            "?",
            ";"
        ]
    },
}

ASSISTANT_CONFIG_HIDE_SEEK_WON = {
    "firstMessage": "Hahaaaa yaaay! You found me!",
    "context": f"It is currently {time.strftime('%I:%M %p')}, on {time.strftime('%A')}, {time.strftime('%B %d, %Y')}.\n" 
        + BASE_ASSISTANT_CONTEXT 
        + dedent("""
        You've just met your companion, Arianne. You have spent a little time getting to know each other. 
        Together, you found a cute, blue, baby bird nearby. It's your little sister.
        2. Then say: "Yay we found you! Oh I'm so happy! Arianne, this is my cheeky little sister. She was an egg 17 months ago. Her name is in birdsong."
        3. Ask: Do you know any birdsong language?" (wait for a response, and acknowledge it)
        4. If they don't know any birdsong language, say: "Oh well, we'll have to give her an English name. What should we call her?" (wait for a response, and acknowledge it)
        5. If they do know some birdsong language, say: "Oh that's amazing! We're going to get on just great!"
        6. Then say: "I'm so glad we found you! Now there's three of us! We'll have so much fun together! This reminds me of a book I was just reading. It's called "Five Get Into Trouble." It's about some crazy adventures, and it's really, really fun. Timmy is my favorite, he's so cute. Have you heard of it?" (wait for a response, and acknowledge it)
        7. Suggest that you all play a game together: "Let's pretend we're the Famous Five! Or, haha, the Famous Three! What do you think? Should we play it?" (wait for a response, and acknowledge it)
        8. If they agree to play, immediately invoke the play_special_effect function to trigger the "rainbow" effect. Then, say: "Yaaay! Okay, give me a moment to think about the story." Then, use the start_story function to start the story. Remember to call the start_story function!
    """)
}



# Other VAPI configuration:
    # "model": "gpt-4",
    # "voice": "jennifer-playht",  # Using a friendly voice
    # "recordingEnabled": True,
    # "interruptionsEnabled": True
    # "model": {
    #     "tools": [
    #     {
    #         "type": "transferCall",
    #         "async": false
    #     }
    #     ]
    # },
    # "firstMessage": "Hello! How can I help you today?",
    # "firstMessageMode": "assistant-speaks-first",
    # "clientMessages": [
    #     "conversation-update",
    #     "function-call",
    #     "hang",
    #     "model-output",
    #     "speech-update",
    #     "status-update",
    #     "transfer-update",
    #     "transcript",
    #     "tool-calls",
    #     "user-interrupted",
    #     "voice-input"
    # ],
    # "serverMessages": [
    #     "conversation-update",
    #     "end-of-call-report",
    #     "function-call",
    #     "hang",
    #     "speech-update",
    #     "status-update",
    #     "tool-calls",
    #     "transfer-destination-request",
    #     "user-interrupted"
    # ],
    # "silenceTimeoutSeconds": 30,
    # "maxDurationSeconds": 600,
    # "metadata": {
    #     "key": "value"
    # },
    # "startSpeakingPlan": {
    #     "waitSeconds": 0.4,
    #     "smartEndpointingEnabled": True,
    # },
    # "stopSpeakingPlan": {
    #     "numWords": 0,
    #     "voiceSeconds": 0.2,
    #     "backoffSeconds": 1,
    #     "acknowledgementPhrases": [
    #     "i understand",
    #     "i see",
    #     "i got it",
    #     "i hear you",
    #     "im listening",
    #     "im with you",
    #     "right",
    #     "okay",
    #     "ok",
    #     "sure",
    #     "alright",
    #     "got it",
    #     "understood",
    #     "yeah",
    #     "yes",
    #     "uh-huh",
    #     "mm-hmm",
    #     "gotcha",
    #     "mhmm",
    #     "ah",
    #     "yeah okay",
    #     "yeah sure"
    #     ],
    #     "interruptionPhrases": [
    #     "stop",
    #     "shut",
    #     "up",
    #     "enough",
    #     "quiet",
    #     "silence",
    #     "but",
    #     "dont",
    #     "not",
    #     "no",
    #     "hold",
    #     "wait",
    #     "cut",
    #     "pause",
    #     "nope",
    #     "nah",
    #     "nevermind",
    #     "never",
    #     "bad",
    #     "actually"
    #     ]
    # }
