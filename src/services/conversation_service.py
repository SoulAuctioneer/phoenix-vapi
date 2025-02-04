import logging
import asyncio
from typing import Dict, Any
from .service import BaseService
from managers.call_manager import CallManager
from config import VAPI_API_KEY, ASSISTANT_ID

class ConversationService(BaseService):
    """Handles conversations with the AI assistant"""
    def __init__(self, manager):
        super().__init__(manager)
        self.call_manager = None  # Will be initialized in start()
        self.is_active = False
        self._is_stopping = False  # Add state tracking for stop operation
        
    async def start(self):
        await super().start()
        self.call_manager = await CallManager.create(manager=self.manager)
            
    async def stop(self):
        if self.is_active:
            await self.stop_conversation()
        if self.call_manager:
            await self.call_manager.cleanup()
        await super().stop()
        
    async def start_conversation(self):
        """Start a conversation with the AI assistant"""
        if self.is_active:
            self.logger.info("Conversation already active, ignoring start request")
            return
            
        if self._is_stopping:
            self.logger.info("Conversation service is stopping, cannot start new conversation")
            return
            
        self.logger.info("Starting new conversation")
        self.is_active = True

        try:
            self.logger.info("Initializing call connection")
            await self.publish({"type": "conversation_starting"})
            await self.call_manager.start_call(assistant_id=ASSISTANT_ID)
            self.logger.info("Conversation started successfully")
            
        except Exception as e:
            self.logger.error("Failed to start call: %s", str(e), exc_info=True)
            self.is_active = False  # Reset active state on failure
            await self.stop_conversation()
            # Notify other services about the failure
            await self.publish({
                "type": "conversation_error",
                "error": str(e)
            })
            
    async def stop_conversation(self):
        """Stop the current conversation"""
        if not self.is_active:
            return
            
        self._is_stopping = True
        try:
            await self.call_manager.leave()
        except Exception as e:
            self.logger.error("Error stopping conversation: %s", str(e))
        finally:
            self.is_active = False
            self._is_stopping = False
            await self.publish({"type": "conversation_ended"})
        
    async def handle_event(self, event: Dict[str, Any]):
        """Handle events from other services"""
        event_type = event.get("type")
        
        if event_type == "wake_word_detected":
            self.logger.info("Wake word detected event received")
            if not self.is_active:  # Only start a new conversation if one isn't already active
                self.logger.info("Starting new conversation in response to wake word")
                await self.start_conversation()
            else:
                self.logger.info("Conversation already active, ignoring wake word")
                
        elif event_type == "call_state":
            if event.get("state") == "ended" and self.is_active:
                self.logger.info("Call ended event received, stopping conversation")
                await self.stop_conversation()

        elif event_type == "location_changed":
            if self.is_active and self.call_manager:
                location = event["data"]["location"]
                previous_location = event["data"]["previous_location"]
                
                # Skip if location is unknown
                if location == "unknown":
                    self.logger.debug("Skipping location change involving unknown location")
                    return
                    
                self.logger.debug(f"Sending location change to assistant: {previous_location} -> {location}")
                try:
                    self.call_manager.add_message(
                        "system",
                        f"""Your companion has moved from {previous_location} to {location}. 
                        If appropriate, you may wish to comment on their new location or incorporate it into your current activity.
                        If it's not really relevant to the conversation, just ignore it for now."""
                    )
                except Exception as e:
                    self.logger.error(f"Failed to send location change to assistant: {e}")
                
        # Enable later when we have a good way to engage with the proximity changes
        # elif event_type == "proximity_changed":
            # if self.is_active and self.call_manager:
            #     location = event["data"]["location"]
            #     distance = event["data"]["distance"]
            #     previous_distance = event["data"]["previous_distance"]
            #     self.logger.debug(f"Sending proximity change to assistant: {location} {previous_distance} -> {distance}")
            #     self.call_manager.add_message(
            #         "system",
            #         f"User's distance to {location} changed from {previous_distance} to {distance}"
            #     )
