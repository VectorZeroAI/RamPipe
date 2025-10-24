#!/usr/bin/env python3
"""
demon.py, the demon for the rampipe projekt. 
Actually should be named rampiped, but I dont really know how to rename files. So for now, this will be like this. I will fix this as soon as I understand how to rename files on github.


The main loop. Uses UNIX sockets to comunicate with the CLI. 
"""

import os
import sys
import json
import time
import signal
import subprocess
import threading
import socket
import shutil
from pathlib import Path

class RamPipeDaemon:
    def __init__(self, config_path="/etc/rampipe.conf"):
        self.config = self.load_config(config_path)
        self.state_file = Path(self.config.get('state_file', '/mnt/rampipe/state.json'))
        self.pinned_items = {}
        self.lock = threading.Lock()
        self.running = True
        self.socket_path = "/run/rampipe.sock"
        self.setup_tmpfs()
        self.load_state()
        
        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

    def load_config(self, config_path):
        """Load configuration from file with comments"""
        config = {
            'ramdisk_path': '/mnt/rampipe',
            'tmpfs_size': '1G',
            'sync_interval': 300,
            'overlay_base': '/dev/shm/overlays',
            'state_file': '/mnt/rampipe/state.json'
        }
        
        try:
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            if '=' in line:
                                key, value = line.split('=', 1)
                                key = key.strip()
                                value = value.strip()
                                # Convert numeric values
                                if value.isdigit():
                                    value = int(value)
                                elif value.replace('.', '').isdigit():
                                    value = float(value)
                                config[key] = value
        except Exception as e:
            print(f"Warning: Could not load config: {e}", file=sys.stderr)
            
        return config

    def setup_tmpfs(self):
        """Setup tmpfs mount for ramdisk"""
        ramdisk_path = self.config.get('ramdisk_path', '/mnt/rampipe')
        tmpfs_size = self.config.get('tmpfs_size', '1G')
        Path(ramdisk_path).mkdir(parents=True, exist_ok=True)
        
        # Check if already mounted
        result = subprocess.run(['mountpoint', '-q', ramdisk_path])
        if result.returncode != 0:
            try:
                subprocess.run(['mount', '-t', 'tmpfs', '-o', f'size={tmpfs_size}', 'tmpfs', ramdisk_path], 
                             check=True, capture_output=True)
                print(f"Mounted tmpfs at {ramdisk_path}")
            except subprocess.CalledProcessError as e:
                print(f"Error mounting tmpfs: {e}", file=sys.stderr)
                raise

    def load_state(self):
        """Load state from JSON file"""
        with self.lock:
            if self.state_file.exists():
                try:
                    with open(self.state_file, 'r') as f:
                        self.pinned_items = json.load(f)
                except Exception as e:
                    print(f"Warning: Could not load state: {e}", file=sys.stderr)
                    self.pinned_items = {}

    def save_state(self):
        """Save state to JSON file"""
        with self.lock:
            try:
                with open(self.state_file, 'w') as f:
                    json.dump(self.pinned_items, f, indent=2)
            except Exception as e:
                print(f"Error saving state: {e}", file=sys.stderr)

    def pin_move(self, path):
        """Pin file/directory using move method"""
        path = Path(path).resolve()
        if not path.exists():
            raise Exception(f"Path does not exist: {path}")
            
        ramdisk_path = Path(self.config['ramdisk_path'])
        temp_path = ramdisk_path / path.relative_to('/')
        temp_path.parent.mkdir(parents=True, exist_ok=True)

        # Copy to tmpfs
        if path.is_file():
            shutil.copy2(str(path), str(temp_path))
        else:
            shutil.copytree(str(path), str(temp_path), dirs_exist_ok=True)

        # Bind mount over original
        subprocess.run(['mount', '--bind', str(temp_path), str(path)], check=True, capture_output=True)

        # Record operation
        self.pinned_items[str(path)] = {
            'type': 'move', 
            'temp_path': str(temp_path),
            'original_path': str(path)
        }
        self.save_state()

    def pin_overlay(self, path):
        """Pin directory using overlay method"""
        path = Path(path).resolve()
        if not path.exists():
            raise Exception(f"Path does not exist: {path}")
        if not path.is_dir():
            raise Exception("Overlay mode only works with directories")
            
        # Check for submounts
        result = subprocess.run(['findmnt', '-rn', '-o', 'TARGET', '--submounts', str(path)], 
                              capture_output=True, text=True)
        if result.stdout.strip():
            raise Exception("Directory has submounts, aborting")

        overlay_base = Path(self.config.get('overlay_base', '/dev/shm/overlays'))
        dir_name = path.name
        overlay_id = f"{dir_name}-{int(time.time())}"
        upper_dir = overlay_base / f"{overlay_id}-upper"
        work_dir = overlay_base / f"{overlay_id}-work"
        merged_dir = Path('/mnt') / overlay_id

        upper_dir.mkdir(parents=True, exist_ok=True)
        work_dir.mkdir(parents=True, exist_ok=True)
        merged_dir.mkdir(parents=True, exist_ok=True)

        # Mount overlay
        subprocess.run([
            'mount', '-t', 'overlay', 'overlay',
            '-o', f'lowerdir={path},upperdir={upper_dir},workdir={work_dir}',
            str(merged_dir)
        ], check=True, capture_output=True)

        # Bind merged overlay over original
        subprocess.run(['mount', '--bind', str(merged_dir), str(path)], check=True, capture_output=True)

        self.pinned_items[str(path)] = {
            'type': 'overlay',
            'upper_dir': str(upper_dir),
            'work_dir': str(work_dir),
            'merged_dir': str(merged_dir),
            'overlay_id': overlay_id,
            'original_path': str(path)
        }
        self.save_state()

    def unpin(self, path):
        """Unpin file/directory and sync back to disk"""
        path = str(Path(path).resolve())
        if path not in self.pinned_items:
            raise Exception("Path is not pinned")

        item = self.pinned_items[path]
        
        try:
            # Unmount the bind mount
            subprocess.run(['umount', path], check=True, capture_output=True)
        except subprocess.CalledProcessError:
            # Force unmount if regular fails
            subprocess.run(['umount', '-f', path], check=True, capture_output=True)

        if item['type'] == 'move':
            # Sync data back using rsync
            temp_path = item['temp_path']
            source = temp_path + '/' if Path(temp_path).is_dir() else temp_path
            subprocess.run(['rsync', '-a', '--delete', source, path], check=True, capture_output=True)
            # Cleanup
            shutil.rmtree(temp_path) if Path(temp_path).is_dir() else os.remove(temp_path)
            
        elif item['type'] == 'overlay':
            # Additional cleanup for overlay
            try:
                subprocess.run(['umount', item['merged_dir']], capture_output=True)
            except:
                pass
                
            # Merge changes back using overlay-tools if available
            try:
                subprocess.run([
                    'overlay', 'merge', '-f', '-l', path, '-u', item['upper_dir']
                ], check=True, capture_output=True)
            except (subprocess.CalledProcessError, FileNotFoundError):
                # Fallback: manually copy changes
                print("Warning: overlay-tools not found, using rsync fallback")
                subprocess.run(['rsync', '-a', '--delete', 
                              f"{item['upper_dir']}/", f"{path}/"], 
                             capture_output=True)
            
            # Cleanup
            shutil.rmtree(item['upper_dir'], ignore_errors=True)
            shutil.rmtree(item['work_dir'], ignore_errors=True)
            shutil.rmtree(item['merged_dir'], ignore_errors=True)

        del self.pinned_items[path]
        self.save_state()

    def run_sync(self):
        """Perform sync of all pinned items to disk"""
        with self.lock:
            for path, item in list(self.pinned_items.items()):
                try:
                    if item['type'] == 'move':
                        temp_path = item['temp_path']
                        source = temp_path + '/' if Path(temp_path).is_dir() else temp_path
                        subprocess.run(['rsync', '-a', '--delete', source, path], 
                                     capture_output=True)
                    # Overlay items sync automatically through the filesystem
                except Exception as e:
                    print(f"Warning: Sync failed for {path}: {e}", file=sys.stderr)

    def get_status(self):
        """Get current status information"""
        with self.lock:
            status = {
                'pinned_items': {},
                'total_count': len(self.pinned_items),
                'memory_usage': {}
            }
            
            # Calculate memory usage (simplified - in production you'd use better methods)
            total_memory = 0
            for path, item in self.pinned_items.items():
                item_status = item.copy()
                
                # Estimate memory usage
                try:
                    if item['type'] == 'move':
                        temp_path = Path(item['temp_path'])
                        if temp_path.exists():
                            if temp_path.is_file():
                                size = temp_path.stat().st_size
                            else:
                                size = sum(f.stat().st_size for f in temp_path.rglob('*') if f.is_file())
                            item_status['memory_usage'] = size
                            total_memory += size
                    elif item['type'] == 'overlay':
                        upper_dir = Path(item['upper_dir'])
                        if upper_dir.exists():
                            size = sum(f.stat().st_size for f in upper_dir.rglob('*') if f.is_file())
                            item_status['memory_usage'] = size
                            total_memory += size
                except:
                    item_status['memory_usage'] = 0
                
                status['pinned_items'][path] = item_status
            
            status['total_memory'] = total_memory
            return status

    def handle_client(self, client_socket):
        """Handle a client connection"""
        try:
            # Receive command
            data = b""
            while True:
                chunk = client_socket.recv(4096)
                if not chunk:
                    break
                data += chunk
            
            if not data:
                return
                
            command = json.loads(data.decode('utf-8'))
            action = command.get('action')
            
            response = {'status': 'success', 'message': ''}
            
            try:
                if action == 'pin':
                    path = command['path']
                    mode = command.get('mode', 'move')
                    
                    if mode == 'overlay':
                        self.pin_overlay(path)
                        response['message'] = f"Pinned {path} using overlay"
                    else:
                        self.pin_move(path)
                        response['message'] = f"Pinned {path} using move"
                        
                elif action == 'unpin':
                    path = command['path']
                    self.unpin(path)
                    response['message'] = f"Unpinned {path}"
                    
                elif action == 'status':
                    status = self.get_status()
                    # Format status output
                    lines = ["RamPipe Status:", f"Total pinned items: {status['total_count']}"]
                    lines.append(f"Total memory used: {status['total_memory'] / 1024 / 1024:.2f} MB")
                    lines.append("\nPinned items:")
                    
                    for path, item in status['pinned_items'].items():
                        mem_mb = item.get('memory_usage', 0) / 1024 / 1024
                        lines.append(f"  {path} ({item['type']}) - {mem_mb:.2f} MB")
                    
                    response['message'] = '\n'.join(lines)
                    response['status_data'] = status
                    
                elif action == 'sync':
                    self.run_sync()
                    response['message'] = "Sync completed"
                    
                else:
                    response['status'] = 'error'
                    response['message'] = f"Unknown action: {action}"
                    
            except Exception as e:
                response['status'] = 'error'
                response['message'] = str(e)
                
            # Send response
            client_socket.send(json.dumps(response).encode('utf-8'))
            
        except Exception as e:
            error_response = json.dumps({
                'status': 'error', 
                'message': f'Internal error: {str(e)}'
            })
            client_socket.send(error_response.encode('utf-8'))
        finally:
            client_socket.close()

    def start_socket_server(self):
        """Start the UNIX socket server"""
        # Remove existing socket
        try:
            os.unlink(self.socket_path)
        except OSError:
            if os.path.exists(self.socket_path):
                raise
        
        # Create socket directory
        Path(self.socket_path).parent.mkdir(parents=True, exist_ok=True)
        
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(self.socket_path)
        server.listen(5)
        os.chmod(self.socket_path, 0o666)  # Allow non-root users to connect
        
        print(f"Socket server started at {self.socket_path}")
        
        while self.running:
            try:
                server.settimeout(1)  # Allow checking self.running
                client, addr = server.accept()
                # Handle client in a thread
                client_thread = threading.Thread(target=self.handle_client, args=(client,))
                client_thread.daemon = True
                client_thread.start()
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    print(f"Socket error: {e}", file=sys.stderr)
        
        server.close()

    def start_periodic_sync(self):
        """Start periodic sync thread"""
        def sync_loop():
            while self.running:
                time.sleep(self.config.get('sync_interval', 300))
                try:
                    self.run_sync()
                except Exception as e:
                    print(f"Periodic sync error: {e}", file=sys.stderr)
        
        sync_thread = threading.Thread(target=sync_loop, daemon=True)
        sync_thread.start()

    def signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        print("Shutting down RamPipe daemon...")
        self.running = False
        self.run_sync()  # Final sync
        sys.exit(0)

    def start_main_loop(self):
        """Start the main daemon loop"""
        print("Starting RamPipe daemon...")
        
        # Start periodic sync
        self.start_periodic_sync()
        
        # Start socket server (blocks until shutdown)
        self.start_socket_server()

if __name__ == '__main__':
    # Check if running as root
    if os.geteuid() != 0:
        print("Error: RamPipe daemon must be run as root", file=sys.stderr)
        sys.exit(1)
    
    daemon = RamPipeDaemon()
    daemon.start_main_loop()