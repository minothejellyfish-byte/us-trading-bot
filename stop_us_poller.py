#!/usr/bin/env python3
"""Stop the US trading poller daemon."""
import os
import signal
import sys

PID_FILE = "/home/mino/us-exec/us_poller.pid"

def main():
    if os.path.exists(PID_FILE):
        with open(PID_FILE) as f:
            pid = int(f.read().strip())
        try:
            os.kill(pid, signal.SIGTERM)
            print(f"Poller {pid} stopped")
        except ProcessLookupError:
            print("Poller already stopped")
        os.remove(PID_FILE)
    else:
        print("No poller PID file")

if __name__ == "__main__":
    main()
