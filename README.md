# RamPipe
Its a hot cache linux daemon, that dynamicly moves frequently written to directories to RAM via overlays and syncs back once usage becomes low again, in order to speed up set ups with slow disk. (e.g. USB based installs.)

--------

# Architecture

It creates overlays over directories that are written to often, and syncs back on shutdown or on lowering of the write rate.

The overlays are based on the acsess rate (amount of acsesses / timeframe) .

Ovelays are a way to transfer the files writes to RAM efficiently and then leave it there. They are integrated into the kernel and are used to create live systems. 

But what I use them for is: "smart caching"

You see, when someone boots from a USB, the main bottleneck of the system instantly becomes the **disk read and write speeds**. 

The idea is to make the system faster by dynamicly moving file writes to RAM and syncing them back to disk based on how much the files are used. 
(its directory based for now, and doesnt speed up reads for now, but I will add per file and read speed-up funktionality later on.)

****

# Architecture

The architecture is fairly simple *(for now)* :

It consists of these modules: 

1. **Monitoring** : fanotify is used to monitor the file operations. 
2. **Rate saving/calculation** : python is used to calculate use rates per dir.
3. **Overlay management** : Overlay management happens through a threash-hold based system. 
4. **Syncback** : Syncback happens ether on use rate drop below a threshhold, or on shutdown. 

****

## Monitoring

fanotify is used to track the activity per directory.
*(via the python API)*
## Rate saving/calculation

Per directory (path) **EMA** *(Estimated moving average)* of writes .

# Overlay management

The tmpfs area that the upper directories for the overlays are created at is created at the start of the demon, and the amount is configured at rampipe.conf. 

The Overlays are created and synced back dynamicly, meaning that the directories that are being written to a lot (since the current version only counts writes) will have an overlay created for them. 

What counts as "a lot" is defined in the config file rampipe.conf.

*creating overlay over a directory is called pin, syncback and unoverlay is called unpin.*

### Pin algoritm

first we make the directory for the upper layer of overlay, then we make the work directory. (in tmpfs)

Then we mount the overlay. 

Example commands: 

`mkdir -p /dev/shm/overlay/projects-upper /dev/shm/overlay/projects-work`

`mount -t overlay overlay -o lowerdir=/data/projects,upperdir=/dev/shm/overlay/projects-upper,workdir=/dev/shm/overlay/projects-work /data/projects`


### Unpin algoritm

First we pause acsess to that file. 

Then we sync the changes back. (using rsync)

Then we delete the whiteouts. (we need to do that manualy.) 

Then we delete the upper and work dirs. (clean up.)

Example commands: 

`sync`

`mount -o remount,ro /data/projects`

`rsync -a --remove-source-files /dev/shm/overlay/projects-upper/ /data/projects/`

`find /dev/shm/overlay/projects-upper -name '.wh.*' -type c -delete`

`umount /data/projects` (if hit error, try:)

`fuser -km /data/projekts`
`unmount /data/projekt`

(Then do:)

`rm -rf /dev/shm/overlay/projects-{upper,work}` 

(clean up)

# Syncback

Syncback happens through the `rsync -a --remove-source-files /dev/shm/overlay/projects-upper/ /data/projects/` action.

On shutdown (`ExecStop`) perform a full Unpin and syncback of all the files. 