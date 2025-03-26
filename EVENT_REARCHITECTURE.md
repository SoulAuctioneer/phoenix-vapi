# Phoenix AI Companion Toy  - Event System Rearchitecture

## Executive Summary

This document outlines a comprehensive redesign of the Phoenix AI Companion Toy event architecture, focusing on improved maintainability, type safety, testability, and operational robustness. The primary goal is to preserve the application's service-based approach while formalizing event contracts, reducing implicit dependencies, and enforcing type safety throughout the codebase.

Unlike the previous phased approach, this plan assumes a complete rearchitecture during a single intensive sprint, enabling us to make a clean break from the existing implementation and avoid maintaining dual systems.

## New Architecture Design

### Core Architectural Principles

1. **Typed Event System**: Replace untyped dictionary events with explicit Pydantic models
2. **Formal Event Registry**: Document and enforce producer/consumer relationships
3. **Layered Architecture**: Clear separation between hardware abstraction, services, and activities
4. **Dependency Injection**: Explicit service dependencies over implicit event coupling
5. **Observability First**: Built-in tracing, logging, and metrics
6. **Progressive Error Recovery**: Graceful degradation when services fail

### Technology Stack

- **Python 3.9+**: For improved typing support
- **Pydantic**: For typed data models and validation
- **Asyncio**: For asynchronous programming
- **pytest-asyncio**: For testing async code
- **Structlog**: For structured, contextual logging
- **Prometheus Client**: For metrics and monitoring

### Event System Design

```python
from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Any, Literal
from enum import Enum
import time

class EventType(str, Enum):
    WAKE_WORD_DETECTED = "wake_word_detected"
    INTENT_DETECTED = "intent_detected"
    CONVERSATION_STARTING = "conversation_starting"
    # ... other events

class BaseEvent(BaseModel):
    """Base model for all events with common metadata"""
    type: EventType
    producer_name: str
    timestamp: float = Field(default_factory=time.time)
    trace_id: Optional[str] = None  # For event tracing

# Example typed event
class IntentDetectedEvent(BaseEvent):
    type: Literal[EventType.INTENT_DETECTED]  # Restrict to specific type
    intent: str
    slots: Dict[str, Any] = {}
    confidence: float
```

### Event Flow and Registry

```python
class EventRegistry:
    """Central registry of all event types, producers, and consumers"""
    
    def __init__(self):
        self._producers = {}
        self._consumers = {}
        self._event_schemas = {}
        
    def register_event(self, event_type: EventType, event_schema, description: str):
        """Register a new event type with its schema and description"""
        self._event_schemas[event_type] = {
            'schema': event_schema,
            'description': description
        }
        
    def register_producer(self, service_name: str, event_type: EventType):
        """Register a service as an event producer"""
        if event_type not in self._producers:
            self._producers[event_type] = set()
        self._producers[event_type].add(service_name)
        
    def register_consumer(self, service_name: str, event_type: EventType):
        """Register a service as an event consumer"""
        if event_type not in self._consumers:
            self._consumers[event_type] = set()
        self._consumers[event_type].add(service_name)
        
    def validate_schema(self, event):
        """Validate that an event matches its registered schema"""
        event_type = event.type
        if event_type not in self._event_schemas:
            raise ValueError(f"Unknown event type: {event_type}")
            
        schema = self._event_schemas[event_type]['schema']
        if not isinstance(event, schema):
            raise TypeError(f"Event does not match schema for {event_type}")
            
    def get_event_flow(self, event_type: EventType):
        """Get all producers and consumers for an event type"""
        return {
            'producers': self._producers.get(event_type, set()),
            'consumers': self._consumers.get(event_type, set())
        }
```

### Enhanced Event Bus

```python
class EventBus:
    """Central event bus for delivering typed events between services"""
    
    def __init__(self, registry: EventRegistry, tracer=None):
        self.registry = registry
        self.tracer = tracer
        self.subscribers = {}
        
    async def publish(self, event: BaseEvent, sender: str):
        """Publish an event to all subscribers"""
        # Validate event against registry
        self.registry.validate_schema(event)
        
        # Set producer name if not set
        if not event.producer_name:
            event.producer_name = sender
            
        # Add trace ID if available
        if self.tracer and not event.trace_id:
            event.trace_id = self.tracer.get_current_trace_id()
            
        # Trace the event
        if self.tracer:
            self.tracer.record_event(event)
            
        # Find subscribers
        event_type = event.type
        subscribers = self.subscribers.get(event_type, [])
        
        # Deliver to subscribers
        for subscriber in subscribers:
            try:
                await subscriber(event)
            except Exception as e:
                logging.error(f"Error delivering event {event_type} to {subscriber.__qualname__}: {e}")
                # Additional error handling can be added here
                
    def subscribe(self, event_type: EventType, handler, service_name: str):
        """Subscribe a handler to events of a specific type"""
        if event_type not in self.subscribers:
            self.subscribers[event_type] = []
        self.subscribers[event_type].append(handler)
        
        # Update registry
        self.registry.register_consumer(service_name, event_type)
```

