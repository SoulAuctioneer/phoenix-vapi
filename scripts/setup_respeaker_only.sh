#!/bin/bash

# Script to configure Raspberry Pi to use only Respeaker audio
# Run with: sudo bash scripts/setup_respeaker_only.sh

echo "=== Configuring Raspberry Pi for Respeaker-only audio ==="

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
  echo "Please run as root (use sudo)"
  exit 1
fi

# Backup existing configurations
echo "Creating backups..."
[ -f /boot/config.txt ] && cp /boot/config.txt /boot/config.txt.backup
[ -f /boot/firmware/config.txt ] && cp /boot/firmware/config.txt /boot/firmware/config.txt.backup
[ -f /etc/asound.conf ] && cp /etc/asound.conf /etc/asound.conf.backup

# Determine config.txt location
if [ -f /boot/firmware/config.txt ]; then
    CONFIG_FILE="/boot/firmware/config.txt"
else
    CONFIG_FILE="/boot/config.txt"
fi

# Step 1: Disable HDMI audio in config.txt
echo "Disabling HDMI audio..."
if ! grep -q "dtoverlay=vc4-kms-v3d,nohdmi0,nohdmi1" "$CONFIG_FILE"; then
    echo "" >> "$CONFIG_FILE"
    echo "# Disable HDMI audio" >> "$CONFIG_FILE"
    echo "dtoverlay=vc4-kms-v3d,nohdmi0,nohdmi1" >> "$CONFIG_FILE"
fi

# Also ensure onboard audio is disabled
if ! grep -q "dtparam=audio=off" "$CONFIG_FILE"; then
    echo "dtparam=audio=off" >> "$CONFIG_FILE"
fi

# Step 2: Blacklist onboard audio module
echo "Blacklisting onboard audio..."
echo "# Disable onboard audio" > /etc/modprobe.d/alsa-blacklist.conf
echo "blacklist snd_bcm2835" >> /etc/modprobe.d/alsa-blacklist.conf

# Step 3: Create ALSA configuration
echo "Creating ALSA configuration..."
cat > /etc/asound.conf << 'EOF'
# Set Respeaker as the only and default device
pcm.!default {
    type asym
    playback.pcm "respeaker"
    capture.pcm "respeaker"
}

pcm.respeaker {
    type plug
    slave.pcm "hw:0,0"
}

ctl.!default {
    type hw
    card 0
}
EOF

# Step 4: Configure module loading order
echo "Configuring module loading order..."
cat > /etc/modprobe.d/alsa-base.conf << 'EOF'
# Force USB audio to be card 0
options snd-usb-audio index=0
EOF

# Step 5: Disable PulseAudio if it exists
if systemctl is-enabled pulseaudio &> /dev/null; then
    echo "Disabling PulseAudio..."
    systemctl disable pulseaudio
    systemctl stop pulseaudio
    systemctl mask pulseaudio
fi

# Step 6: Clean up ALSA state
echo "Cleaning up ALSA state..."
rm -f /var/lib/alsa/asound.state

# Step 7: Remove modules if currently loaded
if lsmod | grep -q snd_bcm2835; then
    echo "Removing snd_bcm2835 module..."
    rmmod snd_bcm2835 2>/dev/null || true
fi

if lsmod | grep -q vc4; then
    echo "Removing vc4 module..."
    rmmod vc4 2>/dev/null || true
fi

echo ""
echo "=== Configuration complete! ==="
echo ""
echo "Please reboot your Raspberry Pi for changes to take effect:"
echo "  sudo reboot"
echo ""
echo "After reboot, verify with:"
echo "  aplay -l"
echo ""
echo "You should only see your Respeaker device listed." 