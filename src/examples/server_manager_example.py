"""
Example demonstrating how to use ServerManager for various server needs.
This shows how the abstracted server management can be reused across the application.
"""
import asyncio
import json
from flask import Flask, jsonify, request
from managers.server_manager import ServerManager


async def example_websocket_handler(websocket, path):
    """Example WebSocket handler that echoes messages back."""
    print(f"New WebSocket connection from {websocket.remote_address}")
    try:
        async for message in websocket:
            # Echo the message back
            response = {
                "type": "echo",
                "original": message,
                "timestamp": asyncio.get_event_loop().time()
            }
            await websocket.send(json.dumps(response))
    except Exception as e:
        print(f"WebSocket error: {e}")


async def main():
    """Demonstrate various uses of ServerManager."""
    
    # Initialize ServerManager
    server_manager = ServerManager()
    
    # Example 1: Create a simple REST API server
    api_app = Flask("example_api")
    
    @api_app.route("/status")
    def status():
        return jsonify({"status": "running", "service": "example"})
    
    @api_app.route("/webhook", methods=["POST"])
    def webhook():
        data = request.get_json()
        print(f"Received webhook: {data}")
        return jsonify({"received": True})
    
    # Start the API server with ngrok tunnel
    api_info = server_manager.create_flask_server(
        name="example_api",
        app=api_app,
        port=8080,
        create_tunnel=True
    )
    print(f"API Server started:")
    print(f"  Local: {api_info['local_url']}")
    print(f"  Public: {api_info['public_url']}")
    
    # Example 2: Create a WebSocket server for real-time communication
    ws_info = await server_manager.create_websocket_server(
        name="realtime_channel",
        handler=example_websocket_handler,
        port=8081,
        create_tunnel=True
    )
    print(f"\nWebSocket Server started:")
    print(f"  Local: {ws_info['local_url']}")
    print(f"  Public: {ws_info['public_url']}")
    
    # Example 3: Create a local-only server (no ngrok tunnel)
    local_app = Flask("local_service")
    
    @local_app.route("/internal")
    def internal():
        return "This is only accessible locally"
    
    local_info = server_manager.create_flask_server(
        name="local_service",
        app=local_app,
        port=8082,
        create_tunnel=False  # No public access needed
    )
    print(f"\nLocal-only Server started:")
    print(f"  Local: {local_info['local_url']}")
    
    # Let servers run for a while
    print("\nServers are running. Press Ctrl+C to stop...")
    try:
        await asyncio.sleep(300)  # Run for 5 minutes
    except KeyboardInterrupt:
        print("\nShutting down...")
    
    # Clean up all servers
    await server_manager.cleanup()
    print("All servers stopped.")


if __name__ == "__main__":
    asyncio.run(main()) 