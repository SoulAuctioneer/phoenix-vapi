"""
ServerManager handles the creation and management of local servers with ngrok tunnels.
This includes Flask HTTP servers and WebSocket servers that can be exposed to the internet via ngrok.
"""
import os
import asyncio
import threading
import logging
from typing import Optional, Dict, Any, Callable, Set
from flask import Flask
import websockets
from pyngrok import ngrok, conf

logger = logging.getLogger(__name__)


class NgrokTunnel:
    """Represents an ngrok tunnel with its configuration and public URL."""
    def __init__(self, port: int, protocol: str = "http"):
        self.port = port
        self.protocol = protocol
        self.tunnel = None
        self.public_url = None
        
    def connect(self) -> str:
        """Establish the ngrok tunnel and return the public URL."""
        self.tunnel = ngrok.connect(self.port, self.protocol)
        self.public_url = self.tunnel.public_url
        return self.public_url
        
    def disconnect(self):
        """Disconnect the ngrok tunnel."""
        if self.tunnel:
            ngrok.disconnect(self.tunnel.public_url)
            self.tunnel = None
            self.public_url = None


class FlaskServer:
    """Manages a Flask server running in a separate thread."""
    def __init__(self, app: Flask, port: int, host: str = "0.0.0.0"):
        self.app = app
        self.port = port
        self.host = host
        self.thread = None
        self.stop_event = threading.Event()
        self.server = None
        
    def start(self):
        """Start the Flask server in a separate thread."""
        self.thread = threading.Thread(target=self._run_server, daemon=True)
        self.thread.start()
        logger.info(f"Flask server started on {self.host}:{self.port}")
        
    def stop(self, timeout: float = 5.0):
        """Stop the Flask server."""
        self.stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=timeout)
        logger.info(f"Flask server stopped on {self.host}:{self.port}")
        
    def _run_server(self):
        """Run the Flask server (called in separate thread)."""
        try:
            from werkzeug.serving import make_server
            
            self.server = make_server(self.host, self.port, self.app)
            self.server.timeout = 0.5  # Short timeout to allow checking stop_event
            
            while not self.stop_event.is_set():
                self.server.handle_request()
                
        except Exception as e:
            logger.error(f"Error in Flask server: {e}", exc_info=True)


class WebSocketServer:
    """Manages an async WebSocket server."""
    def __init__(self, handler: Callable, port: int, host: str = "0.0.0.0"):
        self.handler = handler
        self.port = port
        self.host = host
        self.server = None
        self.server_task = None
        self.active_connections: Set[websockets.WebSocketServerProtocol] = set()
        
    async def start(self):
        """Start the WebSocket server."""
        self.server_task = asyncio.create_task(self._run_server())
        logger.info(f"WebSocket server starting on {self.host}:{self.port}")
        
    async def stop(self):
        """Stop the WebSocket server and close all connections."""
        # Close all active connections
        for ws in list(self.active_connections):
            try:
                await ws.close()
            except Exception as e:
                logger.error(f"Error closing WebSocket connection: {e}")
        self.active_connections.clear()
        
        # Cancel the server task
        if self.server_task and not self.server_task.done():
            self.server_task.cancel()
            try:
                await self.server_task
            except asyncio.CancelledError:
                pass
        self.server_task = None
        
    async def _run_server(self):
        """Run the WebSocket server."""
        try:
            async def connection_handler(websocket, path=None):
                """Handle new WebSocket connections."""
                self.active_connections.add(websocket)
                try:
                    await self.handler(websocket, path)
                except websockets.exceptions.ConnectionClosed:
                    logger.info(f"WebSocket connection closed by client {websocket.remote_address}")
                except Exception as e:
                    logger.error(f"Error in WebSocket handler: {e}", exc_info=True)
                finally:
                    self.active_connections.discard(websocket)
            
            self.server = await websockets.serve(connection_handler, self.host, self.port)
            logger.info(f"WebSocket server started on {self.host}:{self.port}")
            
            # Keep the server running until cancelled
            await asyncio.Future()
            
        except asyncio.CancelledError:
            logger.info("WebSocket server task cancelled")
            raise
        except Exception as e:
            logger.error(f"Error starting WebSocket server: {e}", exc_info=True)
        finally:
            if self.server:
                self.server.close()
                await self.server.wait_closed()
                logger.info("WebSocket server closed")
                self.server = None


