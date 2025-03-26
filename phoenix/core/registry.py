"""
Event and service registry for the Phoenix AI Companion Toy.

This module provides registration and validation for events, their producers and consumers.
It enables discovery and documentation of event flows through the system.
"""

import logging
from typing import Dict, Set, Type, Any, Optional, Callable, Awaitable
from .events import EventType, BaseEvent

# Type aliases
EventHandler = Callable[[BaseEvent], Awaitable[None]]

class EventRegistry:
    """
    Central registry of all event types, producers, and consumers.
    
    This registry maintains information about:
    - Which services produce which events
    - Which services consume which events
    - The schema (event class) for each event type
    - Documentation about each event type
    
    This enables validation, documentation, and visualization of event flows.
    """
    
    def __init__(self):
        self._producers: Dict[EventType, Set[str]] = {}
        self._consumers: Dict[EventType, Set[str]] = {}
        self._event_schemas: Dict[EventType, Dict[str, Any]] = {}
        self._logger = logging.getLogger(__name__)
        
    def register_event(self, event_type: EventType, event_schema: Type[BaseEvent], description: str):
        """
        Register a new event type with its schema and description.
        
        Args:
            event_type: The type of event being registered
            event_schema: The Pydantic model class for this event type
            description: Human-readable description of this event type
        """
        self._event_schemas[event_type] = {
            'schema': event_schema,
            'description': description
        }
        self._logger.debug(f"Registered event type: {event_type}")
        
    def register_producer(self, service_name: str, event_type: EventType):
        """
        Register a service as an event producer.
        
        Args:
            service_name: Name of the service producing the event
            event_type: Type of event the service produces
        """
        if event_type not in self._producers:
            self._producers[event_type] = set()
        self._producers[event_type].add(service_name)
        self._logger.debug(f"Registered producer {service_name} for {event_type}")
        
    def register_consumer(self, service_name: str, event_type: EventType):
        """
        Register a service as an event consumer.
        
        Args:
            service_name: Name of the service consuming the event
            event_type: Type of event the service consumes
        """
        if event_type not in self._consumers:
            self._consumers[event_type] = set()
        self._consumers[event_type].add(service_name)
        self._logger.debug(f"Registered consumer {service_name} for {event_type}")
        
    def validate_schema(self, event: BaseEvent) -> bool:
        """
        Validate that an event matches its registered schema.
        
        Args:
            event: The event to validate
            
        Returns:
            bool: True if validation passes
            
        Raises:
            ValueError: If event type is unknown
            TypeError: If event doesn't match registered schema
        """
        event_type = event.type
        if event_type not in self._event_schemas:
            raise ValueError(f"Unknown event type: {event_type}")
            
        schema = self._event_schemas[event_type]['schema']
        if not isinstance(event, schema):
            raise TypeError(f"Event does not match schema for {event_type}")
            
        return True
    
    def get_event_flow(self, event_type: EventType) -> Dict[str, Set[str]]:
        """
        Get all producers and consumers for an event type.
        
        Args:
            event_type: The event type to get flow information for
            
        Returns:
            Dict containing producers and consumers sets
        """
        return {
            'producers': self._producers.get(event_type, set()),
            'consumers': self._consumers.get(event_type, set())
        }
    
    def get_event_description(self, event_type: EventType) -> Optional[str]:
        """
        Get the description for an event type.
        
        Args:
            event_type: The event type to get the description for
            
        Returns:
            The event description or None if not found
        """
        if event_type in self._event_schemas:
            return self._event_schemas[event_type]['description']
        return None
    
    def get_event_schema(self, event_type: EventType) -> Optional[Type[BaseEvent]]:
        """
        Get the schema class for an event type.
        
        Args:
            event_type: The event type to get the schema for
            
        Returns:
            The event schema class or None if not found
        """
        if event_type in self._event_schemas:
            return self._event_schemas[event_type]['schema']
        return None
    
    def get_all_event_types(self) -> Set[EventType]:
        """
        Get all registered event types.
        
        Returns:
            Set of all registered event types
        """
        return set(self._event_schemas.keys())
    
    def generate_documentation(self) -> Dict[str, Any]:
        """
        Generate comprehensive documentation of the event system.
        
        Returns:
            Dictionary with complete event documentation
        """
        doc = {}
        for event_type in self.get_all_event_types():
            doc[event_type] = {
                'description': self.get_event_description(event_type),
                'producers': list(self._producers.get(event_type, set())),
                'consumers': list(self._consumers.get(event_type, set())),
                'schema': str(self.get_event_schema(event_type))
            }
        return doc


class ServiceRegistry:
    """
    Registry for services and their lifecycle management.
    
    This registry keeps track of all services, their dependencies, and their state.
    """
    
    def __init__(self):
        self._services = {}
        self._dependencies = {}
        self._states = {}
        self._logger = logging.getLogger(__name__)
    
    def register_service(self, service_name: str, service_instance: Any):
        """
        Register a service with the registry.
        
        Args:
            service_name: Name of the service
            service_instance: The service instance
        """
        self._services[service_name] = service_instance
        self._states[service_name] = "registered"
        self._logger.debug(f"Registered service: {service_name}")
    
    def register_dependency(self, service_name: str, depends_on: str):
        """
        Register a dependency between services.
        
        Args:
            service_name: Name of the dependent service
            depends_on: Name of the service depended upon
        """
        if service_name not in self._dependencies:
            self._dependencies[service_name] = set()
        self._dependencies[service_name].add(depends_on)
        
    def get_service(self, service_name: str) -> Optional[Any]:
        """
        Get a service by name.
        
        Args:
            service_name: Name of the service to retrieve
            
        Returns:
            The service instance or None if not found
        """
        return self._services.get(service_name)
    
    def set_service_state(self, service_name: str, state: str):
        """
        Update a service's state.
        
        Args:
            service_name: Name of the service
            state: New state of the service
        """
        self._states[service_name] = state
        self._logger.debug(f"Service {service_name} state changed to {state}")
    
    def get_service_state(self, service_name: str) -> Optional[str]:
        """
        Get a service's state.
        
        Args:
            service_name: Name of the service
            
        Returns:
            The service state or None if not found
        """
        return self._states.get(service_name)
    
    def get_dependent_services(self, service_name: str) -> Set[str]:
        """
        Get services that depend on the specified service.
        
        Args:
            service_name: Name of the service
            
        Returns:
            Set of services that depend on the specified service
        """
        dependents = set()
        for service, dependencies in self._dependencies.items():
            if service_name in dependencies:
                dependents.add(service)
        return dependents
    
    def get_dependencies(self, service_name: str) -> Set[str]:
        """
        Get services that the specified service depends on.
        
        Args:
            service_name: Name of the service
            
        Returns:
            Set of services the specified service depends on
        """
        return self._dependencies.get(service_name, set())
    
    def get_all_services(self) -> Dict[str, Any]:
        """
        Get all registered services.
        
        Returns:
            Dictionary of service names to service instances
        """
        return self._services.copy() 