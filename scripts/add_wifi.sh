#!/bin/bash

#
# Adds a new WiFi network, detecting whether to use NetworkManager (nmcli)
# or wpa_supplicant.
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

# Check if NetworkManager is running and use nmcli if it is
if command -v nmcli &>/dev/null && nmcli general status &>/dev/null; then
    echo "NetworkManager is running. Using nmcli."
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

    echo
    echo "Current configured networks (via nmcli):"
    nmcli connection show

# Fallback to wpa_supplicant if NetworkManager is not running
elif [ -f /etc/wpa_supplicant/wpa_supplicant.conf ]; then
    echo "NetworkManager not available. Falling back to wpa_supplicant."

    if sudo grep -q "ssid=\"${SSID}\"" /etc/wpa_supplicant/wpa_supplicant.conf; then
        echo "A network profile for '${SSID}' already exists in wpa_supplicant.conf. Nothing to do."
        exit 0
    fi
    
    echo "Adding new WiFi connection for '${SSID}' to /etc/wpa_supplicant/wpa_supplicant.conf..."

    # Ensure there is a newline at the end of the file before appending
    echo "" | sudo tee -a /etc/wpa_supplicant/wpa_supplicant.conf > /dev/null
    
    # Generate network block and append to wpa_supplicant.conf
    wpa_passphrase "${SSID}" "${PASSWORD}" | sudo tee -a /etc/wpa_supplicant/wpa_supplicant.conf > /dev/null

    if [ $? -eq 0 ]; then
        echo "Successfully added WiFi configuration for '${SSID}'."
        echo "You may need to reconfigure the interface or reboot for the changes to take effect."
        echo "Try: sudo wpa_cli -i wlan0 reconfigure"
    else
        echo "Failed to add WiFi connection for '${SSID}'."
        exit 1
    fi
    
    echo
    echo "Current configured networks (/etc/wpa_supplicant/wpa_supplicant.conf):"
    sudo cat /etc/wpa_supplicant/wpa_supplicant.conf

else
    echo "Error: Neither NetworkManager (nmcli) nor /etc/wpa_supplicant/wpa_supplicant.conf were found."
    echo "This script supports only these two methods for WiFi configuration."
    exit 1
fi

exit 0 