class ServerManager:
    """
    Manages local servers (Flask, WebSocket) and their ngrok tunnels.
    Provides a unified interface for creating and managing servers that need to be exposed to the internet.
    """
    
    def __init__(self, ngrok_auth_token: Optional[str] = None):
        """
        Initialize the ServerManager.
        
        Args:
            ngrok_auth_token: Optional ngrok authentication token. If not provided,
                            will try to use NGROK_AUTH_TOKEN from environment.
        """
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        
        # Configure ngrok
        auth_token = ngrok_auth_token or os.environ.get("NGROK_AUTH_TOKEN", "")
        if auth_token:
            conf.get_default().auth_token = auth_token
            self.logger.info("ngrok configured with auth token")
        else:
            self.logger.warning("No ngrok auth token provided. Some features may be limited.")
            
        # Track active resources
        self.tunnels: Dict[str, NgrokTunnel] = {}
        self.flask_servers: Dict[str, FlaskServer] = {}
        self.websocket_servers: Dict[str, WebSocketServer] = {}
        self._cleaning_up = False  # Flag to prevent concurrent cleanup
        
    def create_flask_server(self, name: str, app: Flask, port: int, 
                          create_tunnel: bool = True, tunnel_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Create and start a Flask server with optional ngrok tunnel.
        
        Args:
            name: Unique name for this server
            app: Flask application instance
            port: Port to run the server on
            create_tunnel: Whether to create an ngrok tunnel
            tunnel_path: Optional path to append to the tunnel URL
            
        Returns:
            Dict containing server info including public URL if tunnel created
        """
        if name in self.flask_servers:
            raise ValueError(f"Flask server '{name}' already exists")
            
        # Create and start Flask server
        server = FlaskServer(app, port)
        server.start()
        self.flask_servers[name] = server
        
        result = {
            "name": name,
            "port": port,
            "local_url": f"http://localhost:{port}"
        }
        
        # Create ngrok tunnel if requested
        if create_tunnel:
            tunnel = NgrokTunnel(port, "http")
            public_url = tunnel.connect()
            self.tunnels[f"{name}_flask"] = tunnel
            
            if tunnel_path:
                public_url = f"{public_url}{tunnel_path}"
                
            result["public_url"] = public_url
            self.logger.info(f"Flask server '{name}' accessible at: {public_url}")
            
        return result
        
    async def create_websocket_server(self, name: str, handler: Callable, port: int,
                                    create_tunnel: bool = True) -> Dict[str, Any]:
        """
        Create and start a WebSocket server with optional ngrok tunnel.
        
        Args:
            name: Unique name for this server
            handler: Async function to handle WebSocket connections
            port: Port to run the server on
            create_tunnel: Whether to create an ngrok tunnel
            
        Returns:
            Dict containing server info including public URL if tunnel created
        """
        if name in self.websocket_servers:
            raise ValueError(f"WebSocket server '{name}' already exists")
            
        # Create and start WebSocket server
        server = WebSocketServer(handler, port)
        await server.start()
        self.websocket_servers[name] = server
        
        result = {
            "name": name,
            "port": port,
            "local_url": f"ws://localhost:{port}"
        }
        
        # Create ngrok tunnel if requested
        if create_tunnel:
            tunnel = NgrokTunnel(port, "http")
            public_url = tunnel.connect()
            self.tunnels[f"{name}_ws"] = tunnel
            
            # Convert http(s) to ws(s) for WebSocket URL
            if public_url.startswith("https://"):
                ws_url = public_url.replace("https://", "wss://", 1)
            elif public_url.startswith("http://"):
                ws_url = public_url.replace("http://", "ws://", 1)
            else:
                ws_url = public_url
                
            result["public_url"] = ws_url
            self.logger.info(f"WebSocket server '{name}' accessible at: {ws_url}")
            
        return result
        
    def stop_flask_server(self, name: str):
        """Stop a Flask server and its tunnel if exists."""
        if name in self.flask_servers:
            self.flask_servers[name].stop()
            del self.flask_servers[name]
            
        tunnel_name = f"{name}_flask"
        if tunnel_name in self.tunnels:
            self.tunnels[tunnel_name].disconnect()
            del self.tunnels[tunnel_name]
            
    async def stop_websocket_server(self, name: str):
        """Stop a WebSocket server and its tunnel if exists."""
        if name in self.websocket_servers:
            await self.websocket_servers[name].stop()
            del self.websocket_servers[name]
            
        tunnel_name = f"{name}_ws"
        if tunnel_name in self.tunnels:
            self.tunnels[tunnel_name].disconnect()
            del self.tunnels[tunnel_name]
            
    def get_active_connections(self, server_name: str) -> Set[websockets.WebSocketServerProtocol]:
        """Get active WebSocket connections for a specific server."""
        if server_name in self.websocket_servers:
            return self.websocket_servers[server_name].active_connections
        return set()
        
    async def cleanup(self):
        """Clean up all servers and tunnels."""
        # Prevent concurrent cleanup operations
        if self._cleaning_up:
            self.logger.warning("Cleanup already in progress, skipping duplicate call")
            return
            
        self._cleaning_up = True
        
        try:
            # Stop all Flask servers
            for name in list(self.flask_servers.keys()):
                self.stop_flask_server(name)
                
            # Stop all WebSocket servers
            for name in list(self.websocket_servers.keys()):
                await self.stop_websocket_server(name)
                
            # Disconnect any remaining tunnels
            for tunnel in self.tunnels.values():
                tunnel.disconnect()
            self.tunnels.clear()
            
            # Kill all ngrok processes
            try:
                ngrok.kill()
                self.logger.info("All ngrok tunnels terminated")
            except Exception as e:
                self.logger.error(f"Error killing ngrok: {e}")
        finally:
            self._cleaning_up = False 