# Raspberry Pi Audio Configuration for Respeaker Only

This guide will help you disable all audio interfaces except for the Respeaker sound card to eliminate ALSA errors and speed up PyAudio initialization.

## Step 1: Disable HDMI Audio

Edit your boot configuration file:

```bash
sudo nano /boot/config.txt
# On newer systems, it might be:
# sudo nano /boot/firmware/config.txt
```

Add these lines at the end of the file:

```
# Disable both HDMI audio outputs
dtoverlay=vc4-kms-v3d,nohdmi0,nohdmi1
# OR if you're not using the vc4 graphics driver:
# dtparam=audio=off
```

## Step 2: Disable Onboard Audio (BCM2835)

Create or edit the blacklist file:

```bash
sudo nano /etc/modprobe.d/alsa-blacklist.conf
```

Add these lines:

```
# Disable onboard audio
blacklist snd_bcm2835
```

## Step 3: Create Custom ALSA Configuration

Create a system-wide ALSA configuration that only uses the Respeaker:

```bash
sudo nano /etc/asound.conf
```

Add this configuration:

```
# Set Respeaker as the only and default device
pcm.!default {
    type asym
    playback.pcm "respeaker"
    capture.pcm "respeaker"
}

pcm.respeaker {
    type plug
    slave.pcm "hw:1,0"
}

ctl.!default {
    type hw
    card 1
}
```

## Step 4: Disable PulseAudio (Optional)

Since you're getting PulseAudio connection refused errors and don't seem to need it:

```bash
# Disable PulseAudio
sudo systemctl disable pulseaudio
sudo systemctl stop pulseaudio

# Or completely mask it
sudo systemctl mask pulseaudio
```

## Step 5: Fix Module Loading Order

Create a modules configuration file to ensure proper loading:

```bash
sudo nano /etc/modprobe.d/alsa-base.conf
```

Add:

```
# Prevent USB audio from being loaded as first soundcard
options snd-usb-audio index=0
```

## Step 6: Clean Up ALSA State

Remove any existing ALSA state files that might cause issues:

```bash
sudo rm -f /var/lib/alsa/asound.state
```

## Step 7: Reboot

```bash
sudo reboot
```

## After Reboot - Verification

Check that only the Respeaker is available:

```bash
# List sound cards
aplay -l

# You should only see:
# **** List of PLAYBACK Hardware Devices ****
# card 0: Array [ReSpeaker 4 Mic Array (UAC1.0)], device 0: USB Audio [USB Audio]

# Test audio
speaker-test -c 2 -t wav
```

## Python Code Optimization

In your Python code, you can also specify the device directly to avoid enumeration:

```python
import pyaudio

# Initialize PyAudio with specific device
p = pyaudio.PyAudio()

# Find Respeaker device index (do this once and hardcode if needed)
respeaker_index = None
for i in range(p.get_device_count()):
    info = p.get_device_info_by_index(i)
    if 'ReSpeaker' in info['name']:
        respeaker_index = i
        break

# Use specific device for faster initialization
if respeaker_index is not None:
    stream = p.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=16000,
        input=True,
        input_device_index=respeaker_index,
        frames_per_buffer=1024
    )
```

## Troubleshooting

If you still see errors after reboot:

1. Check which modules are loaded:
   ```bash
   lsmod | grep snd
   ```

2. Manually remove unwanted modules:
   ```bash
   sudo rmmod snd_bcm2835
   sudo rmmod vc4
   ```

3. Check ALSA configuration:
   ```bash
   cat /proc/asound/cards
   ```

4. For persistent USB device naming, create a udev rule:
   ```bash
   sudo nano /etc/udev/rules.d/85-alsa-usb.rules
   ```
   
   Add:
   ```
   SUBSYSTEM=="sound", ATTRS{idVendor}=="2886", ATTRS{idProduct}=="0018", ATTR{id}="Respeaker"
   ```
   (Replace vendor and product IDs with your Respeaker's actual values from `lsusb`)

This configuration should eliminate all the ALSA errors and significantly speed up PyAudio initialization by preventing it from trying to enumerate non-existent audio devices. 