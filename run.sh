#!/bin/bash

SERVICE_NAME="phoenix-vapi"

# Check if systemctl is available and the service is running
if command -v systemctl &> /dev/null && systemctl is-active --quiet "$SERVICE_NAME"; then
    echo "Phoenix VAPI service is running. Stopping it first..."
    sudo systemctl stop "$SERVICE_NAME"
    echo "Service stopped."
fi

echo "Starting Phoenix App"
if [ -z "$VIRTUAL_ENV" ]; then
    source .venv/bin/activate
fi
export PYTHONPATH="${PYTHONPATH}:$(pwd)/src"
sudo ./.venv/bin/python3 src/main.py "$@"
echo "Phoenix App Exited"
