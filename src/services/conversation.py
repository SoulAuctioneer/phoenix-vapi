import logging
import asyncio
from typing import Dict, Any
from .base import BaseService
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
        if not self.is_active and not self._is_stopping:  # Only start if not active and not in process of stopping
            logging.info("Starting new conversation")
            self.is_active = True
            try:
                logging.info("Attempting to start Vapi connection")
                await self.manager.publish_event({"type": "conversation_starting"})  # New event
                self.vapi.start(assistant_id=ASSISTANT_ID)
            except Exception as e:
                logging.error("Failed to start Vapi: %s", str(e), exc_info=True)
                await self.stop_conversation()
                
    async def stop_conversation(self):
        """Stop the current conversation"""
        if self.is_active and not self._is_stopping:
            self._is_stopping = True
            logging.info("Stopping conversation")
            try:
                self.vapi.stop()
                await self.manager.publish_event({"type": "conversation_ended"})
            except Exception as e:
                logging.error("Error stopping conversation: %s", str(e), exc_info=True)
            finally:
                self.is_active = False
                self._is_stopping = False
                
    async def handle_event(self, event: Dict[str, Any]):
        """Handle events from other services"""
        event_type = event.get("type")
        
        if event_type == "wake_word_detected":
            if not self.is_active and not self._is_stopping:  # Only handle if not in a transitional state
                await self.start_conversation()
        elif event_type == "call_state":
            if event.get("state") == "ended" and self.is_active:
                await self.stop_conversation() 