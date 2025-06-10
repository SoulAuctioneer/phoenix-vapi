#!/bin/bash

# Phoenix VAPI Auto-reload Service Installer
# This script creates and installs a systemd service to run reload.sh on boot

set -e  # Exit on any error

# Configuration
SERVICE_NAME="phoenix-vapi"
SERVICE_DESCRIPTION="Phoenix VAPI Auto-reload Service"
PROJECT_DIR="$HOME/phoenix-vapi"
SCRIPT_PATH="$PROJECT_DIR/reload.sh"
SERVICE_FILE="/etc/systemd/system/$SERVICE_NAME.service"

echo "=== Phoenix VAPI Service Installer ==="
echo "This will create a systemd service to run reload.sh on boot"
echo ""

# Check if we're running as root for systemd operations
if [[ $EUID -eq 0 ]]; then
    echo "Error: This script should not be run as root."
    echo "Please run as a regular user. The script will use sudo when needed."
    exit 1
fi

# Verify the reload.sh script exists
if [[ ! -f "$SCRIPT_PATH" ]]; then
    echo "Error: reload.sh not found at $SCRIPT_PATH"
    echo "Please ensure you're running this from the phoenix-vapi directory"
    echo "and that reload.sh exists in the project root."
    exit 1
fi

# Make reload.sh executable
echo "Making reload.sh executable..."
chmod +x "$SCRIPT_PATH"

# Create the systemd service file content
SERVICE_CONTENT="[Unit]
Description=$SERVICE_DESCRIPTION
After=network.target
Wants=network.target

[Service]
Type=simple
User=$USER
Group=$USER
WorkingDirectory=$PROJECT_DIR
ExecStart=$SCRIPT_PATH
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

# Environment variables
Environment=HOME=$HOME
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

[Install]
WantedBy=multi-user.target"

# Create the service file
echo "Creating systemd service file..."
echo "$SERVICE_CONTENT" | sudo tee "$SERVICE_FILE" > /dev/null

# Set proper permissions
sudo chmod 644 "$SERVICE_FILE"

# Reload systemd to recognize the new service
echo "Reloading systemd daemon..."
sudo systemctl daemon-reload

# Enable the service (but don't start it yet)
echo "Enabling $SERVICE_NAME service..."
sudo systemctl enable "$SERVICE_NAME.service"

echo ""
echo "=== Installation Complete ==="
echo "Service '$SERVICE_NAME' has been installed and enabled."
echo ""
echo "Available commands:"
echo "  Start service:     sudo systemctl start $SERVICE_NAME"
echo "  Stop service:      sudo systemctl stop $SERVICE_NAME"
echo "  Service status:    sudo systemctl status $SERVICE_NAME"
echo "  View logs:         sudo journalctl -u $SERVICE_NAME -f"
echo "  Disable service:   sudo systemctl disable $SERVICE_NAME"
echo ""
echo "The service will automatically start on next boot."
echo "To start it now, run: sudo systemctl start $SERVICE_NAME" 
echo ""
echo "To stop the service, run scripts/stop_service.sh"
echo ""
