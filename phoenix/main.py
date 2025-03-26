"""
Main entry point for the Phoenix AI Companion Toy.

This module initializes the core components of the system and starts the application.
It handles signal management, logging setup, and system lifecycle.
"""

import asyncio
import logging
import signal
import sys
import time
import structlog
from typing import Set, Dict, Any, Optional, List

from phoenix.core import (
    EventRegistry, ServiceRegistry, EventBus, EventTracer, get_config
)
from phoenix.events.system import ApplicationStartupCompletedEvent

# Import services (these will be initialized later)
# from phoenix.services.audio import AudioService
# from phoenix.services.wakeword import WakeWordService
# from phoenix.services.intent import IntentService
# from phoenix.services.activity import ActivityService

# Configure structured logging
def setup_logging():
    """Configure structured logging for the application."""
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer()
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    
    # Set up stdlib logging
    logging.basicConfig(
        format="%(message)s",
        level=logging.INFO,
        stream=sys.stdout,
    )

class PhoenixApplication:
    """
    Main application class for Phoenix AI Companion Toy.
    
    This class initializes and manages the core components of the system,
    including the event system, service registry, and services.
    """
    
    def __init__(self):
        """Initialize the Phoenix application."""
        self.logger = structlog.get_logger(app="phoenix")
        self.config = get_config()
        
        # Set up core components
        self.event_registry = EventRegistry()
        self.service_registry = ServiceRegistry()
        
        # Set up event tracing if enabled
        if self.config.event.tracing_enabled:
            self.event_tracer = EventTracer(max_events=self.config.event.max_trace_events)
        else:
            self.event_tracer = None
            
        # Create event bus
        self.event_bus = EventBus(self.event_registry, self.event_tracer)
        
        # Services to initialize
        self.services = {}
        self._running = True
        
    async def initialize(self):
        """Initialize all services and start the application."""
        self.logger.info("Initializing Phoenix AI Companion Toy")
        
        try:
            # Initialize core services in dependency order
            # TODO: Add service initialization code
            # self.services["audio"] = await self._init_service(AudioService)
            # self.services["wakeword"] = await self._init_service(WakeWordService)
            # self.services["intent"] = await self._init_service(IntentService)
            # self.services["activity"] = await self._init_service(ActivityService)
            
            # Publish application startup completed event
            await self.event_bus.publish(
                ApplicationStartupCompletedEvent(producer_name="phoenix"),
                "phoenix"
            )
            
            self.logger.info("Phoenix AI Companion Toy initialization complete")
            
        except Exception as e:
            self.logger.error("Failed to initialize application", error=str(e), exc_info=True)
            raise
            
    async def _init_service(self, service_class, **kwargs):
        """
        Initialize and start a service.
        
        Args:
            service_class: The service class to initialize
            **kwargs: Additional arguments to pass to the service constructor
            
        Returns:
            The initialized service instance
        """
        service_name = service_class.__name__
        self.logger.info(f"Initializing service: {service_name}")
        
        # Create service instance
        service = service_class(
            event_bus=self.event_bus,
            service_registry=self.service_registry,
            config=self.config,
            **kwargs
        )
        
        # Start the service
        try:
            await service.start()
            self.logger.info(f"Service started: {service_name}")
            return service
        except Exception as e:
            self.logger.error(f"Failed to start service: {service_name}", 
                             error=str(e), exc_info=True)
            raise
            
    async def run(self):
        """Run the application main loop."""
        try:
            # Run until interrupted
            while self._running:
                await asyncio.sleep(1)
                
        except asyncio.CancelledError:
            self.logger.info("Application task cancelled")
            
        finally:
            await self.shutdown()
            
    async def shutdown(self):
        """Shut down all services and clean up resources."""
        if not self._running:
            return
            
        self._running = False
        self.logger.info("Shutting down Phoenix AI Companion Toy")
        
        # Stop services in reverse dependency order
        for name, service in reversed(list(self.services.items())):
            try:
                self.logger.info(f"Stopping service: {name}")
                await service.stop()
            except Exception as e:
                self.logger.error(f"Error stopping service {name}: {e}")
                
        self.logger.info("Phoenix AI Companion Toy shutdown complete")
        
    def handle_signal(self, sig):
        """
        Handle termination signals.
        
        Args:
            sig: The signal received
        """
        self.logger.info(f"Received signal {sig.name}, shutting down")
        self._running = False
        
        # Schedule the shutdown
        asyncio.create_task(self.shutdown())
        
        # Cancel all tasks except the current one
        for task in asyncio.all_tasks():
            if task is not asyncio.current_task():
                task.cancel()

async def main():
    """Application entry point."""
    # Set up logging
    setup_logging()
    
    # Create and initialize the application
    app = PhoenixApplication()
    
    # Set up signal handlers
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(
            sig, lambda s=sig: app.handle_signal(s))
    
    # Initialize and run the application
    await app.initialize()
    await app.run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logging.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1) 