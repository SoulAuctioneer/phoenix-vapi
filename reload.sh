#!/bin/bash

clear
git pull || echo "Git pull failed, continuing..."

# Check if we are running under systemd by checking for the INVOCATION_ID env var.
if [ -n "$INVOCATION_ID" ]; then
    # Running from service, tell run.sh not to stop the service again.
    ./run.sh --service "$@"
else
    # Running manually from the command line.
    ./run.sh "$@"
fi
