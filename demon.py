# demon.py , the main file of the demon.
# Has the main event loop. 

#!/usr/bin/python3
import os
import subprocess
import time
import math
import argparse
import configparser
import pyinotify
from threading import Lock

# Global state
state = {}  # {path: {"R": float, "last_t": float, "pinned": bool, "loop_dev": str, "lock": Lock}}
CONFIG_FILE = "/etc/rampipe.conf"

def load_config():
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)
    return {
        "pin_writes": float(config.get("thresholds", "pin_writes", fallback=10)),
        "unpin_writes": float(config.get("thresholds", "unpin_writes", fallback=2)),
        "tau": float(config.get("thresholds", "tau", fallback=30)),
        "thinpool_size": config.get("thresholds", "thinpool_size", fallback="2G")
    }

def setup_thinpool(size):
    try:
        subprocess.run(["mount", "-t", "tmpfs", "-o", f"size={size}", "tmpfs", "/mnt/thinpool"], check=True)
        subprocess.run(["truncate", "-s", "1M", "/mnt/thinpool/meta"], check=True)
        subprocess.run(["truncate", "-s", "1M", "/mnt/thinpool/data"], check=True)
        subprocess.run(["dmsetup", "create", "thinpool", "--table",
                        f"0 $(blockdev --getsize64 /mnt/thinpool/data) thin-pool /mnt/thinpool/meta /mnt/thinpool/data 128"], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Failed to setup thinpool: {e}")
        exit(1)

def is_file_open(path):
    for pid_dir in os.listdir("/proc"):
        if not pid_dir.isdigit():
            continue
        fd_dir = f"/proc/{pid_dir}/fd"
        if os.path.exists(fd_dir):
            for fd in os.listdir(fd_dir):
                try:
                    if os.path.realpath(f"{fd_dir}/{fd}") == os.path.realpath(path):
                        return True
                except FileNotFoundError:
                    pass
    return False

def pin_file(path, inode):
    if not os.path.isfile(path) or is_file_open(path):
        return
    try:
        loop_dev = subprocess.check_output(["losetup", "-fP", "--show", path], text=True).strip()
        origin = f"hot-{inode}"
        cow = f"hot-{inode}-cow"
        subprocess.run(["dmsetup", "snapshot", loop_dev, "/dev/mapper/thinpool",
                        f"--originname={origin}", f"--cowname={cow}"], check=True)
        subprocess.run(["mount", "--bind", f"/dev/mapper/{cow}", path], check=True)
        with state[path]["lock"]:
            state[path]["pinned"] = True
            state[path]["loop_dev"] = loop_dev
    except subprocess.CalledProcessError as e:
        print(f"Failed to pin {path}: {e}")

def unpin_file(path, inode, loop_dev):
    if not state.get(path, {}).get("pinned") or is_file_open(path):
        return
    try:
        subprocess.run(["umount", path], check=True)
        subprocess.run(["dmsetup", "merge", f"hot-{inode}-cow"], check=True)
        subprocess.run(["dmsetup", "remove", f"hot-{inode}-cow", f"hot-{inode}"], check=True)
        subprocess.run(["losetup", "-d", loop_dev], check=True)
        with state[path]["lock"]:
            state[path]["pinned"] = False
            state[path]["loop_dev"] = None
    except subprocess.CalledProcessError as e:
        print(f"Failed to unpin {path}: {e}")

def update_ema(path, time_now, is_write):
    state.setdefault(path, {"R": 0.0, "last_t": None, "pinned": False, "loop_dev": None, "lock": Lock()})
    with state[path]["lock"]:
        decay = math.exp(-(time_now - state[path]["last_t"]) / config["tau"]) if state[path]["last_t"] else 1
        state[path]["R"] = decay * state[path]["R"] + (1 if is_write else 0)
        state[path]["last_t"] = time_now
        rate = state[path]["R"] * (60 / config["tau"])
        inode = os.stat(path).st_ino if os.path.exists(path) else 0
        if rate > config["pin_writes"] and not state[path]["pinned"]:
            pin_file(path, inode)
        elif rate < config["unpin_writes"] and state[path]["pinned"]:
            unpin_file(path, inode, state[path]["loop_dev"])

def unpin_all():
    for path, data in list(state.items()):
        if data["pinned"]:
            unpin_file(path, os.stat(path).st_ino, data["loop_dev"])

def main():
    global config
    config = load_config()
    setup_thinpool(config["thinpool_size"])
    wm = pyinotify.WatchManager()
    notifier = pyinotify.Notifier(wm, lambda event: update_ema(event.pathname, time.time(), event.mask & pyinotify.IN_MODIFY))
    wm.add_watch("/", pyinotify.IN_MODIFY)
    notifier.loop()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--unpin-all", action="store_true", help="Unpin all files and exit")
    args = parser.parse_args()
    if args.unpin_all:
        unpin_all()
    else:
        main()