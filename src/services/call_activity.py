import os
from typing import Dict, Any, Optional
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
from services.service import BaseService
# Import configuration from config module
from config import (
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_FROM_NUMBER,
    HARDCODED_TO_NUMBER,
    TWILIO_POLL_INTERVAL
)
import asyncio

class CallActivity(BaseService):
    """
    Activity responsible for handling outgoing PSTN calls via Twilio.
    (Simplified implementation - bypasses local AudioManager, uses polling for status)
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
        self._polling_task: Optional[asyncio.Task] = None

    async def start(self):
        """Start the call activity by initiating the call and status polling."""
        await super().start()
        self.logger.info("Call Activity started")
        await self._initiate_call()
        # Start polling only if call initiation seemed successful (got a SID)
        if self.call_sid and not self._polling_task:
            self.logger.info(f"Starting call status polling for SID: {self.call_sid} every {TWILIO_POLL_INTERVAL}s")
            self._polling_task = asyncio.create_task(self._poll_call_status())

    async def stop(self):
        """Stop the call activity by ending the call and stopping polling."""
        self.logger.info("Call Activity stopping")
        # Cancel polling task first, ensuring it's not already done
        if self._polling_task:
            if not self._polling_task.done():
                self.logger.info("Cancelling call status polling task.")
                self._polling_task.cancel()
            else:
                self.logger.info("Polling task already done, no need to cancel.")
            self._polling_task = None
        
        # Then end the call via API (if SID still exists)
        await self._end_call()
        await super().stop()

    async def handle_event(self, event: Dict[str, Any]):
        """Handle events relevant to the call activity (currently none)."""
        event_type = event.get("type")
        self.logger.debug(f"Call Activity received event: {event_type} - No action taken.")
        # ActivityService handles the 'end_call' intent directly

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
                    # Decide if we should stop polling on other errors? Maybe retry a few times?
                    # For now, continue polling after logging error.
            except Exception as e:
                self.logger.error(f"Polling: Unexpected error fetching status for SID {self.call_sid}: {e}", exc_info=True)
                # Continue polling after logging error.
        self.logger.debug(f"Polling task finished for original SID: {self.call_sid or 'None'}")

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
            # Simple TwiML to just dial the number, keeping the call active until hangup.
            # Using url attribute pointing to empty TwiML might be more robust for keeping the call alive after dial connects.
            # Alternatively, just Dial might suffice.
            # Let's try just Dial first.
            twiml = f'<Response><Dial callerId="{TWILIO_FROM_NUMBER}">{HARDCODED_TO_NUMBER}</Dial></Response>'
            
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