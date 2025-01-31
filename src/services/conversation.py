import logging
import asyncio
from typing import Dict, Any
from .service import BaseService
from vapi import Vapi
from config import VAPI_API_KEY, ASSISTANT_ID

class ConversationService(BaseService):
    """Handles conversations with the AI assistant"""
    def __init__(self, manager):
        super().__init__(manager)
        self.vapi = Vapi(api_key=VAPI_API_KEY, manager=manager)
        self.is_active = False
        self._is_stopping = False  # Add state tracking for stop operation
        
    async def start(self):
        await super().start()
            
    async def stop(self):
        if self.is_active:
            await self.stop_conversation()
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
            self.logger.info("Initializing Vapi connection")
            await self.publish({"type": "conversation_starting"})
            self.vapi.start(assistant_id=ASSISTANT_ID)
            self.logger.info("Conversation started successfully")
            
        except Exception as e:
            self.logger.error("Failed to start Vapi: %s", str(e), exc_info=True)
            self.is_active = False  # Reset active state on failure
            await self.stop_conversation()
            # Notify other services about the failure
            await self.publish({
                "type": "conversation_error",
                "error": str(e)
            })
                
    async def stop_conversation(self):
        """Stop the current conversation"""
        if self.is_active and not self._is_stopping:
            self._is_stopping = True
            self.logger.info("Stopping conversation")
            try:
                self.vapi.stop()
                await self.publish({"type": "conversation_ended"})
            except Exception as e:
                self.logger.error("Error stopping conversation: %s", str(e), exc_info=True)
            finally:
                self.is_active = False
                self._is_stopping = False
                
    async def handle_event(self, event: Dict[str, Any]):
        """Handle events from other services"""
        event_type = event.get("type")
        self.logger.debug(f"Received event: {event_type}")
        
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