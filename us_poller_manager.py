#!/usr/bin/env python3

import subprocess
import sys
import os

def is_trading_day():
    """Check if today is a US trading day"""
    try:
        result = subprocess.run([sys.executable, '/home/mino/us-exec/us_market_calendar.py'], 
                              capture_output=True, text=True)
        return result.returncode == 0
    except Exception as e:
        print(f"Error checking trading day: {e}")
        return False

def start_poller():
    """Start the US price poller"""
    try:
        # Change to the working directory
        os.chdir('/home/mino/us-exec')
        
        # Start the poller in the background
        process = subprocess.Popen(['nohup', 'python3', 'us_poller.py'], 
                                 stdout=open('us_poller.log', 'a'), 
                                 stderr=subprocess.STDOUT,
                                 preexec_fn=os.setpgrp)
        
        # Give it time to start
        import time
        time.sleep(5)
        
        # Check if it's running
        result = subprocess.run(['pgrep', '-f', 'python.*us_poller'], 
                              capture_output=True)
        return result.returncode == 0
    except Exception as e:
        print(f"Error starting poller: {e}")
        return False

def send_telegram_message(message):
    """Send a message via OpenClaw gateway"""
    try:
        subprocess.run([
            '/home/mino/.nvm/current/bin/openclaw', 'gateway', 'call', 'sessions.send',
            'agent:main:telegram:direct:5529987063',
            message
        ])
    except Exception as e:
        print(f"Error sending message: {e}")

def main():
    print("Checking if today is a US trading day...")
    
    if is_trading_day():
        print("📅 Today is a US trading day - starting price poller")
        send_telegram_message("📅 Today is a US trading day - starting price poller")
        
        if start_poller():
            print("✅ US Price poller started successfully - monitoring Sharia-compliant picks")
            send_telegram_message("🇺🇸 US Price poller started — monitoring Sharia-compliant picks.")
        else:
            print("❌ US poller failed to start - check /home/mino/us-exec/us_poller.log")
            send_telegram_message("⚠️ US poller failed to start — check /home/mino/us-exec/us_poller.log 🔴")
    else:
        print("⏭️ US holiday/weekend — skipping poller")
        send_telegram_message("⏭️ US holiday/weekend — skipping poller")

if __name__ == "__main__":
    main()