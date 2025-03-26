# Phoenix Voice Assistant - Architecture Guide

## Application Purpose

The Phoenix is a bouncy ball and an interactive, smart, beautiful AI-powered companion and toy for children. It provides emotional, social, and cognitive engagement and support via dynamic nurturing mechanics, guided play, tutoring, and wellness practices. This app is the Phoenix's software, designed to be run on a Raspberry Pi embedded in the ball.

Key capabilities include:
- Starting activities via wake word and intent detection
- AI voice chat and interaction via an LLM and speech recognition/synthesis
- Physical touch sensing with stroking and purring responses
- Adaptive personalization based on interaction patterns
- Location awareness via Bluetooth beacon tracking
- Various activity modes (conversation, hide & seek, movement play, cuddling, sleep)
- LED patterns for visual feedback
- Audio effects and voice responses

## Architectural Approach

### Service-Based Architecture

The Phoenix application is built on an event-driven, service-based architecture with the following key characteristics:

1. **Service Manager**: A central service manager coordinates all services, handling event distribution and service lifecycle management.

2. **Event-Driven Communication**: Services communicate asynchronously through a publish/subscribe event system. Each service can publish events that others subscribe to, enabling loose coupling between components.

3. **Shared Global State**: A centralized global state object maintains key application state information that services can access without direct coupling.

4. **Activity-Based Orchestration**: The system uses an activity-based approach where different modes (conversation, hide & seek, sleep, etc.) are represented as activities that coordinate specific services they require.

5. **Asynchronous Operation**: Built using Python's asyncio for non-blocking, concurrent execution of services.

### Sensor Integration

The application integrates with various sensors to enable interaction:
- Audio input/output for voice detection and responses
- BLE beacons for location tracking
- Accelerometer for motion detection
- Touch sensors for physical interaction
- LED controllers for visual feedback

## Project Structure

### Core Components

- `src/main.py` - Entry point that initializes and manages the application lifecycle
- `src/config.py` - Comprehensive configuration settings for all services and features
- `src/services/service.py` - Base service implementation and service manager

### Service Layer

The `src/services/` directory contains individual service implementations:

- **Core Services**
  - `audio_service.py` - Manages audio input and output
  - `wakeword_service.py` - Handles wake word detection (using Picovoice Porcupine)
  - `intent_service.py` - Processes voice commands to determine user intent
  - `conversation_service.py` - Manages voice interactions with the AI assistant (via Vapi)
  - `activity_service.py` - Orchestrates different activity modes and their required services

- **Hardware Integration**
  - `led_service.py` - Controls LED patterns for visual feedback
  - `haptic_service.py` - Manages haptic feedback for physical interaction
  - `sensor_service.py` - Interfaces with various physical sensors
  - `battery_service.py` - Monitors battery status on the physical device
  - `accelerometer_service.py` - Processes accelerometer data

- **Activity Services**
  - `sleep_activity.py` - Implements sleep mode behavior
  - `hide_seek_service.py` - Implements hide and seek game behavior
  - `move_activity.py` - Implements motion-based activities

### Manager Layer

The `src/managers/` directory contains lower-level managers that interface with specific hardware or external APIs:

- Managers for speech processing
- Location and BLE beacon handling
- Hardware interfaces and drivers

### Utility Layer

The `src/utils/` directory contains shared utilities and helper functions used across the application.

## Data Flow

1. **Startup Flow**:
   - Application initializes the service manager
   - Core services are started in dependency order
   - Initial activity (typically sleep mode) is triggered

2. **Interaction Flow**:
   - Wake word detection triggers intent service
   - Intent detection determines user's desired activity
   - Activity service transitions to the appropriate activity
   - Activity coordinates specific services for its operation
   - Services communicate via events to respond to user actions

3. **State Management**:
   - Global state tracks key information like:
     - Current location
     - Conversation status
     - Sensor readings
     - Audio state

## Cross-Platform Compatibility

The application is designed to run on:
- Raspberry Pi (primary target for the physical toy)
- macOS (for development and testing)

Platform-specific code is isolated and controlled via configuration settings to enable development on both platforms.

## Development Guidelines

### Adding New Features

1. Determine if the feature requires a new service or can be integrated into an existing one
2. If creating a new service:
   - Inherit from `BaseService`
   - Implement `start()`, `stop()`, and `handle_event()` methods
   - Register event subscribers in the `start()` method

3. If creating a new activity:
   - Add the activity type to `ActivityType` enum in `activity_service.py`
   - Define required services in the `ACTIVITY_REQUIREMENTS` dictionary
   - Implement activity-specific service for complex activities

### Event Handling

Events should follow a standardized structure:
```python
{
    "type": "event_name",
    "producer_name": "service_name",  # Service that produced the event
    "data": {  # Optional additional data
        # Event-specific information
    }
}
```

### Configuration

All configuration should be defined in `config.py` using class-based organization for related settings.

## Deployment

The application is designed to be deployed on a Raspberry Pi embedded in the Phoenix toy. Installation can be performed using the `install.sh` script that handles dependencies and environment setup.

## API Keys and Security

The application requires several API keys to function:
- VAPI API key for voice AI
- Picovoice access key for wake word detection
- OpenAI API key (optional) for alternative intent detection

These keys should be specified in the `.env` file which is not committed to version control. 