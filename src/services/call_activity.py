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
import audioop
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
        self.websocket_loop = None
        self.twilio_pcm_buffer = np.array([], dtype=np.int16) # Buffer for incoming Twilio PCM audio

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
            # Convert http:// or https:// to wss:// for WebSocket
            public_url = self.ngrok_ws_tunnel.public_url
            if public_url.startswith("https://"):
                ws_url = public_url.replace("https://", "wss://", 1)
            elif public_url.startswith("http://"):
                ws_url = public_url.replace("http://", "wss://", 1)
            else:
                self.logger.error(f"Unexpected ngrok public URL scheme: {public_url}. Using as is.")
                ws_url = public_url # Fallback, though this might still cause issues
            
            # self.ws_url = f"{ws_url}/media" # REMOVE /media path for testing
            self.ws_url = ws_url # Use root path
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
            response = VoiceResponse()

            # Use bidirectional streaming with Connect/Stream
            with response.connect() as connect:
                connect.stream(url=self.ws_url)
                
            self.logger.info(f"Returning TwiML: {response}")
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
            self.websocket_loop = asyncio.get_event_loop() # Capture the loop

            async def handle_websocket(websocket_conn): # Expecting one argument
                self.logger.debug(f"Inspecting websocket_conn object attributes: {dir(websocket_conn)}")
                
                path_to_use = "<unknown_path>"
                if hasattr(websocket_conn, 'request') and websocket_conn.request and hasattr(websocket_conn.request, 'path'):
                    path_to_use = websocket_conn.request.path
                    self.logger.info(f"Found path via websocket_conn.request.path: {path_to_use}")
                elif hasattr(websocket_conn, 'path'): # Fallback if request.path isn't there
                    path_to_use = websocket_conn.path
                    self.logger.info(f"Found path via websocket_conn.path: {path_to_use}")
                else:
                    self.logger.warning("Could not find path attribute directly on websocket_conn or via websocket_conn.request.path. Check dir() output.")

                self.logger.info(f"WebSocket connection attempt from {websocket_conn.remote_address} to path '{path_to_use}'")
                try:
                    self.logger.info(f"New WebSocket connection accepted from {websocket_conn.remote_address}")
                    self.active_websockets.add(websocket_conn)
                    
                    # Process incoming messages (audio from Twilio)
                    async for message in websocket_conn: 
                        await self._handle_websocket_message(websocket_conn, message)
                        
                except websockets.exceptions.ConnectionClosed:
                    self.logger.info(f"WebSocket connection closed by client {websocket_conn.remote_address}")
                except Exception as e:
                    self.logger.error(f"Error in WebSocket handler: {e}", exc_info=True)
                finally:
                    if websocket_conn in self.active_websockets:
                        self.active_websockets.remove(websocket_conn)
            
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
                # Log stream metadata if available
                stream_data = data.get("start", {})
                self.logger.info(f"Stream metadata: {stream_data}")
                
            elif event == "media":
                # Extract and decode audio payload
                payload = data.get("media", {}).get("payload")
                if payload:
                    # Decode base64 string
                    audio_bytes = base64.b64decode(payload)
                    self.logger.info(f"Received {len(audio_bytes)} bytes of µ-law audio from Twilio")
                    
                    # Convert µ-law to PCM
                    # Twilio sends 8kHz µ-law audio
                    pcm_audio = self._ulaw_to_pcm(audio_bytes)
                    
                    # Log audio characteristics for debugging
                    self.logger.info(f"After conversion: {len(pcm_audio)} PCM samples, dtype={pcm_audio.dtype}")
                    if len(pcm_audio) > 0:
                        self.logger.info(f"Audio stats: min={np.min(pcm_audio)}, max={np.max(pcm_audio)}, mean={np.mean(pcm_audio):.2f}, std={np.std(pcm_audio):.2f}")
                        # Log first few samples to check if they look reasonable
                        self.logger.info(f"First 10 samples: {pcm_audio[:10].tolist()}")
                    
                    # Buffer and play full chunks
                    if self.audio_manager and self.call_producer and self.call_producer.active:
                        self.twilio_pcm_buffer = np.concatenate((self.twilio_pcm_buffer, pcm_audio))
                        chunk_size = self.audio_manager.config.chunk # Get chunk size from AudioManager
                        self.logger.info(f"Buffer size: {len(self.twilio_pcm_buffer)}, chunk size: {chunk_size}")
                        
                        while len(self.twilio_pcm_buffer) >= chunk_size:
                            chunk_to_play = self.twilio_pcm_buffer[:chunk_size]
                            self.twilio_pcm_buffer = self.twilio_pcm_buffer[chunk_size:]
                            self.audio_manager.play_audio(chunk_to_play, producer_name="twilio_call")
                            self.logger.debug(f"Played a chunk of {len(chunk_to_play)} samples from Twilio buffer.")
                
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
            # Use run_coroutine_threadsafe as _handle_mic_audio is called from a different thread
            if self.websocket_loop and self.websocket_loop.is_running():
                for ws in list(self.active_websockets):
                    asyncio.run_coroutine_threadsafe(self._send_to_websocket(ws, message), self.websocket_loop)
            else:
                self.logger.warning("WebSocket event loop not available/running; cannot send mic audio.")
                
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
        
        Note: Our AudioManager provides 16kHz PCM, but Twilio expects 8kHz µ-law.
        This function handles both the downsampling and the PCM to µ-law conversion.
        """
        # Normalize to int16 range if not already
        if pcm_data.dtype != np.int16:
            pcm_data = np.clip(pcm_data, -32768, 32767).astype(np.int16)
        
        # Convert numpy array to bytes for audioop
        pcm_bytes_16khz = pcm_data.tobytes()
        
        # Downsample from 16kHz to 8kHz using audioop.ratecv
        pcm_bytes_8khz, _ = audioop.ratecv(
            pcm_bytes_16khz,  # input bytes
            2,                # 2 bytes per sample (16-bit)
            1,                # 1 channel (mono)
            16000,            # input rate (16kHz)
            8000,             # output rate (8kHz)
            None              # no previous state
        )
        
        # Convert PCM to µ-law using audioop
        ulaw_bytes = audioop.lin2ulaw(pcm_bytes_8khz, 2)
        
        # Twilio expects standard µ-law, not inverted
        return ulaw_bytes

    def _ulaw_to_pcm(self, ulaw_data: bytes) -> np.ndarray:
        """Convert µ-law audio from Twilio to PCM using audioop for accuracy.
        
        Note: Twilio sends 8kHz µ-law audio, but our AudioManager expects 16kHz PCM.
        This function handles both the µ-law to PCM conversion and the resampling.
        """
        # Twilio sends standard µ-law, not inverted
        # Convert µ-law bytes to linear PCM bytes (16-bit, mono)
        pcm_bytes_8khz = audioop.ulaw2lin(ulaw_data, 2)
        
        # Log intermediate conversion results
        pcm_8khz_array = np.frombuffer(pcm_bytes_8khz, dtype=np.int16)
        self.logger.info(f"After µ-law to PCM: {len(pcm_8khz_array)} samples at 8kHz")
        if len(pcm_8khz_array) > 0:
            self.logger.info(f"8kHz PCM stats: min={np.min(pcm_8khz_array)}, max={np.max(pcm_8khz_array)}, mean={np.mean(pcm_8khz_array):.2f}, std={np.std(pcm_8khz_array):.2f}")
            # Check if this looks like valid audio (should be centered around 0)
            if abs(np.mean(pcm_8khz_array)) > 1000:
                self.logger.warning(f"Audio has large DC offset: {np.mean(pcm_8khz_array):.2f}, this might indicate incorrect decoding")
        
        # Resample from 8kHz to 16kHz using audioop.ratecv
        # Parameters: (input_bytes, width_in_bytes, num_channels, input_rate, output_rate, state, weight_A, weight_B)
        pcm_bytes_16khz, _ = audioop.ratecv(
            pcm_bytes_8khz,  # input bytes
            2,               # 2 bytes per sample (16-bit)
            1,               # 1 channel (mono)
            8000,            # input rate (8kHz)
            16000,           # output rate (16kHz)
            None             # no previous state
        )
        
        # Convert PCM bytes to numpy array of int16
        pcm_audio = np.frombuffer(pcm_bytes_16khz, dtype=np.int16)
        
        self.logger.info(f"After resampling to 16kHz: {len(pcm_audio)} samples")
        
        return pcm_audio

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
            # --- REVERTED: Use original code ---
            # Ensure self.twiml_url (Flask ngrok URL) is correctly set in _setup_ngrok
            self.logger.info(f"Initiating call from {TWILIO_FROM_NUMBER} to {HARDCODED_TO_NUMBER} using TwiML URL: {self.twiml_url}")
            
            call = self.twilio_client.calls.create(
                to=HARDCODED_TO_NUMBER,
                from_=TWILIO_FROM_NUMBER,
                url=self.twiml_url # Use the app's Flask ngrok HTTP URL
            )
            # --- END REVERTED ---
            
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