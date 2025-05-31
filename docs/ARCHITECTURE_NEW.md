# Phoenix AI Companion Toy - New Architecture

## Overview

The Phoenix AI Companion Toy is a comprehensive interactive companion designed for children, embedding AI capabilities in a soft, bouncy ball toy. The system runs on a Raspberry Pi with various sensors and provides voice interaction, physical feedback, and adaptive activities.

This document describes the new architecture implemented with a focus on maintainability, type safety, and robust event-driven design.

## Core Architectural Principles

1. **Typed Event System**: All events are Pydantic models with strict type checking and validation
2. **Service-Based Architecture**: Functionality is divided into specialized services that communicate via events
3. **Hardware Abstraction**: Hardware interactions are isolated behind platform-independent abstractions
4. **Activity Orchestration**: User experiences are managed as activities that coordinate multiple services
5. **Observability First**: Built-in tracing, structured logging, and metrics collection

## Event System

The core of the architecture is a fully typed event system that provides:

- **Event Registry**: Central documentation of all events, their producers, and consumers
- **Event Bus**: Handles validation, tracing, and delivery of events between services
- **Event Tracer**: Records event flow for debugging and performance analysis

Events are defined as Pydantic models with explicit schemas:

```python
class WakeWordDetectedEvent(BaseEvent):
    type: Literal[EventType.WAKE_WORD_DETECTED] = EventType.WAKE_WORD_DETECTED
    confidence: Optional[float] = None
```

## Service Framework

Services are the primary components of the system, each responsible for specific functionality:

- **Lifecycle Management**: Standardized start/stop operations with dependency checking
- **Event Handling**: Declarative event production and consumption
- **Error Recovery**: Graceful degradation in face of errors
- **Automatic Registration**: Services declare their capabilities and dependencies

Example service definition:

```python
class WakeWordService(BaseService):
    PRODUCES_EVENTS = {
        EventType.WAKE_WORD_DETECTED: {
            'schema': WakeWordDetectedEvent,
            'description': 'Triggered when wake word is detected'
        }
    }
    
    CONSUMES_EVENTS = {}
    REQUIRED_SERVICES = {'audio'}
```

## Activity System

Activities are special services that represent interactive modes like conversation, hide-and-seek, etc.:

- **State Management**: Explicit state transitions with proper cleanup
- **Service Coordination**: Activities dynamically start/stop required services
- **Event Flow Control**: Activity-specific event handling based on current state

Activities build upon the service framework but add activity-specific lifecycle:

```python
class HideSeekActivity(BaseActivity):
    ACTIVITY_NAME = "hide_seek"
    REQUIRED_SERVICES = {'audio', 'location', 'led'}
```

## Hardware Abstraction Layer

Hardware components are abstracted behind platform-independent interfaces:

- **Platform Detection**: Automatic selection of platform-specific implementations
- **Simulation Capability**: Hardware can be simulated for development and testing
- **Error Handling**: Robust handling of hardware failures with fallback options

Example hardware abstraction:

```python
class AudioHardware(BaseHardware, ABC):
    @abstractmethod
    async def get_audio_chunk(self) -> np.ndarray:
        pass
    
    @classmethod
    def create(cls, config):
        # Factory method that returns platform-specific implementation
        if platform.system() == "Darwin":
            return MacOSAudioHardware(config)
        else:
            return RaspberryPiAudioHardware(config)
```

## Configuration System

Configuration is managed through Pydantic models with validation:

- **Type Safety**: Configurations are validated at startup
- **Environment Variables**: Automatic loading from environment variables
- **Hierarchical Structure**: Config is organized by component
- **Default Values**: Sensible defaults with clear override points

Example configuration:

```python
class AudioConfig(BaseConfig):
    format: str = "int16"
    channels: int = 1
    sample_rate: int = 16000
    
    @validator("format")
    def validate_format(cls, v):
        valid_formats = ["int16", "int32", "float32"]
        if v not in valid_formats:
            raise ValueError(f"Audio format must be one of {valid_formats}")
        return v
```

## Directory Structure

```
phoenix/
│
├── phoenix/                  # Main package
│   ├── core/                 # Core framework
│   │   ├── events.py         # Event base models
│   │   ├── registry.py       # Event registry
│   │   ├── bus.py            # Event bus
│   │   ├── tracing.py        # Event tracing
│   │   ├── service.py        # Service framework
│   │   └── config.py         # Configuration system
│   │
│   ├── events/               # Event definitions
│   │   ├── system.py         # System events
│   │   ├── voice.py          # Voice interaction events
│   │   ├── activities.py     # Activity events
│   │   └── sensors.py        # Sensor events
│   │
│   ├── services/             # Service implementations
│   │   ├── audio.py          # Audio service
│   │   ├── wakeword.py       # Wake word detection
│   │   ├── intent.py         # Intent processing
│   │   └── ...
│   │
│   ├── activities/           # Activity implementations
│   │   ├── base.py           # Activity base class
│   │   ├── sleep.py          # Sleep activity
│   │   ├── conversation.py   # Conversation activity
│   │   └── ...
│   │
│   ├── hardware/             # Hardware abstractions
│   │   ├── base.py           # Hardware base class
│   │   ├── audio.py          # Audio hardware interface
│   │   ├── led.py            # LED hardware interface
│   │   └── ...
│   │
│   └── main.py               # Application entry point
│
└── tests/                    # Test suite
    ├── unit/                 # Unit tests
    ├── integration/          # Integration tests
    └── system/               # System tests
```

## Event Flow Example

A typical interaction flow:

1. **Wake Word Detection**:
   - `WakeWordService` detects wake word
   - Publishes `WakeWordDetectedEvent`
   - `IntentService` subscribes and starts listening

2. **Intent Detection**:
   - `IntentService` processes audio
   - Publishes `IntentDetectedEvent` with intent info
   - `ActivityService` subscribes and handles intent

3. **Activity Transition**:
   - `ActivityService` starts appropriate activity (e.g., conversation)
   - Publishes `ActivityStartedEvent`
   - Activity coordinates required services

4. **Conversation Flow**:
   - `ConversationActivity` manages the conversation
   - Publishes `SpeechUpdateEvent` when user or assistant speaks
   - Other services respond accordingly (LEDs, haptics, etc.)

## Development Guidelines

1. **Event-First Design**:
   - Design flows in terms of events before implementing services
   - Document all events in the central registry
   - Use explicit typing for all event payloads

2. **Service Isolation**:
   - Services should be self-contained with clear responsibilities
   - Communicate only through events, not direct method calls
   - Declare all events produced and consumed

3. **Platform Independence**:
   - Use hardware abstractions for platform-specific code
   - Provide simulations for development/testing
   - Use feature detection, not platform detection when possible

4. **Testing Approach**:
   - Unit test services in isolation with mocked dependencies
   - Integration test event flows across services
   - System test complete activities

## Contribution Workflow

1. Define required events in appropriate modules
2. Add event definitions to registry
3. Implement services that produce and consume events
4. Create test cases for the new functionality
5. Update documentation to reflect changes

## Conclusion

This architecture solves the key maintainability issues identified in the previous system:

1. **Event System Complexity**: Explicit typing and central registry makes event flow clear
2. **Configuration Management**: Pydantic models with validation replace monolithic config
3. **Service Lifecycle**: Clear dependencies and lifecycle management
4. **Hardware Abstraction**: Platform-specific code is isolated behind interfaces
5. **Observability**: Built-in tracing and structured logging for debugging

The result is a more maintainable, testable, and robust application that preserves the capabilities of the original system while addressing its architectural limitations. 