# RamPipe
Its a hot cache linux daemon, that dynamicly moves frequently used files to RAM and back to disk.

--------

# Architecture

This is my demon that creates loop-back-devices and file-overlay for *hot* files. 

The overlays are based on the acsess rate (amount of acsesses / timeframe) .

Ovelays are a way to transfer the files writes to RAM efficiently and then leave it there. They are integrated into the [[kernel]] and are used to create live systems. 

But what I use them for is: "smart caching"

You see, when someone boots from a USB, the main bottleneck of the system instantly becomes the **disk read and write speeds**. 

The idea is to make the system faster by dynamicly moving files to RAM and syncing them back to disk based on how much the file is used. 

****

# Architecture

The architecture is fairly simple *(for now)* :

It consists of these modules: 

1. **Monitoring** : fanotify is used to monitor the file operations. 
2. **Rate saving/calculation** : python is used to calculate use rates per file. 
3. **Overlay management** : Overlay management happens through a threash-hold based system. 
4. **Syncback** : Syncback happens ether on use rate drop below a threshhold, or on shutdown. 

****

## Monitoring

fanotify is used to track the activity per file.
*(via the python API)*
## Rate saving/calculation

Per file (path) **EMA** *(Estimated moving average)* of writes .

# Overlay management

First, we create the thin pool used by the Cache.
( mount -t tmpfs -o size=1G tmpfs /mnt/thinpool )

Then we just pin the files taht are used above a sertain threshhold, and unpin the files wich are used below a different threashhold.

*Exact threshhold needs testing on the user mashine and is configurated by the user*

There is no "hard-maximum" because I dont think there is a need for one. Unless your short on RAM or on loop devices, for whatever reason. 

I wont include it for now, because Im not short on RAM.

### Pin algoritm

The Pin algoritm is as following: 

Create a loop device. (`losetup`)

Create a snapshot for the loop device. (`dmsetup snapshot /dev/loopX /dev/mapper/thinpool --originname=X --cowname=Y`)

Bind mount the loop device to the file. (`mount --bind /dev/mapper/X-cow /path/to/the/file`)

### Unpin algoritm

Unmount the loop device.  `unmount /path`

Sync back. `dmsetup merge`

Clean up. (delete the loop device if clean up doesnt do that.) `losetup -d`

# Syncback

Syncback happens through a `dmsetup merge` action.

On shutdown (`ExecStop`) perform a full Unpin and syncback of all the files. 