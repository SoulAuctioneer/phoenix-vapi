#!/bin/bash

#
# Adds a new WiFi network using NetworkManager (nmcli).
#
# This script checks if a network profile for the given SSID already exists.
# If it doesn't, it creates a new one. This is useful for pre-configuring
# a device to connect to a WiFi network that is not currently in range.
#
# Usage: ./add_wifi.sh <SSID> <password>
#

set -e

if [ "$#" -ne 2 ]; then
    echo "Usage: $0 <SSID> <password>"
    exit 1
fi

SSID="$1"
PASSWORD="$2"

# Check if a connection profile with the given name already exists.
# We use the SSID as the connection name for simplicity.
if nmcli -g NAME connection show | grep -wq "^${SSID}$"; then
    echo "A connection profile named '${SSID}' already exists. Nothing to do."
    exit 0
fi

echo "Adding new WiFi connection profile for '${SSID}'..."

# Add the new connection using nmcli. This requires sudo privileges.
sudo nmcli connection add type wifi con-name "${SSID}" ifname wlan0 ssid "${SSID}" -- wifi-sec.key-mgmt wpa-psk wifi-sec.psk "${PASSWORD}"

if [ $? -eq 0 ]; then
    echo "Successfully added WiFi connection for '${SSID}'."
    echo "The device will automatically connect when the network is in range."
else
    echo "Failed to add WiFi connection for '${SSID}'."
    exit 1
fi

exit 0 