### Improved Service Base Class

```python
class BaseService:
    """Base class for all services with improved event handling"""
    
    # Define events produced/consumed by this service
    PRODUCES_EVENTS = {}  # Map of EventType to description
    CONSUMES_EVENTS = {}  # Map of EventType to handler method name
    
    def __init__(self, event_bus: EventBus, service_registry, name=None):
        self.event_bus = event_bus
        self.service_registry = service_registry
        self.name = name or self.__class__.__name__
        self.logger = structlog.get_logger(service=self.name)
        self._running = False
        
        # Register produced events
        for event_type, description in self.PRODUCES_EVENTS.items():
            event_bus.registry.register_producer(self.name, event_type)
            
        # Subscribe to consumed events
        for event_type, handler_name in self.CONSUMES_EVENTS.items():
            handler = getattr(self, handler_name)
            event_bus.subscribe(event_type, handler, self.name)
            
    async def start(self):
        """Start the service"""
        self._running = True
        self.logger.info("service_started")
        
    async def stop(self):
        """Stop the service"""
        self._running = False
        self.logger.info("service_stopped")
        
    async def publish(self, event: BaseEvent):
        """Publish an event through the bus"""
        if not self._running:
            self.logger.warning("attempted_publish_while_stopped", event_type=event.type)
            return
            
        await self.event_bus.publish(event, self.name)
```

### Configuration Management

```python
from pydantic import BaseSettings, Field

class ServiceSettings(BaseSettings):
    """Base configuration for all services"""
    debug: bool = False
    metrics_enabled: bool = True

class AudioSettings(ServiceSettings):
    """Audio service configuration"""
    sample_rate: int = 16000
    chunk_size: int = 640
    default_volume: float = 1.0
    
    class Config:
        env_prefix = 'AUDIO_'  # Read from AUDIO_* environment variables
```

## Single-Sprint Implementation Strategy

Unlike a phased approach, we'll implement this architecture in a single intensive sprint. This approach has higher short-term risk but eliminates the complexity of maintaining dual systems and accelerates the delivery of a cleaner, more maintainable codebase.

### Day 1-2: Infrastructure Setup

1. **Core Framework Development**
   - Implement the EventRegistry and EventBus
   - Create BaseEvent class and service framework
   - Set up project structure with new layout

2. **Configuration System**
   - Convert configuration to Pydantic models
   - Set up environment variable integration
   - Create validation for all configuration parameters

3. **Tooling Setup**
   - Configure linting and type checking
   - Set up testing framework with pytest-asyncio
   - Implement CI workflows for automated testing

### Day 3-5: Event Model Implementation

1. **Event Definition**
   - Create enums for all event types
   - Implement Pydantic models for all events
   - Document all events in the registry

2. **Service Base Classes**
   - Implement BaseService with typed event support
   - Create ServiceRegistry for lifecycle management
   - Build observability hooks for tracing and metrics

3. **Event Visualization**
   - Generate event flow diagrams
   - Create documentation from event registry
   - Build debug tools for event tracing

### Day 6-10: Service Implementation

1. **Core Services Rewrite**
   - Implement each service with the new framework:
     - WakeWordService
     - IntentService
     - ActivityService
     - AudioService
     - ConversationService
   - Add comprehensive unit tests for each

2. **Hardware Integration**
   - Create hardware abstraction interfaces
   - Implement platform-specific providers
   - Add simulation mode for testing

3. **Activity System Rewrite**
   - Implement Activity base class
   - Rewrite all activities using the new framework
   - Build state transition management

### Day 11-13: Integration and Testing

1. **System Integration**
   - Connect all services together
   - Test event flow through the system
   - Verify error handling and recovery

2. **Regression Testing**
   - Compare behavior with previous implementation
   - Fix any functional regressions
   - Validate performance characteristics

3. **Hardware Testing**
   - Test on target hardware (Raspberry Pi)
   - Validate sensor integration
   - Verify resource utilization

### Day 14-15: Deployment and Documentation

1. **Deployment Preparation**
   - Update installation scripts
   - Create deployment packages
   - Prepare rollback procedures

