#!/bin/bash
echo "Starting Phoenix App"
if [ -z "$VIRTUAL_ENV" ]; then
    source .venv/bin/activate
fi
export PYTHONPATH="${PYTHONPATH}:$(pwd)/src"
sudo ./.venv/bin/python3 src/main.py
echo "Phoenix App Exited"
