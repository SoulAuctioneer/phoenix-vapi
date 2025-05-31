from typing import Dict, Any
from services.service import BaseService
from managers.conversation_manager import ConversationManager
from managers.memory_manager import MemoryManager
from config import ASSISTANT_ID, ASSISTANT_CONFIG

class ConversationActivity(BaseService):
    """Handles conversations with the AI assistant"""
    def __init__(self, service_manager):
        super().__init__(service_manager)
        self.conversation_manager = None  # Will be initialized in start()
        self.is_active = False
        self._is_stopping = False  # Add state tracking for stop operation
        
    async def start(self):
        """Start the service (initializes call manager but doesn't start the conversation)"""
        await super().start()
        self.memory_manager = MemoryManager()
        # TODO: Don't pass service manager here, pass a callback for event publishing instead
        self.conversation_manager = await ConversationManager.create(publish_event_callback=self.publish, memory_manager=self.memory_manager)

    async def stop(self):
        """Stop the service and any active conversation"""
        if self.is_active:
            await self.stop_conversation()
        if self.conversation_manager:
            await self.conversation_manager.cleanup()
        await super().stop()
        
    async def start_conversation(self, assistant_config: Dict[str, Any] = ASSISTANT_CONFIG):
        """Start a conversation with the AI assistant
        
        This should only be called by the ActivityService when starting the CONVERSATION activity.
        """
        if self.is_active:
            self.logger.info("Conversation already active, ignoring start request")
            return
            
        if self._is_stopping:
            self.logger.info("Conversation service is stopping, cannot start new conversation")
            return
            
        self.logger.info("Starting new conversation")
        self.is_active = True

        try:
            # Start LED effect
            await self.publish({
                "type": "start_led_effect",
                "data": {
                    "effect_name": "TWINKLING",
                    "speed": 0.1
                }
            })
            # Start conversation
            self.logger.info("Initializing conversation call connection")
            await self.publish({"type": "conversation_starting"})
            await self.conversation_manager.start_call(assistant_id=ASSISTANT_ID, assistant_config=assistant_config)
            self.logger.info("Conversation started successfully")
            
        except Exception as e:
            self.logger.error("Failed to start conversation call: %s", str(e), exc_info=True)
            self.is_active = False  # Reset active state on failure
            await self.stop_conversation()
            # Notify other services about the failure
            await self.publish({
                "type": "conversation_error",
                "error": str(e)
            })
            
    async def stop_conversation(self):
        """Stop the current conversation
        
        This can be called directly by the ActivityService or in response to call_state events.
        """
        if not self.is_active:
            return
            
        self._is_stopping = True
        try:
            await self.conversation_manager.leave()
        except Exception as e:
            self.logger.error("Error stopping conversation: %s", str(e))
        finally:
            self.is_active = False
            self._is_stopping = False
            await self.publish({"type": "conversation_ended"})
        
    async def handle_event(self, event: Dict[str, Any]):
        """Handle events from other services"""
        event_type = event.get("type")
        
        if event_type == "intent_detection_started":
            # Mute local mic while intent detection is happening
            if self.is_active:
                self.logger.info("Conversation active, sending interrupt message and muting until intent detection completes")
                self.conversation_manager.interrupt_assistant()
                # await self.conversation_manager.mute()

        elif event_type == "intent_detection_timeout":
            # Unmute local mic when intent detection completes
            if self.is_active:
                self.logger.info("Intent detection completed, unmuting local mic")
                # await self.conversation_manager.unmute()

        elif event_type == "intent_detected":
            # Only handle conversation intent if we're already active
            intent = event.get("intent")
            if intent == "conversation" and self.is_active:
                self.logger.info("Conversation already active, passing along the `wake up` message")
                self.conversation_manager.add_message("user", "Wake up!")
                                    
        elif event_type == "call_state":
            if event.get("state") == "ended" and self.is_active:
                self.logger.info("Call ended event received, stopping conversation")
                await self.stop_conversation()

        elif event_type == "location_changed":
            # Disabled for now as we don't want this for the first meeting with Arianne
            pass
            # if self.is_active and self.conversation_manager:
            #     location = event["data"]["location"]
            #     previous_location = event["data"]["previous_location"]
                
            #     # Skip if location is unknown
            #     if location == "unknown":
            #         self.logger.debug("Skipping location change involving unknown location")
            #         return
                    
            #     self.logger.debug(f"Sending location change to assistant: {previous_location} -> {location}")
            #     try:
            #         self.conversation_manager.add_message(
            #             "system",
            #             f"""You and your companion have moved from {previous_location} to {location}. 
            #             If appropriate, you may wish to comment on their new location or incorporate it into your current activity.
            #             If it's not really relevant to the conversation, just ignore it for now."""
            #         )
            #     except Exception as e:
            #         self.logger.error(f"Failed to send location change to assistant: {e}")

        # Proximity changes are for scavenger hunts and hunts for other Phoenixes
        elif event_type == "proximity_changed":
            # We only care about proximity changes to other Phoenixes
            if self.is_active and self.conversation_manager:
                location = event["data"]["location"]
                if location == "blue_phoenix":
                    distance = event["data"]["distance"]
                    previous_distance = event["data"]["previous_distance"]
                    self.logger.debug(f"Sending proximity change to assistant: {location} {previous_distance} -> {distance}")
                    self.conversation_manager.add_message(
                        "system",
                        f"You are now {distance} distance away from your little sister."
                    )