2. **Documentation Finalization**
   - Complete API documentation
   - Update architecture documentation
   - Create developer onboarding guide

3. **Quality Assurance**
   - Conduct final testing
   - Address any outstanding issues
   - Sign off for production deployment

## New Project Structure

```
phoenix/
│
├── phoenix/                # Main package
│   ├── __init__.py
│   ├── core/               # Core framework
│   │   ├── events.py       # Event base models
│   │   ├── registry.py     # Event and service registries
│   │   ├── service.py      # BaseService implementation
│   │   ├── config.py       # Configuration system
│   │   └── tracing.py      # Event tracing utilities
│   │
│   ├── events/             # Event definitions
│   │   ├── __init__.py
│   │   ├── conversation.py # Conversation-related events
│   │   ├── sensors.py      # Sensor events
│   │   └── activities.py   # Activity events
│   │
│   ├── services/           # Service implementations
│   │   ├── __init__.py
│   │   ├── audio.py        # Audio handling
│   │   ├── wakeword.py     # Wake word detection
│   │   ├── intent.py       # Intent processing
│   │   └── ...
│   │
│   ├── activities/         # Activity implementations
│   │   ├── __init__.py
│   │   ├── base.py         # Activity base class
│   │   ├── sleep.py        # Sleep activity
│   │   ├── conversation.py # Conversation activity
│   │   └── ...
│   │
│   ├── hardware/           # Hardware abstractions
│   │   ├── __init__.py
│   │   ├── audio.py        # Audio I/O
│   │   ├── leds.py         # LED control
│   │   ├── sensors.py      # Sensor interfaces
│   │   └── ...
│   │
│   ├── utils/              # Utility functions
│   │   ├── __init__.py
│   │   └── ...
│   │
│   └── main.py             # Application entry point
│
├── tests/                  # Test suite
│   ├── conftest.py         # Test fixtures
│   ├── unit/               # Unit tests
│   ├── integration/        # Integration tests
│   └── system/             # End-to-end tests
│
├── docs/                   # Documentation
│   ├── events.md           # Event documentation
│   ├── architecture.md     # Architecture overview
│   └── ...
│
├── scripts/                # Utility scripts
│   ├── install.sh          # Installation script
│   └── ...
│
├── pyproject.toml          # Project metadata and dependencies
├── setup.py                # Installation script
└── README.md               # Project overview
```

## Key Architectural Improvements

### 1. Type Safety
- All events are Pydantic models with validation
- Static type checking via Python type hints
- Runtime validation through Pydantic

### 2. Event Documentation
- Centralized event registry
- Automatic documentation generation
- Explicit producer-consumer relationships

### 3. Error Handling
- Structured error recovery
- Graceful service degradation
- Explicit error events for coordinating recovery

### 4. Testing
- Service mocking framework
- Hardware simulation for testing
- Comprehensive unit and integration test suite

### 5. Observability
- Structured logging with context
- Distributed tracing of events
- Metrics for performance monitoring

### 6. Configuration
- Validated configuration via Pydantic models
- Environment variable integration
- Hierarchical configuration system

## Risks and Mitigations

### High-Risk Areas

1. **Complete Rewrite Risk**
   - **Risk**: Introducing new bugs or missing edge cases in the rewrite
   - **Mitigation**: Comprehensive test suite comparing old and new behavior

2. **Deadline Pressure**
   - **Risk**: Rushed implementation may sacrifice quality
   - **Mitigation**: Prioritize core functionality; defer non-critical improvements

3. **Integration Complexity**
   - **Risk**: Difficulty reconnecting all system components
   - **Mitigation**: Define clear interfaces; use composition over inheritance

4. **Hardware Dependencies**
   - **Risk**: Hardware-specific code may be difficult to test
   - **Mitigation**: Create robust hardware abstraction layer and simulation

### Contingency Plan

If the sprint deadline approaches and the system is not fully operational:

1. Focus on core event system and prioritize essential services
2. Create wrapper classes to maintain backward compatibility
3. Document incomplete items for follow-up work
4. Establish clear criteria for production readiness

## Conclusion

This aggressive single-sprint approach to rearchitecting the Phoenix AI Companion Toy event system offers the advantage of a clean break from the existing implementation, eliminating the need to maintain dual systems during migration. While more risky than an incremental approach, it enables us to deliver a complete solution faster and avoids the complexity of a hybrid system.

The proposed architecture directly addresses the event system complexity identified as a key maintainability challenge, while preserving the core strengths of the service-based approach. By formalizing event contracts through typed models and establishing a centralized registry, we will significantly improve the system's maintainability, testability, and long-term evolution potential. 