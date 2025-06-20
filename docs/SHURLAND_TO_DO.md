
BEFORE REHEARSALS:
* Increase power on other 3 beacons.
* Create new Rhino model with only stuff that we need for the event.
* Re-run TTS caching.
* Make plantasia tune.
* Clean up mic ports on #3. Check others.
* Verify we got cache hits for everything scavenger hunty and cratery.
* Do a full run-through.

AFTER REHEARSALS:
* Ask Sean for some shade over the crater.
* Conversation first part of audio is being cut off, looks like amp is disabled initially for a moment. Started happening after the attempted pitch refactor.
* Upgrade Tom's pea (software instructions at bottom).
* Make conversation voice sound childish. Maybe just do call/response from wakword+intent only.
* Add squeal effects etc to squealing activity.
* Lights in botany dock
* Try dynamically adjusting volume based on ambient noise levels
* Fix respeaker on #5:
  * NOTE: The thin wires on #0's LEDs might be causing the high power draw. If one of the others fails, could scavenge it.

LATER:
* Need another PicoVoice account? ash.eldritch was disabled, but it seems to still be working?
* Bug: "go to sleep" inside conversation doesn't shut down LEDs, maybe doesn't stop service properly. Only works via the intent.
*	Amazon returns
* Pay folks


GROW SONG:
Start with a yawn right at the beginning
ALSO giggles during the thing
Add 30-second SFX/giggles intro to plant growy song, for actor to find responses, chop shorter and cute, and add some giggles, add some wooshes, maybe every four beats. Starts a bit random, scattered, but rhythmic, on the beat, combine and become more coherent until we hit the drop. Then it's the regular tune until we get to the break, then finished.
For the music: Add 20 seconds of discovery figuring out how the pea responds, effects on beat, responding a bit harder each time. Lil bit of trumpet, lil bit of beats, mostly giggles and chuckles. Then we do the full initial verse while kids play with the pea, then go into the lull.


9.15-10.15 technical runthrough.

Expenses:
- Nad work hours
- Purchases
- Per diem
- Flight May

WORK HOURS:
NAD:
* 6th 1.45 - 6:15 4.5 hrs PAID $225
* 7th: 3.00 - 8.30 5.5 hrs PAID $275
* 8th: 3.00 - 4.45 and 5.15 - 6pm 2.5 hrs PAID $150
* 9th: 3.30 - 8.00 less 30 break 4 hours PAID $200
* 10th: 4.00 - 7.00 3 hours PAID $150
* 11th: 3.15 - 9.00 5.45 PAID $288
* 13th: 4.45 - 9.45 5 hrs PAID $250
* 14th: 3.30 - 8.00 4.5 hrs PAID $225
* 15th: 4.15 - 6.00  1.75 hrs PAID $ $87.50
* 16th: 12.30 - 5.30 5 hrs PAID $250
MEGAN:
* 10th: 2.30 - 4.10 1:40 hrs TO PAY $50
ROHIT:
* 10th: 2.00 - 7.00 5 hours TO PAY $250
* 11th: 2.00 -  6.00 4 hours TO PAY $200
* 13th: 8.30 - 1.18am
CAROLINA:
* 11th: 3.30 - 8.30 5 hours PAID @ $30 = 
* 12th: 2.30 - 7.00 4.5 hours PAID @ $30 = 
* 13th: 3.30 - 6.00 2.5 hours PAID @ $30 = 
* 15th: 1.30 - 3.00 1.5 hours PAID @ $30 = 
TOTAL $405 + $12 CC fee = $417

EVENT SLIDES:
https://docs.google.com/presentation/d/10CB5ldhfgQDrg7EVcocxdp6LFyqzWWMMBgkNeTOzm0Q/edit?slide=id.g35a9257e399_0_5#slide=id.g35a9257e399_0_5




Squealing peas in crater (2 fake peas that just glow, and 1 real).
Take them to the lab.
https://docs.google.com/presentation/d/10CB5ldhfgQDrg7EVcocxdp6LFyqzWWMMBgkNeTOzm0Q/edit?slide=id.g359602834c8_1_103#slide=id.g359602834c8_1_103 
Put it in dock in lab (or see below, there’s already a pea in there)
It’s asleep. At some point actor will say “magic pea, can you hear us?”, triggering the waking-up-energy activity.  Pea will get brighter with more and more sound, until it’s fully energized and wakes up, starting a conversation with some scripted words. 
PEA #1 - (conversational pea) - In the lab room. This Pea is lying in the dock (so it can keep charged). Its relaxing after its long journey from space. We ask everyone to be very quiet. And the pea says a couple of scripted things. We then find a way to turn off the pea so the actor can continue speaking with the people in the room.
Magic pea needs is told to go to sleep, then it stops chatting. 
Then dance with bluetooth pea in botany lab. First, in dock. Responds to humming by humming back. Then tune when dancing. 
Then scavenger hunt, groups of 10.
Then finale: Mother pea voice recording says “Hey magic peas, don’t be afraid” or something, that’s the trigger phrase for an activity where they respond: “Hello mummy!” and they light up. (ensure no need for internet).





Update Tom's Pi:
git pull
sudo apt-get update && sudo apt-get install -y build-essential gfortran libatlas-base-dev cpufrequtils rubberband-cli
source .venv/bin/activate
pip install -r requirements.txt

if [ -f "/boot/firmware/config.txt" ]; then
    CONFIG_PATH="/boot/firmware/config.txt"
else
    CONFIG_PATH="/boot/config.txt"
fi
cat $CONFIG_PATH
sudo sh -c "echo '' >> $CONFIG_PATH"
sudo sh -c "echo '# Disable HDMI output for power savings' >> $CONFIG_PATH"
sudo sh -c "echo 'hdmi_blanking=2' >> $CONFIG_PATH"
echo $CONFIG_PATH
