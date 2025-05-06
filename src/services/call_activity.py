"""
CallActivity is a service that handles outgoing PSTN calls via Twilio.
It is used for making voice calls to regular phone numbers with bidirectional audio support.
"""
import os
import base64
import json
import threading
import numpy as np
from typing import Dict, Any, Optional, List
from flask import Flask, request, Response
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Start
from twilio.base.exceptions import TwilioRestException
from services.service import BaseService
from managers.audio_manager import AudioManager, AudioConsumer, AudioProducer
from pyngrok import ngrok, conf
import websockets
import asyncio
import logging
# Import configuration from config module
from config import (
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_FROM_NUMBER,
    HARDCODED_TO_NUMBER,
    TWILIO_POLL_INTERVAL,
    NGROK_AUTH_TOKEN
)

# Additional configuration for the Flask/WebSocket servers
FLASK_PORT = 5000
WEBSOCKET_PORT = 3000
NGROK_AUTH_TOKEN = os.environ.get("NGROK_AUTH_TOKEN", "")  # Set in .env or environment

class CallActivity(BaseService):
    """
    Activity responsible for handling outgoing PSTN calls via Twilio with bidirectional audio.
    Integrates with AudioManager for local audio input/output and uses Flask/WebSocket/ngrok
    to bridge the local audio with the Twilio call.
    """
    def __init__(self, service_manager):
        super().__init__(service_manager)
        self.logger.info("Initializing Call Activity")
        
        # Check if imported credentials are valid
        if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER, HARDCODED_TO_NUMBER]):
            self.logger.error("Twilio credentials or target number missing in environment variables (loaded via config.py).")
            self.twilio_client = None
        else:
            try:
                self.twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
            except Exception as e:
                self.logger.error(f"Failed to initialize Twilio client: {e}", exc_info=True)
                self.twilio_client = None
                
        # Call tracking
        self.call_sid = None
        self._polling_task: Optional[asyncio.Task] = None
        
        # Audio integration
        self.audio_manager = None
        self.mic_consumer = None
        self.call_producer = None
        
        # Flask app for TwiML
        self.flask_app = Flask(__name__)
        self.flask_app.route("/twiml", methods=["POST"])(self._handle_twiml_request)
        self.flask_thread = None
        self.flask_stop_event = threading.Event()
        
        # WebSocket for media streaming
        self.websocket_server = None
        self.active_websockets = set()  # Track active WebSocket connections
        self.websocket_task = None
        
        # ngrok tunnels
        self.ngrok_flask_tunnel = None
        self.ngrok_ws_tunnel = None
        self.twiml_url = None
        self.ws_url = None

    async def start(self):
        """Start the call activity by setting up servers and tunnels, then initiating the call."""
        await super().start()
        self.logger.info("Call Activity starting")
        
        # Get AudioManager instance
        self.audio_manager = AudioManager.get_instance()
        if not self.audio_manager:
            self.logger.error("AudioManager not initialized. Cannot start CallActivity.")
            return
        
        # Set up ngrok tunnels
        success = await self._setup_ngrok()
        if not success:
            self.logger.error("Failed to set up ngrok tunnels. Cannot start CallActivity.")
            return
            
        # Start Flask server in a separate thread
        self.flask_thread = threading.Thread(target=self._run_flask_server, daemon=True)
        self.flask_thread.start()
        self.logger.info(f"Flask server started on port {FLASK_PORT}, tunneled at {self.twiml_url}")
        
        # Start WebSocket server
        self.websocket_task = asyncio.create_task(self._run_websocket_server())
        self.logger.info(f"WebSocket server starting on port {WEBSOCKET_PORT}, tunneled at {self.ws_url}")
        
        # Give a moment for servers to start
        await asyncio.sleep(1)
        
        # Set up audio consumer to capture microphone input
        # This callback will be called with audio data from the microphone
        self.mic_consumer = self.audio_manager.add_consumer(
            callback=self._handle_mic_audio,
            chunk_size=None  # Use default chunks from AudioManager
        )
        
        # Create a producer for call audio output
        self.call_producer = self.audio_manager.add_producer(
            name="twilio_call",
            buffer_size=100
        )
        
        # Initiate the call
        await self._initiate_call()
        
        # Start polling only if call initiation seemed successful (got a SID)
        if self.call_sid and not self._polling_task:
            self.logger.info(f"Starting call status polling for SID: {self.call_sid} every {TWILIO_POLL_INTERVAL}s")
            self._polling_task = asyncio.create_task(self._poll_call_status())
        
        self.logger.info("Call Activity started")

    async def stop(self):
        """Stop the call activity by ending the call and cleaning up all resources."""
        self.logger.info("Call Activity stopping")
        
        # Cancel polling task first
        if self._polling_task:
            if not self._polling_task.done():
                self.logger.info("Cancelling call status polling task.")
                self._polling_task.cancel()
            self._polling_task = None
        
        # End the call via API
        await self._end_call()
        
        # Close all active WebSocket connections
        for ws in list(self.active_websockets):
            try:
                await ws.close()
            except Exception as e:
                self.logger.error(f"Error closing WebSocket: {e}")
        self.active_websockets.clear()
        
        # Stop WebSocket server
        if self.websocket_task and not self.websocket_task.done():
            self.websocket_task.cancel()
            try:
                await self.websocket_task
            except asyncio.CancelledError:
                pass
        self.websocket_task = None
        
        # Stop Flask server
        self.flask_stop_event.set()
        if self.flask_thread and self.flask_thread.is_alive():
            self.flask_thread.join(timeout=5.0)
        
        # Stop ngrok tunnels
        await self._cleanup_ngrok()
        
        # Clean up audio resources
        if self.mic_consumer:
            self.audio_manager.remove_consumer(self.mic_consumer)
            self.mic_consumer = None
            
        if self.call_producer:
            self.audio_manager.remove_producer("twilio_call")
            self.call_producer = None
        
        await super().stop()
        self.logger.info("Call Activity stopped")

    async def handle_event(self, event: Dict[str, Any]):
        """Handle events relevant to the call activity."""
        event_type = event.get("type")
        self.logger.debug(f"Call Activity received event: {event_type}")
        
        # ActivityService handles the 'end_call' intent directly
        if event_type == "mute_call":
            # If we want to implement muting, we could disable the mic_consumer here
            if self.mic_consumer:
                self.mic_consumer.active = False
                self.logger.info("Call microphone muted")
                
        elif event_type == "unmute_call":
            # Re-enable the mic_consumer
            if self.mic_consumer:
                self.mic_consumer.active = True
                self.logger.info("Call microphone unmuted")

    async def _setup_ngrok(self) -> bool:
        """Set up ngrok tunnels for Flask and WebSocket servers."""
        try:
            # Configure ngrok
            if NGROK_AUTH_TOKEN:
                conf.get_default().auth_token = NGROK_AUTH_TOKEN
                
            # Create tunnels
            self.ngrok_flask_tunnel = ngrok.connect(FLASK_PORT, "http")
            self.twiml_url = f"{self.ngrok_flask_tunnel.public_url}/twiml"
            self.logger.info(f"ngrok Flask tunnel established: {self.twiml_url}")
            
            self.ngrok_ws_tunnel = ngrok.connect(WEBSOCKET_PORT, "http")
            # Convert http:// to wss:// for WebSocket
            ws_url = self.ngrok_ws_tunnel.public_url.replace("http://", "wss://")
            self.ws_url = f"{ws_url}/media"
            self.logger.info(f"ngrok WebSocket tunnel established: {self.ws_url}")
            
            return True
        except Exception as e:
            self.logger.error(f"Failed to set up ngrok tunnels: {e}", exc_info=True)
            await self._cleanup_ngrok()  # Clean up any partial setup
            return False

    async def _cleanup_ngrok(self):
        """Clean up ngrok tunnels."""
        try:
            ngrok.kill()  # This kills all tunnels
            self.logger.info("ngrok tunnels terminated")
        except Exception as e:
            self.logger.error(f"Error cleaning up ngrok tunnels: {e}")
        self.ngrok_flask_tunnel = None
        self.ngrok_ws_tunnel = None
        self.twiml_url = None
        self.ws_url = None

    def _run_flask_server(self):
        """Run Flask server in a separate thread."""
        try:
            from werkzeug.serving import make_server
            
            server = make_server('0.0.0.0', FLASK_PORT, self.flask_app)
            server.timeout = 0.5  # Short timeout to allow checking stop_event
            
            self.logger.info(f"Flask server starting on port {FLASK_PORT}")
            
            while not self.flask_stop_event.is_set():
                server.handle_request()
                
        except Exception as e:
            self.logger.error(f"Error in Flask server: {e}", exc_info=True)
        finally:
            self.logger.info("Flask server stopped")

    def _handle_twiml_request(self):
        """Handle incoming TwiML request from Twilio."""
        try:
            self.logger.info("Received TwiML request from Twilio")
            
            # Create TwiML response with <Connect><Stream>
            response = VoiceResponse()
            
            # Use <Connect><Stream> for bidirectional streaming
            with response.connect() as connect:
                connect.stream(url=self.ws_url)
                
            self.logger.debug(f"Returning TwiML: {response}")
            return Response(str(response), mimetype="text/xml")
            
        except Exception as e:
            self.logger.error(f"Error handling TwiML request: {e}", exc_info=True)
            # Return a simple TwiML in case of error
            response = VoiceResponse()
            response.say("An error occurred setting up the call")
            return Response(str(response), mimetype="text/xml")

    async def _run_websocket_server(self):
        """Run WebSocket server to handle media streaming."""
        try:
            self.logger.info(f"Starting WebSocket server on port {WEBSOCKET_PORT}")
            
            async def handle_websocket(websocket, path):
                self.logger.info(f"WebSocket connection attempt from {websocket.remote_address} to path '{path}'")
                try:
                    self.logger.info(f"New WebSocket connection accepted from {websocket.remote_address}")
                    self.active_websockets.add(websocket)
                    
                    # Process incoming messages (audio from Twilio)
                    async for message in websocket:
                        await self._handle_websocket_message(websocket, message)
                        
                except websockets.exceptions.ConnectionClosed:
                    self.logger.info(f"WebSocket connection closed by client {websocket.remote_address}")
                except Exception as e:
                    self.logger.error(f"Error in WebSocket handler: {e}", exc_info=True)
                finally:
                    if websocket in self.active_websockets:
                        self.active_websockets.remove(websocket)
            
            # Start the WebSocket server
            self.websocket_server = await websockets.serve(handle_websocket, "0.0.0.0", WEBSOCKET_PORT)
            self.logger.info(f"WebSocket server started on port {WEBSOCKET_PORT}")
            
            # Keep the server running until the task is cancelled
            await asyncio.Future()
            
        except asyncio.CancelledError:
            self.logger.info("WebSocket server task cancelled")
            raise
        except Exception as e:
            self.logger.error(f"Error starting WebSocket server: {e}", exc_info=True)
        finally:
            if self.websocket_server:
                self.websocket_server.close()
                await self.websocket_server.wait_closed()
                self.logger.info("WebSocket server closed")
                self.websocket_server = None

    async def _handle_websocket_message(self, websocket, message):
        """Handle incoming WebSocket message from Twilio."""
        try:
            # Parse JSON message
            data = json.loads(message)
            event = data.get("event")
            
            if event == "start":
                self.logger.info("WebSocket stream started")
                
            elif event == "media":
                # Extract and decode audio payload
                payload = data.get("media", {}).get("payload")
                if payload:
                    # Decode base64 string
                    audio_bytes = base64.b64decode(payload)
                    
                    # Convert µ-law to PCM
                    # Twilio sends 8kHz µ-law audio
                    pcm_audio = self._ulaw_to_pcm(audio_bytes)
                    
                    # Pass to AudioManager to play through speakers
                    if self.call_producer and self.call_producer.active:
                        # Play the audio
                        self.audio_manager.play_audio(pcm_audio, producer_name="twilio_call")
                
            elif event == "stop":
                self.logger.info("WebSocket stream stopped by Twilio")
                # The call might have ended - check status
                if self.call_sid:
                    asyncio.create_task(self._check_call_status(self.call_sid))
                
            else:
                self.logger.debug(f"Received unknown WebSocket event: {event}")
                
        except json.JSONDecodeError:
            self.logger.error("Failed to parse WebSocket message as JSON")
        except Exception as e:
            self.logger.error(f"Error handling WebSocket message: {e}", exc_info=True)

    def _handle_mic_audio(self, audio_data: np.ndarray):
        """Handle audio data from the microphone and send it to Twilio."""
        if not self.active_websockets:  # No active WebSocket connections
            return
            
        try:
            # Convert PCM to µ-law (Twilio expects 8kHz µ-law)
            ulaw_audio = self._pcm_to_ulaw(audio_data)
            
            # Encode to base64
            base64_audio = base64.b64encode(ulaw_audio).decode('utf-8')
            
            # Create JSON message
            message = json.dumps({
                "event": "media",
                "streamSid": "STREAM_SID",  # This is normally provided by Twilio but we're sending TO Twilio
                "media": {
                    "payload": base64_audio
                }
            })
            
            # Send to all active WebSockets (usually just one)
            for ws in list(self.active_websockets):
                asyncio.create_task(self._send_to_websocket(ws, message))
                
        except Exception as e:
            self.logger.error(f"Error processing microphone audio: {e}", exc_info=True)

    async def _send_to_websocket(self, websocket, message):
        """Send a message to a WebSocket with error handling."""
        try:
            await websocket.send(message)
        except websockets.exceptions.ConnectionClosed:
            self.logger.info("WebSocket connection closed while sending")
            if websocket in self.active_websockets:
                self.active_websockets.remove(websocket)
        except Exception as e:
            self.logger.error(f"Error sending to WebSocket: {e}")
            if websocket in self.active_websockets:
                self.active_websockets.remove(websocket)

    def _pcm_to_ulaw(self, pcm_data: np.ndarray) -> bytes:
        """Convert PCM audio to µ-law format for Twilio.
        
        Note: This is a simplified version - in production, you'd want to 
        use a proper audio library with resampling capabilities to handle
        different sample rates.
        """
        # Twilio expects 8kHz mono µ-law audio
        # This is a basic implementation assuming pcm_data is already at 8kHz
        
        # Normalize to int16 range if not already
        if pcm_data.dtype != np.int16:
            pcm_data = np.clip(pcm_data, -32768, 32767).astype(np.int16)
        
        # Basic µ-law conversion (simplified)
        # In production, use a proper audio library like audioop or scipy
        sign = np.signbit(pcm_data).astype(np.uint8)
        pcm_abs = np.abs(pcm_data)
        
        # µ-law conversion formula (simplified)
        ulaw = np.zeros_like(pcm_abs, dtype=np.uint8)
        mask = pcm_abs > 0
        ulaw[mask] = 127 - np.clip(np.log(1 + 255 * pcm_abs[mask] / 32767) / np.log(256) * 127, 0, 127).astype(np.uint8)
        
        # Apply sign bit
        ulaw = (sign * 128 + ulaw).astype(np.uint8)
        ulaw = 255 - ulaw  # Twilio expects inverted µ-law
        
        return ulaw.tobytes()

    def _ulaw_to_pcm(self, ulaw_data: bytes) -> np.ndarray:
        """Convert µ-law audio from Twilio to PCM.
        
        Note: This is a simplified version - in production, you'd want to 
        use a proper audio library with resampling capabilities.
        """
        # Convert bytes to numpy array
        ulaw_array = np.frombuffer(ulaw_data, dtype=np.uint8)
        
        # Invert (Twilio sends inverted µ-law)
        ulaw_array = 255 - ulaw_array
        
        # Extract sign bit and magnitude
        sign = (ulaw_array & 0x80) >> 7
        magnitude = ulaw_array & 0x7F
        
        # µ-law to linear conversion (simplified)
        pcm = np.zeros_like(magnitude, dtype=np.float32)
        mask = magnitude > 0
        pcm[mask] = np.power(256, magnitude[mask] / 127) - 1
        pcm = pcm * 32767 / 255
        
        # Apply sign
        pcm = pcm * (1 - 2 * sign)
        
        # Convert to int16
        pcm = pcm.astype(np.int16)
        
        return pcm

    async def _poll_call_status(self):
        """Periodically polls the Twilio API for the call status."""
        self.logger.debug(f"Polling task started for SID: {self.call_sid}")
        terminal_statuses = ['completed', 'canceled', 'failed', 'no-answer']
        while True:
            await asyncio.sleep(TWILIO_POLL_INTERVAL)
            if not self.call_sid or not self.twilio_client:
                self.logger.info("Polling task stopping: No active call SID or Twilio client.")
                break # Exit loop if call ended or client invalid

            try:
                self.logger.debug(f"Polling status for call SID: {self.call_sid}")
                call = self.twilio_client.calls(self.call_sid).fetch()
                self.logger.debug(f"Call SID {self.call_sid} status: {call.status}")

                if call.status in terminal_statuses:
                    self.logger.info(f"Call SID {self.call_sid} reached terminal state '{call.status}' via polling. Requesting activity stop.")
                    # Publish an event for ActivityService to handle the stop
                    await self.publish({
                        "type": "pstn_call_completed_remotely",
                        "sid": self.call_sid,
                        "status": call.status
                    })
                    self.call_sid = None # Clear SID to stop polling
                    break # Exit polling loop

            except TwilioRestException as e:
                if e.status == 404:
                    self.logger.warning(f"Polling: Call SID {self.call_sid} not found. Assuming ended.")
                    await self.publish({"type": "pstn_call_completed_remotely", "sid": self.call_sid, "status": "not-found"})
                    self.call_sid = None
                    break
                else:
                    self.logger.error(f"Polling: Twilio API error fetching status for SID {self.call_sid}: {e}")
            except Exception as e:
                self.logger.error(f"Polling: Unexpected error fetching status for SID {self.call_sid}: {e}", exc_info=True)
        self.logger.debug(f"Polling task finished for original SID: {self.call_sid or 'None'}")

    async def _check_call_status(self, sid: str):
        """Check the status of a call immediately."""
        if not sid or not self.twilio_client:
            return
            
        try:
            call = self.twilio_client.calls(sid).fetch()
            self.logger.info(f"Call SID {sid} status check: {call.status}")
            
            # If the call has ended, publish an event
            if call.status in ['completed', 'canceled', 'failed', 'no-answer']:
                await self.publish({
                    "type": "pstn_call_completed_remotely",
                    "sid": sid,
                    "status": call.status
                })
                if sid == self.call_sid:
                    self.call_sid = None
                    
        except Exception as e:
            self.logger.error(f"Error checking call status: {e}")

    async def _initiate_call(self):
        """Initiate the outbound call using Twilio REST API."""
        if not self.twilio_client:
            self.logger.error("Twilio client not initialized. Cannot initiate call.")
            await self.publish({"type": "pstn_call_error", "reason": "Twilio client not initialized"})
            return

        if self.call_sid:
            self.logger.warning(f"Call already in progress (SID: {self.call_sid}). Cannot initiate another.")
            return

        try:
            self.logger.info(f"Initiating call from {TWILIO_FROM_NUMBER} to {HARDCODED_TO_NUMBER} using TwiML URL: {self.twiml_url}")
            
            # Create a call using the TwiML URL (Flask server)
            call = self.twilio_client.calls.create(
                to=HARDCODED_TO_NUMBER,
                from_=TWILIO_FROM_NUMBER,
                url=self.twiml_url
            )
            self.call_sid = call.sid
            self.logger.info(f"Call initiated successfully. SID: {self.call_sid}")
            await self.publish({"type": "pstn_call_initiated", "sid": self.call_sid})

        except TwilioRestException as e:
            self.logger.error(f"Twilio API error initiating call: {e}")
            await self.publish({"type": "pstn_call_error", "reason": str(e)})
        except Exception as e:
            self.logger.error(f"Unexpected error initiating call: {e}", exc_info=True)
            await self.publish({"type": "pstn_call_error", "reason": "Unexpected error"})

    async def _end_call(self):
        """End the current call using Twilio REST API."""
        if not self.twilio_client:
            self.logger.error("Twilio client not initialized. Cannot end call.")
            return
            
        if not self.call_sid:
            self.logger.info("No active call SID found to end.")
            return

        self.logger.info(f"Attempting to end call with SID: {self.call_sid}")
        try:
            # Fetch the call first to check its status
            call = self.twilio_client.calls(self.call_sid).fetch()
            
            # Only attempt to update if the call is in a state that can be ended
            if call.status not in ['completed', 'canceled', 'failed', 'no-answer']:
                updated_call = self.twilio_client.calls(self.call_sid).update(status='completed')
                self.logger.info(f"Call SID {self.call_sid} requested to end. Final status: {updated_call.status}")
                await self.publish({"type": "pstn_call_ended", "sid": self.call_sid, "final_status": updated_call.status})
            else:
                self.logger.info(f"Call SID {self.call_sid} already in terminal state: {call.status}")
                await self.publish({"type": "pstn_call_already_ended", "sid": self.call_sid, "status": call.status})

        except TwilioRestException as e:
            # Handle cases where the call might not exist or is already completed
            if e.status == 404:
                self.logger.warning(f"Call SID {self.call_sid} not found. Assuming already ended.")
                await self.publish({"type": "pstn_call_not_found", "sid": self.call_sid})
            else:
                self.logger.error(f"Twilio API error ending call SID {self.call_sid}: {e}")
                await self.publish({"type": "pstn_call_error", "sid": self.call_sid, "reason": str(e)})
        except Exception as e:
            self.logger.error(f"Unexpected error ending call SID {self.call_sid}: {e}", exc_info=True)
            await self.publish({"type": "pstn_call_error", "sid": self.call_sid, "reason": "Unexpected error"})
        finally:
            # Always clear the SID after attempting to end
            self.call_sid = None 