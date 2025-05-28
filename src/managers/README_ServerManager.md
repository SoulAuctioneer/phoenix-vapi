# ServerManager

The `ServerManager` class provides a unified interface for creating and managing local servers (Flask HTTP and WebSocket) with optional ngrok tunnels for public internet access.

## Features

- **Flask Server Management**: Create and manage Flask HTTP servers running in separate threads
- **WebSocket Server Management**: Create and manage async WebSocket servers
- **ngrok Integration**: Automatically create ngrok tunnels to expose local servers to the internet
- **Resource Tracking**: Keeps track of all active servers and tunnels for easy cleanup
- **Error Handling**: Robust error handling for server and tunnel creation/destruction

## Installation

The ServerManager requires the following dependencies:
- `flask`: For HTTP server functionality
- `websockets`: For WebSocket server functionality
- `pyngrok`: For ngrok tunnel management

## Usage

### Basic Example

```python
from managers.server_manager import ServerManager
from flask import Flask

# Initialize ServerManager
server_manager = ServerManager(ngrok_auth_token="your_token")  # Optional token

# Create a Flask app
app = Flask(__name__)

@app.route("/hello")
def hello():
    return "Hello, World!"

# Start server with ngrok tunnel
server_info = server_manager.create_flask_server(
    name="my_api",
    app=app,
    port=5000,
    create_tunnel=True,
    tunnel_path="/api"  # Optional path to append to tunnel URL
)

print(f"Server accessible at: {server_info['public_url']}")
```

### WebSocket Server Example

```python
async def handle_connection(websocket, path):
    """Handle incoming WebSocket connections."""
    async for message in websocket:
        # Process message
        await websocket.send(f"Echo: {message}")

# Create WebSocket server
ws_info = await server_manager.create_websocket_server(
    name="chat_server",
    handler=handle_connection,
    port=8080,
    create_tunnel=True
)

print(f"WebSocket server at: {ws_info['public_url']}")
```

### Local-Only Server

```python
# Create server without ngrok tunnel
local_info = server_manager.create_flask_server(
    name="internal_api",
    app=app,
    port=8000,
    create_tunnel=False  # No public access
)
```

## API Reference

### ServerManager

#### `__init__(ngrok_auth_token: Optional[str] = None)`
Initialize the ServerManager with optional ngrok authentication token.

#### `create_flask_server(name: str, app: Flask, port: int, create_tunnel: bool = True, tunnel_path: Optional[str] = None) -> Dict[str, Any]`
Create and start a Flask HTTP server.

**Parameters:**
- `name`: Unique identifier for the server
- `app`: Flask application instance
- `port`: Port number to run the server on
- `create_tunnel`: Whether to create an ngrok tunnel
- `tunnel_path`: Optional path to append to the tunnel URL

**Returns:** Dictionary with server information including URLs

#### `async create_websocket_server(name: str, handler: Callable, port: int, create_tunnel: bool = True) -> Dict[str, Any]`
Create and start a WebSocket server.

**Parameters:**
- `name`: Unique identifier for the server
- `handler`: Async function to handle WebSocket connections
- `port`: Port number to run the server on
- `create_tunnel`: Whether to create an ngrok tunnel

**Returns:** Dictionary with server information including URLs

#### `stop_flask_server(name: str)`
Stop a Flask server and its associated tunnel.

#### `async stop_websocket_server(name: str)`
Stop a WebSocket server and its associated tunnel.

#### `get_active_connections(server_name: str) -> Set[websockets.WebSocketServerProtocol]`
Get all active WebSocket connections for a specific server.

#### `async cleanup()`
Clean up all servers and tunnels. Should be called when shutting down.

## Integration with CallActivity

The `CallActivity` service uses `ServerManager` to handle its Flask and WebSocket servers:

```python
# In CallActivity.__init__
self.server_manager = ServerManager(ngrok_auth_token=NGROK_AUTH_TOKEN)

# In CallActivity.start()
# Create Flask server for TwiML
flask_info = self.server_manager.create_flask_server(
    name="twilio_twiml",
    app=self.flask_app,
    port=FLASK_PORT,
    create_tunnel=True,
    tunnel_path="/twiml"
)

# Create WebSocket server for media streaming
ws_info = await self.server_manager.create_websocket_server(
    name="twilio_media",
    handler=self._handle_websocket_connection,
    port=WEBSOCKET_PORT,
    create_tunnel=True
)

# In CallActivity.stop()
await self.server_manager.cleanup()
```

## Best Practices

1. **Unique Names**: Always use unique names for servers to avoid conflicts
2. **Cleanup**: Always call `cleanup()` when shutting down to properly close all resources
3. **Error Handling**: Wrap server creation in try-except blocks to handle potential failures
4. **Port Management**: Ensure ports are available before creating servers
5. **ngrok Limits**: Be aware of ngrok's rate limits and connection limits on free tier

## Common Use Cases

1. **Webhook Endpoints**: Create temporary HTTP endpoints for receiving webhooks
2. **Real-time Communication**: WebSocket servers for chat, notifications, or streaming
3. **API Testing**: Expose local development APIs for external testing
4. **Service Integration**: Bridge local services with cloud services (like Twilio)
5. **Debugging**: Expose local services for remote debugging or monitoring 