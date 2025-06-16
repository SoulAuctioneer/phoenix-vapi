"""
CallActivity is a service that handles outgoing PSTN calls via Twilio.
It is used for making voice calls to regular phone numbers with bidirectional audio support.
"""
import os
import base64
import json
import numpy as np
from typing import Dict, Any, Optional, List
from flask import Flask, request, Response
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Start
from twilio.base.exceptions import TwilioRestException
from services.service import BaseService
from managers.audio_manager import AudioManager, AudioConsumer, AudioProducer
from managers.server_manager import ServerManager
import websockets
import asyncio
import logging
import audioop
# Import configuration from config module
from config import (    
    CallConfig,
    NGROK_AUTH_TOKEN
)

# Additional configuration for the Flask/WebSocket servers
FLASK_PORT = 5000
WEBSOCKET_PORT = 3000

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
        if not all([CallConfig.TWILIO_ACCOUNT_SID, CallConfig.TWILIO_AUTH_TOKEN, CallConfig.TWILIO_FROM_NUMBER]):
            self.logger.error("Twilio credentials or target number missing in environment variables (loaded via config.py).")
            self.twilio_client = None
        else:
            try:
                self.twilio_client = Client(CallConfig.TWILIO_ACCOUNT_SID, CallConfig.TWILIO_AUTH_TOKEN)
            except Exception as e:
                self.logger.error(f"Failed to initialize Twilio client: {e}", exc_info=True)
                self.twilio_client = None
                
        # Call tracking
        self.call_sid = None
        self._polling_task: Optional[asyncio.Task] = None  # Currently disabled - using status callbacks instead
        self.is_ringing = False
        # Audio integration
        self.audio_manager = None
        self.mic_consumer = None
        self.call_producer = None
        
        # Server manager for handling Flask and WebSocket servers with ngrok
        self.server_manager = ServerManager(ngrok_auth_token=NGROK_AUTH_TOKEN)
        
        # Flask app for TwiML
        self.flask_app = Flask(__name__)
        self.flask_app.route("/twiml", methods=["POST"])(self._handle_twiml_request)
        self.flask_app.route("/status", methods=["POST"])(self._handle_status_callback)
        
        # Server info
        self.twiml_url = None
        self.ws_url = None
        self.status_callback_url = None
        
        # WebSocket tracking
        self.stream_sid = None  # Store the Twilio stream SID
        self.websocket_loop = None
        self.twilio_pcm_buffer = np.array([], dtype=np.int16) # Buffer for incoming Twilio PCM audio
        
        # Stop operation tracking
        self._stopping = False  # Flag to prevent concurrent stop operations

    async def start(self, contact: str):
        """Start the call activity by setting up servers and tunnels, then initiating the call."""
        await super().start()
        self.logger.info("Call Activity starting")
        
        # Get AudioManager instance
        self.audio_manager = AudioManager.get_instance()
        if not self.audio_manager:
            self.logger.error("AudioManager not initialized. Cannot start CallActivity.")
            return
        
        # Set up Flask server with ngrok tunnel
        try:
            flask_info = self.server_manager.create_flask_server(
                name="twilio_twiml",
                app=self.flask_app,
                port=FLASK_PORT,
                create_tunnel=True,
                tunnel_path="/twiml"
            )
            self.twiml_url = flask_info["public_url"]
            # Create status callback URL using the same base URL
            base_url = flask_info["public_url"].rsplit('/twiml', 1)[0]
            self.status_callback_url = f"{base_url}/status"
            self.logger.info(f"Flask server started with TwiML URL: {self.twiml_url}")
            self.logger.info(f"Status callback URL: {self.status_callback_url}")
        except Exception as e:
            self.logger.error(f"Failed to set up Flask server: {e}", exc_info=True)
            return
            
        # Set up WebSocket server with ngrok tunnel
        try:
            ws_info = await self.server_manager.create_websocket_server(
                name="twilio_media",
                handler=self._handle_websocket_connection,
                port=WEBSOCKET_PORT,
                create_tunnel=True
            )
            self.ws_url = ws_info["public_url"]
            self.websocket_loop = asyncio.get_event_loop()
            self.logger.info(f"WebSocket server started with URL: {self.ws_url}")
        except Exception as e:
            self.logger.error(f"Failed to set up WebSocket server: {e}", exc_info=True)
            return
        
        # Give a moment for servers to start
        await asyncio.sleep(1)
        
        # Set up audio consumer to capture microphone input
        # This callback will be called with audio data from the microphone
        # NOTE: We delay this setup until WebSocket is connected to avoid warnings
        # self.mic_consumer = self.audio_manager.add_consumer(
        #     callback=self._handle_mic_audio,
        #     chunk_size=None  # Use default chunks from AudioManager
        # )
        
        # Create a producer for call audio output
        self.call_producer = self.audio_manager.add_producer(
            name="twilio_call",
            buffer_size=100,
            is_stream=True
        )
        
        # Get the contact number for the given contact name
        to_number = CallConfig.CONTACT_NUMBERS.get(contact.lower())
        if not to_number:
            self.logger.error(f"No contact number found for contact: {contact}")
            return

        # Initiate the call
        await self._initiate_call(to_number=to_number)
        
        # Start polling only if call initiation seemed successful (got a SID)
        # COMMENTED OUT: Relying on status callbacks instead of polling
        # if self.call_sid and not self._polling_task:
        #     self.logger.info(f"Starting call status polling for SID: {self.call_sid} every {CallConfig.TWILIO_POLL_INTERVAL}s")
        #     self._polling_task = asyncio.create_task(self._poll_call_status())
        
        self.logger.info("Call Activity started")

    async def stop(self):
        """Stop the call activity by ending the call and cleaning up all resources."""
        # Prevent multiple concurrent stop operations
        if self._stopping:
            self.logger.info("Call Activity stop already in progress, skipping duplicate call")
            return
            
        self._stopping = True
        
        try:
            self.logger.info("Call Activity stopping")
            
            # First, remove audio resources to stop processing immediately
            # This prevents the "No active WebSocket connections" warnings
            if self.mic_consumer:
                self.audio_manager.remove_consumer(self.mic_consumer)
                self.mic_consumer = None
                self.logger.info("Microphone consumer removed")
                
            if self.call_producer:
                self.audio_manager.remove_producer("twilio_call")
                self.call_producer = None
                self.logger.info("Call audio producer removed")
            
            # Cancel polling task
            # COMMENTED OUT: Not using polling, relying on status callbacks
            # if self._polling_task:
            #     if not self._polling_task.done():
            #         self.logger.info("Cancelling call status polling task.")
            #         self._polling_task.cancel()
            #         try:
            #             await self._polling_task
            #         except asyncio.CancelledError:
            #             pass
            #     self._polling_task = None
            
            # End the call via API (this may take time)
            await self._end_call()
            
            # Small delay to allow WebSocket to close gracefully after call ends
            await asyncio.sleep(0.5)
            
            # Stop servers and clean up ngrok tunnels
            # Use try-except to handle potential double-cleanup scenarios
            try:
                await self.server_manager.cleanup()
            except Exception as e:
                self.logger.warning(f"Error during server cleanup (may be already cleaned up): {e}")
            
            await super().stop()
            self.logger.info("Call Activity stopped")
        finally:
            # Always reset the stopping flag, even if an error occurred
            self._stopping = False

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

    def _handle_twiml_request(self):
        """Handle incoming TwiML request from Twilio."""
        try:
            self.logger.info("Received TwiML request from Twilio")
            response = VoiceResponse()

            # Use bidirectional streaming with Connect/Stream
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

    def _handle_status_callback(self):
        """Handle status callbacks from Twilio for real-time call status updates."""
        try:
            # Get the call status from the request
            call_sid = request.form.get('CallSid')
            call_status = request.form.get('CallStatus')
            
            self.logger.info(f"Received status callback - SID: {call_sid}, Status: {call_status}")
            
            # Run the async publish in the event loop
            if hasattr(self, 'websocket_loop') and self.websocket_loop:
                # Publish specific events based on status
                if call_status == 'ringing':
                    self.is_ringing = True
                    asyncio.run_coroutine_threadsafe(
                        self.publish({
                            "type": "pstn_call_ringing",
                            "sid": call_sid,
                            "status": call_status
                        }), 
                        self.websocket_loop
                    )
                    # Play ringing sound effect
                    self.logger.info("Playing ringing sound effect for outgoing call")
                    asyncio.run_coroutine_threadsafe(
                        self.publish({
                            "type": "play_sound",
                            "effect_name": "BRING_BRING",
                            "loop": True  # Loop the ringing sound until answered
                        }),
                        self.websocket_loop
                    )
                elif call_status == 'in-progress':
                    # Stop the ringing sound when call is answered
                    if self.is_ringing:
                        self.is_ringing = False
                        self.logger.info("Call answered")
                        asyncio.run_coroutine_threadsafe(
                            self.publish({
                                "type": "stop_sound",
                                "effect_name": "BRING_BRING"
                            }),
                            self.websocket_loop
                        )
                    asyncio.run_coroutine_threadsafe(
                        self.publish({
                            "type": "pstn_call_answered",
                            "sid": call_sid,
                            "status": call_status
                        }), 
                        self.websocket_loop
                    )
                elif call_status in ['completed', 'canceled', 'failed', 'no-answer', 'busy']:
                    self.logger.info(f"Call ended with status: {call_status}")
                    # Stop any playing sounds when call ends
                    if self.is_ringing:
                        self.is_ringing = False
                        asyncio.run_coroutine_threadsafe(
                            self.publish({
                                "type": "stop_sound",
                                "effect_name": "BRING_BRING"
                            }),
                            self.websocket_loop
                        )
                    asyncio.run_coroutine_threadsafe(
                        self.publish({
                            "type": "pstn_call_completed_remotely",
                            "sid": call_sid,
                            "status": call_status
                        }), 
                        self.websocket_loop
                    )
                    
            return Response("OK", status=200)
            
        except Exception as e:
            self.logger.error(f"Error handling status callback: {e}", exc_info=True)
            return Response("Error", status=500)

    async def _handle_websocket_connection(self, websocket, path):
        """Handle a WebSocket connection from Twilio."""
        self.logger.info(f"New WebSocket connection from {websocket.remote_address} to path '{path}'")
        try:
            # Process incoming messages (audio from Twilio)
            async for message in websocket:
                await self._handle_websocket_message(websocket, message)
                
        except websockets.exceptions.ConnectionClosed:
            self.logger.info(f"WebSocket connection closed by client {websocket.remote_address}")
        except Exception as e:
            self.logger.error(f"Error in WebSocket handler: {e}", exc_info=True)

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
                self.stream_sid = stream_data.get("streamSid")
                
                # Now that WebSocket is connected, set up microphone consumer if not already done
                if not self.mic_consumer and self.audio_manager:
                    self.mic_consumer = self.audio_manager.add_consumer(
                        callback=self._handle_mic_audio,
                        chunk_size=None  # Use default chunks from AudioManager
                    )
                    self.logger.info("Microphone consumer added - WebSocket is ready for audio")
                
            elif event == "media":
                # Extract and decode audio payload
                payload = data.get("media", {}).get("payload")
                if payload:
                    # Decode base64 string
                    audio_bytes = base64.b64decode(payload)
                    self.logger.debug(f"Received {len(audio_bytes)} bytes of µ-law audio from Twilio")
                    
                    # Convert µ-law to PCM
                    # Twilio sends 8kHz µ-law audio
                    pcm_audio = self._ulaw_to_pcm(audio_bytes)
                    
                    # Log audio characteristics for debugging
                    self.logger.debug(f"After conversion: {len(pcm_audio)} PCM samples, dtype={pcm_audio.dtype}")
                    if len(pcm_audio) > 0:
                        self.logger.debug(f"Audio stats: min={np.min(pcm_audio)}, max={np.max(pcm_audio)}, mean={np.mean(pcm_audio):.2f}, std={np.std(pcm_audio):.2f}")
                        # Log first few samples to check if they look reasonable
                        self.logger.debug(f"First 10 samples: {pcm_audio[:10].tolist()}")
                    
                    # Buffer and play full chunks
                    if self.audio_manager and self.call_producer and self.call_producer.active:
                        self.twilio_pcm_buffer = np.concatenate((self.twilio_pcm_buffer, pcm_audio))
                        chunk_size = self.audio_manager.config.chunk # Get chunk size from AudioManager
                        self.logger.debug(f"Buffer size: {len(self.twilio_pcm_buffer)}, chunk size: {chunk_size}")
                        
                        while len(self.twilio_pcm_buffer) >= chunk_size:
                            chunk_to_play = self.twilio_pcm_buffer[:chunk_size]
                            self.twilio_pcm_buffer = self.twilio_pcm_buffer[chunk_size:]
                            self.audio_manager.play_audio(chunk_to_play, producer_name="twilio_call")
                            self.logger.debug(f"Played a chunk of {len(chunk_to_play)} samples from Twilio buffer.")
                
            elif event == "stop":
                self.logger.info("WebSocket stream stopped by Twilio")
                # Note: We don't need to check call status here since we have reliable status callbacks
                # that will notify us when the call ends. The WebSocket stop just indicates the media
                # stream ended, which happens both for natural call completion and manual termination.
                
            else:
                self.logger.debug(f"Received unknown WebSocket event: {event}")
                
        except json.JSONDecodeError:
            self.logger.error("Failed to parse WebSocket message as JSON")
        except Exception as e:
            self.logger.error(f"Error handling WebSocket message: {e}", exc_info=True)

    def _handle_mic_audio(self, audio_data: np.ndarray):
        """Handle audio data from the microphone and send it to Twilio."""
        # Get active WebSocket connections from the server manager
        active_websockets = self.server_manager.get_active_connections("twilio_media")
        
        if not active_websockets:  # No active WebSocket connections
            self.logger.warning("No active WebSocket connections to send mic audio")
            return
            
        try:
            self.logger.debug(f"Processing mic audio: {len(audio_data)} samples, dtype={audio_data.dtype}")
            
            # Convert PCM to µ-law (Twilio expects 8kHz µ-law)
            ulaw_audio = self._pcm_to_ulaw(audio_data)
            self.logger.debug(f"Converted to µ-law: {len(ulaw_audio)} bytes")
            
            # Encode to base64
            base64_audio = base64.b64encode(ulaw_audio).decode('utf-8')
            
            # Create JSON message
            message = json.dumps({
                "event": "media",
                "streamSid": self.stream_sid,
                "media": {
                    "payload": base64_audio
                }
            })
            
            self.logger.debug(f"Sending mic audio message: {len(message)} chars, streamSid: {self.stream_sid}")
            
            # Send to all active WebSockets (usually just one)
            # Use run_coroutine_threadsafe as _handle_mic_audio is called from a different thread
            if self.websocket_loop and self.websocket_loop.is_running():
                for ws in list(active_websockets):
                    future = asyncio.run_coroutine_threadsafe(self._send_to_websocket(ws, message), self.websocket_loop)
                    # Log if the send was scheduled successfully
                    self.logger.debug(f"Scheduled mic audio send to WebSocket")
            else:
                self.logger.warning("WebSocket event loop not available/running; cannot send mic audio.")
                
        except Exception as e:
            self.logger.error(f"Error processing microphone audio: {e}", exc_info=True)

    async def _send_to_websocket(self, websocket, message):
        """Send a message to a WebSocket with error handling."""
        try:
            await websocket.send(message)
            self.logger.debug(f"Successfully sent message to WebSocket ({len(message)} chars)")
        except websockets.exceptions.ConnectionClosed:
            self.logger.info("WebSocket connection closed while sending")
        except Exception as e:
            self.logger.error(f"Error sending to WebSocket: {e}")

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
        self.logger.debug(f"After µ-law to PCM: {len(pcm_8khz_array)} samples at 8kHz")
        if len(pcm_8khz_array) > 0:
            self.logger.debug(f"8kHz PCM stats: min={np.min(pcm_8khz_array)}, max={np.max(pcm_8khz_array)}, mean={np.mean(pcm_8khz_array):.2f}, std={np.std(pcm_8khz_array):.2f}")
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
        
        self.logger.debug(f"After resampling to 16kHz: {len(pcm_audio)} samples")
        
        return pcm_audio

    # POLLING METHOD - Currently disabled in favor of status callbacks
    # This method is kept for reference and can be re-enabled if needed
    async def _poll_call_status(self):
        """Periodically polls the Twilio API for the call status."""
        self.logger.debug(f"Polling task started for SID: {self.call_sid}")
        terminal_statuses = ['completed', 'canceled', 'failed', 'no-answer']
        last_status = None  # Track last known status to detect changes
        
        while True:
            await asyncio.sleep(CallConfig.TWILIO_POLL_INTERVAL)
            if not self.call_sid or not self.twilio_client:
                self.logger.info("Polling task stopping: No active call SID or Twilio client.")
                break # Exit loop if call ended or client invalid

            try:
                self.logger.debug(f"Polling status for call SID: {self.call_sid}")
                call = self.twilio_client.calls(self.call_sid).fetch()
                self.logger.debug(f"Call SID {self.call_sid} status: {call.status}")

                # Report status changes
                if call.status != last_status:
                    last_status = call.status
                    
                    # Publish status change events
                    if call.status == 'ringing':
                        self.logger.info(f"Call SID {self.call_sid} is ringing at recipient")
                        await self.publish({
                            "type": "pstn_call_ringing",
                            "sid": self.call_sid,
                            "status": call.status
                        })
                    elif call.status == 'in-progress':
                        self.logger.info(f"Call SID {self.call_sid} was answered")
                        await self.publish({
                            "type": "pstn_call_answered", 
                            "sid": self.call_sid,
                            "status": call.status
                        })

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

    async def _initiate_call(self, to_number: str):
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
            self.logger.info(f"Initiating call from {CallConfig.TWILIO_FROM_NUMBER} to {to_number} using TwiML URL: {self.twiml_url}")
            
            # Create call with status callbacks if available
            call_params = {
                "to": to_number,
                "from_": CallConfig.TWILIO_FROM_NUMBER,
                "url": self.twiml_url  # Use the app's Flask ngrok HTTP URL
            }
            
            # Add status callback parameters if we have the URL
            if hasattr(self, 'status_callback_url') and self.status_callback_url:
                call_params["status_callback"] = self.status_callback_url
                call_params["status_callback_event"] = ["initiated", "ringing", "answered", "completed"]
                call_params["status_callback_method"] = "POST"
                self.logger.info(f"Using status callback URL: {self.status_callback_url}")
            
            call = self.twilio_client.calls.create(**call_params)
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