# RamPipe
Its a hot cache linux daemon, that provides a CLI interface for moving files and directories to RAM, creating overlays, and managing persistanse, in order to speed up set ups with slow disk. (e.g. USB based installs.)

--------

*Note that configuration is located in the rampipe.conf file in /var directory. Explanation to each parameter is inside of the config itself. (comments)*

--------

# Explanation

It provides this set of commands: 

`rampipe pin /path/to/file --move`

`rampipe pin /path/to/dir/ --move`

`rampipe pin /path/to/dir/ --overlay`

`rampipe unpin /path/to/dir`

`rampipe status`  

following this structure: 

`rampipe {action} [arguments]`


****

# What the commands do:

### `rampipe pin /path/to/file --move` does this:

It copies the file to tmpfs and bind mounts the copy in tmpfs over the file on disk, so that operations with it happen on RAM.

The command sequense: 

`cp -r /path/to/file /mnt/ramdisk/`

`mount --bind /mnt/ramdisk/dir /path/to/dir`

### `rampipe pin /path/to/dir/ --move` does this:

It copies the entire dir over to RAM the same way as the command above. 
*(not very practical, but you may still want that if you dont want to figure out wich exact file causes the disk stress.)*

#### command sequense: 

`cp -r /path/to/dir /mnt/ramdisk/`

`mount --bind /mnt/ramdisk/dir /path/to/dir`

### `rampipe pin /path/to/dir/ --overlay` does this:

It creates an overlay over the directory, with the upper dir and working dir going to tmpfs (RAM). 

#### The command sequense (manual way of doing it):

(assuming projekts at /data/projekts is the dir you want to pin)

`mkdir -p /dev/shm/overlay/projects-upper /dev/shm/overlay/projects-work`

`mount -t overlay overlay -o lowerdir=/data/projects,upperdir=/dev/shm/overlay/projects-upper,workdir=/dev/shm/overlay/projects-work /data/projects`


### `rampipe unpin /path/to/dir` does this:

It syncs the data from RAM back to disk, and cleans the RAM up, freeing it. 

#### command sequense: 

`unmount /path/to/thingy`

`rsync -a --delete /mnt/ramdisk/thingy /path/to/thingy` 

*(if thingy is a dir, add / at the end)*

`rm -rf /mnt/ramdisk/thingy`

### `rampipe status` does this: 

It displays the current status ofthe rampipe demon, meaning that it shows what dirs and files are pinned, how much RAM each of them consum and how much total RAM is consumed.

# What the demon does (in the background):

Initialises the tmpfs and overlays as you configurate in the rampipe.conf file. 

It keeps track of what directories and files are currently pinned via a json file, wich itself is pinned by default. 

It syncs the data to disk periodicaly, and even allows batching to not stress the disk. *(its all configurable in the config file, but be carefull, if you batch the data too much, it will result in syncs taking longer then the timer between them.)*

It also ensures that on shutdown (a.k.a. on ExecStop ) it syncs all the data to the disk, ensuring that nothing is lost. 







---------------------------------------------------


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

Then we delete the upper and work dirs. (clean up.)

Example commands: 

`sync`

`mount -o remount,ro /data/projects`

`rsync -a --delete /dev/shm/overlay/projects-upper/ /data/projects/`

`umount /data/projects` (if hit error, try:)

`fuser -km /data/projekts`
`unmount /data/projekt`

(Then do:)

`rm -rf /dev/shm/overlay/projects-{upper,work}` 

(clean up)

# Syncback

Syncback happens through the `rsync -a --remove-source-files /dev/shm/overlay/projects-upper/ /data/projects/` action.

On shutdown (`ExecStop`) perform a full Unpin and syncback of all the files. 