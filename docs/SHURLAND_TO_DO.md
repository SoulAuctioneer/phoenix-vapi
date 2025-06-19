FOR-THE-DAY NOTES:
* Check if Pis wakeword / intent detection works even when offline. Seems to!

MOST IMPORTANT NOW:
* Disable HDMI on all devices, install any new dependencies, including i2c-tools cpufrequtils
* Clean up mic ports on #3.
* Fix respeaker on #5
* Finish upgrading V1 pea
* Change spoken hints for some kinda whoopy bloop peanglish.
* Squealing activity also needs some lights
# Split scavenger hunt into the two paths.
* Tiny Bluetooth LED string light or something
* The service isn't pulling latest
* Have to be able to shut down with command
* Create mother pea activity

* Need another PicoVoice account? ash.eldritch was disabled, but it seems to still be working?
*	LEDs in Bluetooth speaker Pea (El wire?)
* Do what I can here to make upgrading Tom's easier over there.
* Test 4, 5, 6
* Test battery life
* Switch branch to demo

* Make plantasia tune
* ALSO humming thing??? Ask Lucy about that
* Add squeal effects etc to squealing activity
* Update spoken strings for scavenger hunt (see script below)
* Create new Rhino model with only stuff that we need for the event (add stuff from intentservice)
  * Need a bunch of new strings if we're going to do the call/response in lab just from wake words

* Set up Pis for Shurland WiFi: scripts/add_wifi.sh "Shurland-Appliance" "15321532"
* Bug: "go to sleep" inside conversation doesn't shut down LEDs, maybe doesn't stop service properly. Only works via the intent.
*	Amazon returns
* Pay folks


GROW SONG:
Start with a yawn right at the beginning
ALSO giggles during the thing
Add 30-second SFX/giggles intro to plant growy song, for actor to find responses, chop shorter and cute, and add some giggles, add some wooshes, maybe every four beats. Starts a bit random, scattered, but rhythmic, on the beat, combine and become more coherent until we hit the drop. Then it's the regular tune until we get to the break, then finished.
For the music: Add 20 seconds of discovery figuring out how the pea responds, effects on beat, responding a bit harder each time. Lil bit of trumpet, lil bit of beats, mostly giggles and chuckles. Then we do the full initial verse while kids play with the pea, then go into the lull.




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



SOFTWARE:
* Squealing activity:
  - Custom intent to start activity
  - Rotate audio samples: "Where are we?" "Sqeal", "Is this Earth?", "Waaaah", "Are we there yet?"
  - Detect when it's picked up. Says something like "ooh thank mother pea, we're gonna be okay. I'm so exhausted", and goes to sleep.

* Add the snoring back in when it's sleeping.

* Reacting-to-sound-getting-brighter activity:
  - 
* Waking up:
  - Open-ended conversation, kids have some specific questions 

* Botany Room:
  - Create humming
  - Can dock light up when I control it remotely?

* Scavenger hunt activity
  - Oooh I sense something (first time it detects it), oh no we're getting further away, ooh I can feel it, we're getting closer, 
  - Handle multiple in the same area, say I can sense two perhaps.
    - Currently we have a linear flow, so this may not make sense.

Other:
* Add a system shutdown command - intent custom command 9. 
* Try to figure out reduced power draw 
* Try dynamically adjusting volume based on ambient noise levels


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




SCRIPT:

Entrance hall scene: 


PETE The Scientist 
“Welcome to the Pea HQ, now what I'm going to reveal to you is top secret. You’re the first humans we’ve invited here. (pick an adult) Wow you’re really tall for your age! We’ve been communicating with another planet - with the ‘Pea people’ and we’re…” 

*CRASH EXPLOSION SOUND 

(Petal & Pete take all the children outside and surround the crash site hole, everyone needs to be really quiet and Pete jumps down to pick up the peas x 4, Petal takes 2 peas and so does Pete)

MAGIC PEA
(We hear excited pea chatter from the hole as smoke pours out) 
‘We made it/ Wow that was such a long journey/Are we there yet?/ I’m so tired now, maybe we should have a little nap’ 
(sleeping pea sounds)

PETE The Scientist 
“Everyone gather round the edge, be very quiet, we don't want to scare the peas - they look, yes, like baby magic peas. This is incredible. I can't believe it, they’re here on earth. This is a momentous day. I never thought in a hundred thousand million squillion years the magic peas would land on earth! 
Petal you carry two and I'll take these two. Wait, what's this?
 (Pete picks up a tube with something inside)

PETE The Scientist 
(Whilst travelling with the Peas to the Lab)
“I’ve been sending a message into space for some time now, hoping to discover other life and they must have heard it!”

Lab Scene:
Pete gets kids to ask questions to the pea’s. Prompts by whispering questions to them.
PETE The Scientist 
“Welcome to my lab (proud) this is the hub of our headquarters. 
From here I monitor earth and beyond all in our pursuit of peas-ful power of peas in a pod to spread hap-pea-ness.
Ah look perfect I can put the magic pea in this incubator. Let's see if we can wake it up. Can some of you assist me? Great. Can you ask it (whispers to 1st child)"

Child
“Hey Magic Pea, what are you?” 

MAGIC PEA 
“I’m a fluffy friend from space, and like you children we magic peas love to play! 
You all have creative super-powers and we the magic peas are looking to help you create a peas-ful future!
We are seeking to create a future more magical than adults could ever imagine!”

PETE The Scientist 
 “Wow, this sounds un-pea-leivable! Oh I have another question, ‘Hey Magic Pea, where have you come from?’”

CHILD
“Hey Magic Pea, where have you come from?”

MAGIC PEA
“We’ve come all the way through space, through a wormhole, from a galaxy called Pea-topia. (get excited) 

PETE The Scientist 
“Oh wow, (Pete moves over to the blackboard and draws a tunnel) A wormhole is like a giant tunnel in space, it’s a shortcut from one place to another.
That must have taken a lot of energy. Ah, I have another question! (Whispers)Hey Magic pea, How did you power yourself?”
CHILD
“Hey Magic pea, How did you power yourself?” 
MAGIC PEA
“We powered ourselves through the power of positive energy. Ooo its the best, it's created by working together as a team. When we all work together we create a positive energy charge!!!” 
PETE The Scientist 
“That’s fantastic. I wonder if that's something we can do too? 
Now another important question.. (Whispers)Why are you here?”
CHILD
“Why are you here?”


MAGIC PEA
“Grandmother Pea sent us. There’s been a solar storm in our galaxy, and everything has been thrown off-kilter. So we have been sent to learn all about earth and make friends with you, our neighbour. Will you help us?”
PETE The Scientist 
Yes of course we will, we’d love to help you, Wouldn’t we pea pals!
(We hear sounds of peas snoring again)
PETE The Scientist 
“They must be so tired, but we’ve learnt lots from our little furry friends.” 





Transmitter Hunt 

We need to find the following pieces: 

1.⁠ ⁠Junction Box
2.⁠ ⁠⁠transmitter valve
3.⁠ ⁠⁠signal processor
4.⁠ ⁠⁠antenna
5.⁠ ⁠system modulator
6.⁠ ⁠⁠crystal oscillator  

