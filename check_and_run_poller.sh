#!/bin/bash

# Change to the script directory
cd /home/mino/us-exec

# Check if today is a US trading day
if python3 /home/mino/us-exec/us_market_calendar.py; then
    echo "📅 Today is a US trading day - starting price poller"
    
    # Start the US price poller for Alpaca paper trading
    cd /home/mino/us-exec && nohup python3 us_poller.py >> us_poller.log 2>&1 &
    
    # Wait 5 seconds for the process to start
    sleep 5
    
    # Verify if the process is running
    if pgrep -f 'python.*us_poller' > /dev/null; then
        echo "✅ US Price poller started successfully - monitoring Sharia-compliant picks"
        # Send success message
        echo "🇺🇸 US Price poller started — monitoring Sharia-compliant picks."
    else
        echo "❌ US poller failed to start - check /home/mino/us-exec/us_poller.log"
        # Send failure message
        echo "⚠️ US poller failed to start — check /home/mino/us-exec/us_poller.log 🔴"
    fi
else
    echo "⏭️ US holiday/weekend — skipping poller"
fi