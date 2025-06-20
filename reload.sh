#!/bin/bash

clear

# Determine the owner of the current directory in a cross-platform way.
if [[ "$(uname)" == "Darwin" ]]; then
    OWNER=$(stat -f '%Su' .)
else
    OWNER=$(stat -c '%U' .)
fi

# Run git pull as the owner of the directory to satisfy git's safe directory check.
echo "Fetching latest from git as user $OWNER..."
sudo -H -u "$OWNER" git reset --hard HEAD
sudo -H -u "$OWNER" git pull || echo "Git pull failed, continuing..."

# Check if we are running under systemd by checking for the INVOCATION_ID env var.
if [ -n "$INVOCATION_ID" ]; then
    # Running from service, tell run.sh not to stop the service again.
    ./run.sh --service "$@"
else
    # Running manually from the command line.
    ./run.sh "$@"
fi
