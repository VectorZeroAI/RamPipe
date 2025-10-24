#!/usr/bin/env python3

"""
CLI client for comunicating with the demon.
"""


import socket
import sys
import json
import argparse

def send_command(command_dict):
    """Send command to daemon via UNIX socket and return response"""
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(10)  # 10 second timeout
        client.connect("/run/rampipe.sock")
        
        # Send command
        client.send(json.dumps(command_dict).encode('utf-8'))
        client.shutdown(socket.SHUT_WR)  # Signal we're done writing
        
        # Receive response
        response = b""
        while True:
            chunk = client.recv(4096)
            if not chunk:
                break
            response += chunk
        
        response_data = json.loads(response.decode('utf-8'))
        
        if response_data.get('status') == 'success':
            if response_data.get('message'):
                print(response_data['message'])
            return True
        else:
            print(f"Error: {response_data.get('message', 'Unknown error')}")
            return False
            
    except socket.timeout:
        print("Error: Connection timeout")
        return False
    except ConnectionRefusedError:
        print("Error: Daemon not running. Start with: systemctl start rampiped")
        return False
    except FileNotFoundError:
        print("Error: Daemon not running. Start with: systemctl start rampiped")
        return False
    except Exception as e:
        print(f"Error: {e}")
        return False
    finally:
        try:
            client.close()
        except:
            pass

def main():
    parser = argparse.ArgumentParser(description='RamPipe CLI - Manage RAM caching')
    subparsers = parser.add_subparsers(dest='action', help='Action to perform')
    
    # Pin command
    pin_parser = subparsers.add_parser('pin', help='Pin file/directory to RAM')
    pin_parser.add_argument('path', help='Path to file or directory')
    pin_parser.add_argument('--move', action='store_true', help='Use move mode (default)')
    pin_parser.add_argument('--overlay', action='store_true', help='Use overlay mode (directories only)')
    
    # Unpin command
    unpin_parser = subparsers.add_parser('unpin', help='Unpin file/directory from RAM')
    unpin_parser.add_argument('path', help='Path to file or directory')
    
    # Status command
    subparsers.add_parser('status', help='Show current status')
    
    # Sync command
    subparsers.add_parser('sync', help='Force sync all data to disk')
    
    args = parser.parse_args()
    
    if not args.action:
        parser.print_help()
        sys.exit(1)
    
    if args.action == 'pin':
        # Determine mode
        if args.overlay:
            mode = 'overlay'
        else:
            mode = 'move'
            
        send_command({
            'action': 'pin', 
            'path': args.path, 
            'mode': mode
        })
        
    elif args.action == 'unpin':
        send_command({
            'action': 'unpin',
            'path': args.path
        })
        
    elif args.action == 'status':
        send_command({'action': 'status'})
        
    elif args.action == 'sync':
        send_command({'action': 'sync'})

if __name__ == '__main__':
    main()