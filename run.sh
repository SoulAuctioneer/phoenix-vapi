#!/bin/bash

RUN_FROM_SERVICE=0
if [ "$1" == "--service" ]; then
    RUN_FROM_SERVICE=1
    shift # remove --service from the arguments
fi

SERVICE_NAME="phoenix-vapi"

# When run manually, stop the service first
if [ "$RUN_FROM_SERVICE" -eq 0 ]; then
    if command -v systemctl &> /dev/null && systemctl is-active --quiet "$SERVICE_NAME"; then
        echo "Phoenix VAPI service is running. Stopping it first..."
        sudo systemctl stop "$SERVICE_NAME"
        echo "Service stopped."
    fi
fi

echo "Starting Phoenix App"
if [ -z "$VIRTUAL_ENV" ]; then
    source .venv/bin/activate
fi
export PYTHONPATH="${PYTHONPATH}:$(pwd)/src"

if [ "$RUN_FROM_SERVICE" -eq 1 ]; then
    # Run as service user, no sudo
    ./.venv/bin/python3 src/main.py "$@"
else
    # Run manually, with sudo for hardware access
    sudo ./.venv/bin/python3 src/main.py "$@"
fi

echo "Phoenix App Exited"
