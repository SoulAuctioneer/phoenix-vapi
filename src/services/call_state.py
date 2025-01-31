from enum import Enum
import asyncio
import logging
from typing import Dict, Any, Callable, Optional

class CallState(Enum):
    """Possible states for a call"""
    INITIALIZING = "initializing"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"

class StateManager:
    """Manages state transitions and notifications"""
    def __init__(self, service: 'BaseService'):
        self.state = CallState.INITIALIZING
        self.state_lock = asyncio.Lock()
        self.service = service
        self._state_handlers: Dict[CallState, Callable] = {}
        
    def register_handler(self, state: CallState, handler: Callable):
        """Register a handler for a specific state"""
        self._state_handlers[state] = handler
        
    async def transition_to(self, new_state: CallState):
        """Transition to a new state and notify listeners"""
        async with self.state_lock:
            old_state = self.state
            self.state = new_state
            
            # Log the transition
            self.service.logger.info(f"Call state transition: {old_state.value} -> {new_state.value}")
            
            # Publish event
            await self.service.publish({
                "type": "call_state_changed",
                "old_state": old_state.value,
                "new_state": new_state.value
            })
            
            # Execute state handler if one exists
            if new_state in self._state_handlers:
                try:
                    await self._state_handlers[new_state]()
                except Exception as e:
                    self.service.logger.error(f"Error in state handler for {new_state.value}: {e}")
                    await self.transition_to(CallState.ERROR)
    
    @property
    def current_state(self) -> CallState:
        """Get the current state"""
        return self.state
    
    def is_in_state(self, *states: CallState) -> bool:
        """Check if current state is one of the given states"""
        return self.state in states
    
    def can_transition_to(self, new_state: CallState) -> bool:
        """Check if transition to new state is valid"""
        # Define valid transitions
        valid_transitions = {
            CallState.INITIALIZING: [CallState.CONNECTING, CallState.ERROR],
            CallState.CONNECTING: [CallState.CONNECTED, CallState.ERROR, CallState.CLOSED],
            CallState.CONNECTED: [CallState.ACTIVE, CallState.DISCONNECTING, CallState.ERROR],
            CallState.ACTIVE: [CallState.DISCONNECTING, CallState.ERROR],
            CallState.DISCONNECTING: [CallState.CLOSED, CallState.ERROR],
            CallState.ERROR: [CallState.INITIALIZING, CallState.CLOSED],
            CallState.CLOSED: [CallState.INITIALIZING]
        }
        
        return new_state in valid_transitions.get(self.state, []) 