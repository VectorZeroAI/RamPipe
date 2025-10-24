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

*IMPORTATNT NOTE: FIRST CHECK IF THE DIRECTORY HAS SUBMOUNTS, ABORT IF IT DOES, PROSEED IF IT DOESNT.*

It creates an overlay over the directory, with the upper dir and working dir going to tmpfs (RAM). 

#### The command sequense (manual way of doing it):

(assuming projekts at /data/projects is the dir you want to pin)

*CHECK FOR SUBMOUNTS FIRST, IF NONE FOUND, PROSEED.*

`mkdir -p /dev/shm/overlay-projects/upper /dev/shm/overlay-projekts/work`

`mount -t overlay overlay -o lowerdir=/data/projects,upperdir=/dev/shm/overlay-projects/upper,workdir=/dev/shm/overlay-projects/work /mnt/projects`

`mount --bind /mnt/projects /data/projects`


### `rampipe unpin /path/to/dir` does this:

It syncs the data from RAM back to disk, and cleans the RAM up, freeing it. 

There are 2 prosedures, one for the --overlay argument and one for --move argument.

#### command sequense *(for --move)*: 

`umount /path/to/thingy`

`rsync -a --delete /mnt/ramdisk/thingy /path/to/thingy` 

*(if thingy is a dir, add / at the end)*

`rm -rf /mnt/ramdisk/thingy`

#### command sequense *(for --overlay)*:

`mount -o remount,ro /path/to/the/target/dir`

`sync`

`umount /path/to/target/dir`

`umount /mnt/{dirname}`

`overlay merge -f -l /path/to/target/dir -u /dev/shm/overlay-{name}/upper`

`rm -rf /dev/shm/overlay-{dirname}`

### `rampipe status` does this: 

Displays the current status of the RamPipe daemon — listing which directories and files are pinned, how much RAM each consumes, and the total RAM consumed by the daemon.


# What the demon does (in the background):

Initialises the tmpfs and overlays as you configurate in the rampipe.conf file. 

It keeps track of what directories and files are currently pinned via a json file, wich itself is in the tmpfs, to avoid using more disk.

It syncs the data to disk periodicaly, and even allows batching to not stress the disk. *(its all configurable in the config file, but be carefull, if you batch the data too much, it will result in syncs taking longer then the timer between them.)*

It also ensures that on shutdown (a.k.a. on ExecStop ) it syncs all the data to the disk, ensuring that nothing is lost. 


---- 

# Technical notes: 

Comunitaction between CLI *(`rampipe`)* and the demon *(`rampiped`)* happens via UNIX socket at /run/rampipe.sock

The json file is on tmpfs.

It is not synced back, since on everything is unpinned on shutdown. 

This service doesnt allow to persist settings for now. 

The programm consists of 2 executables: rampiped.py and rampipe.py , whereby: 
rampiped.py is the background daemon. 
rampipe.py is the CLI client.


if --move or --overlay is not specified, default to --move. (because --move works regardles of directory or file, and overlay only works on directories.)



# Requirements:

overlayfs-tools
rsync
coreutils
utils-linux