import os
from typing import Dict, Any
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
from services.service import BaseService
# Import configuration from config module
from config import (
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_FROM_NUMBER,
    HARDCODED_TO_NUMBER
)
import asyncio

class CallActivity(BaseService):
    """
    Activity responsible for handling outgoing PSTN calls via Twilio.
    (Simplified implementation - bypasses local AudioManager)
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
        self.call_sid = None

    async def start(self):
        """Start the call activity by initiating the call."""
        await super().start()
        self.logger.info("Call Activity started")
        await self._initiate_call()
        # No event subscriptions needed here as ActivityService handles the 'end_call' intent

    async def stop(self):
        """Stop the call activity by ending the call."""
        self.logger.info("Call Activity stopping")
        await self._end_call()
        await super().stop()

    async def handle_event(self, event: Dict[str, Any]):
        """Handle events relevant to the call activity (currently none)."""
        event_type = event.get("type")
        self.logger.debug(f"Call Activity received event: {event_type} - No action taken.")
        # ActivityService handles the 'end_call' intent directly

    async def _initiate_call(self):
        """Initiate the outbound call using Twilio REST API."""
        if not self.twilio_client:
            self.logger.error("Twilio client not initialized. Cannot initiate call.")
            await self.publish({"type": "pstn_call_error", "reason": "Twilio client not initialized"})
            # Consider stopping the activity here?
            return

        if self.call_sid:
            self.logger.warning(f"Call already in progress (SID: {self.call_sid}). Cannot initiate another.")
            return

        try:
            self.logger.info(f"Initiating call from {TWILIO_FROM_NUMBER} to {HARDCODED_TO_NUMBER}")
            # Simple TwiML to connect the call
            twiml = f'<Response><Say>Connecting your call.</Say><Dial callerId="{TWILIO_FROM_NUMBER}">{HARDCODED_TO_NUMBER}</Dial></Response>'
            
            call = self.twilio_client.calls.create(
                twiml=twiml,
                to=HARDCODED_TO_NUMBER,
                from_=TWILIO_FROM_NUMBER
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