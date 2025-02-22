import logging
import numpy as np
import asyncio
import threading
import openai
import tempfile
import soundfile as sf
import json
from textwrap import dedent
from typing import Callable, Awaitable, Optional, Dict, Any
from managers.audio_manager import AudioManager
from config import OPENAI_API_KEY, IntentConfig

class WhisperGPTIntentManager:
    """
    Handles speech-to-intent detection using OpenAI's Whisper for speech-to-text
    and GPT-4 for intent classification. This is an alternative to Rhino that
    doesn't require custom model training.
    
    Uses callbacks to notify service of detected intents rather than publishing events directly.
    """
    def __init__(self, audio_manager, *, on_intent: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None):
        self.audio_manager = audio_manager
        self.on_intent = on_intent
        self.running = False
        self._audio_consumer = None
        self._lock = threading.Lock()
        self._audio_buffer = []  # Store audio chunks
        self._loop = None
        self._initialize_openai()
        
    def _initialize_openai(self):
        """Initialize OpenAI client"""
        try:
            if not OPENAI_API_KEY:
                raise ValueError("OpenAI API key not found in environment")
            openai.api_key = OPENAI_API_KEY
            logging.info("OpenAI client initialized successfully")
        except Exception as e:
            logging.error(f"Failed to initialize OpenAI client: {e}")
            raise

    @classmethod
    async def create(cls, *, audio_manager=None, on_intent: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None):
        """Factory method to create and initialize a WhisperGPTIntentManager instance"""
        if audio_manager is None:
            audio_manager = AudioManager.get_instance()
        instance = cls(audio_manager, on_intent=on_intent)
        return instance

    async def start(self):
        """Start speech intent detection"""
        if self.running:
            return

        try:
            self.running = True
            self._loop = asyncio.get_running_loop()
            self._audio_buffer = []  # Clear any existing audio
            self._audio_consumer = self.audio_manager.add_consumer(
                self._process_audio
            )
            logging.info("Speech intent detection started")

        except Exception as e:
            logging.error(f"Error starting speech intent detection: {e}")
            await self.cleanup()
            raise

    def _process_audio(self, audio_data: np.ndarray):
        """Process audio data from the audio manager by buffering it"""
        if not self.running:
            return
            
        try:
            # Buffer the audio data
            self._audio_buffer.append(audio_data)
            
        except Exception as e:
            logging.error(f"Error processing audio in speech intent detection: {e}")

    async def _transcribe_audio(self) -> str:
        """
        Transcribe the buffered audio using Whisper.
        Returns the transcribed text.
        """
        if not self._audio_buffer:
            return ""
            
        try:
            # Combine all audio chunks
            audio = np.concatenate(self._audio_buffer)
            
            # Save audio to a temporary file
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as temp_file:
                sf.write(temp_file.name, audio, self.audio_manager.sample_rate)
                
                # Transcribe using Whisper
                with open(temp_file.name, "rb") as audio_file:
                    transcript = await openai.Audio.atranscribe(
                        "whisper-1",
                        audio_file
                    )
                    
            return transcript.text
            
        except Exception as e:
            logging.error(f"Error transcribing audio: {e}")
            return ""

    async def _classify_intent(self, text: str) -> Dict[str, Any]:
        """
        Classify the intent from the transcribed text using GPT-4.
        Returns a dictionary with intent and slots.
        """
        try:
            # Define the system prompt for intent classification
            system_prompt = dedent("""
                You are an intent classifier. Given a transcribed speech input, classify it into one of these intents:

                1. cuddle - Match when someone:
                   - Says "show me some love" or "give me some love"
                   - Asks for cuddles/snuggles/hugs with phrases like:
                     * "let's cuddle/snuggle/hug"
                     * "I want/would like/can I have/give me/can we have a/some cuddle(s)/snuggle(s)/hug(s)"
                     * "cuddle/snuggle/hug me"
                   - Any of the above with optional "please"

                2. conversation (wake_up) - Match when someone:
                   - Says "time to wake up" or "time to start the day"
                   - Asks to talk/chat
                   - Asks "are you awake" or "are you there"
                   - Says "good morning" or "hey there" with optional "wake up"
                   - Suggests having a conversation
                   - Says it's time to "wake up", "rise and shine", or "get up"

                3. hide_and_seek - Match when someone:
                   - Expresses wanting to play hide and seek
                   - Says it's time for hide and seek
                   - Says "you hide and I'll find you"
                   - Suggests playing a game (in context of hide and seek)

                4. sleep - Match when someone:
                   - Mentions taking a nap
                   - Says it's nap time or time for a nap
                   - Says it's time to sleep
                   - Asks to go to sleep (with optional "please" and "now")

                5. learn_voice - Match when someone:
                   - Asks to learn/add a/my (new) voice
                   - Says "learn my voice"

                Return ONLY a JSON object with two fields:
                - intent: The classified intent name or null if no match
                - slots: An empty dictionary (for compatibility)

                Example response:
                {"intent": "cuddle", "slots": {}}

                If the input doesn't match any intent patterns closely enough, return:
                {"intent": null, "slots": {}}
            """).strip()
            
            # Get classification from GPT-4
            response = await openai.ChatCompletion.acreate(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text}
                ],
                temperature=0,
                max_tokens=100
            )
            
            # Parse the response
            try:
                result = response.choices[0].message.content
                intent_data = json.loads(result)
                if intent_data["intent"] == "wake_up":  # Normalize wake_up/conversation intent
                    intent_data["intent"] = "conversation"
                return intent_data
            except (json.JSONDecodeError, AttributeError) as e:
                logging.error(f"Error parsing GPT response: {e}")
                return {"intent": None, "slots": {}}
                
        except Exception as e:
            logging.error(f"Error classifying intent: {e}")
            return {"intent": None, "slots": {}}

    async def stop(self):
        """Stop speech intent detection"""
        if not self.running:
            return

        logging.info("Stopping speech intent detection")
        self.running = False
        await asyncio.sleep(0.1)
        await self.cleanup()

    async def cleanup(self):
        """Clean up resources"""
        logging.info("Cleaning up speech intent detection resources")
        self.running = False

        if self._audio_consumer is not None:
            self.audio_manager.remove_consumer(self._audio_consumer)
            self._audio_consumer = None

        # Clear audio buffer
        self._audio_buffer = []

        logging.info("Speech intent detection cleanup completed")

    async def __aenter__(self):
        """Async context manager entry"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.cleanup() 