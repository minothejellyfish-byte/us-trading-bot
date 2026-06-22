#!/bin/bash
# US Trading System — Start Script
# Run all US components: screener (pre-market) + poller + bot

set -e

BASE_DIR="/home/mino/us-exec"
LOG_DIR="$BASE_DIR/logs"
mkdir -p "$LOG_DIR"

# Source environment
if [ -f "$BASE_DIR/.env" ]; then
    export $(grep -v '^#' "$BASE_DIR/.env" | xargs)
fi

echo "🇺🇸 US Trading System"
echo "===================="

# Check Alpaca connection
echo "Checking Alpaca..."
python3 -c "
from alpaca_api import AlpacaTrader
t = AlpacaTrader()
info = t.get_account()
print(f'Account: {info[\"id\"]}')
print(f'Cash: \${info[\"cash\"]}')
print(f'Status: {info[\"status\"]}')
"

# Start bot in background
echo "Starting US Bot..."
nohup python3 "$BASE_DIR/us_bot.py" > "$LOG_DIR/bot.log" 2>&1 &
echo $! > "$LOG_DIR/bot.pid"

# Start poller in background (only during market hours)
echo "Starting US Poller..."
nohup python3 "$BASE_DIR/us_poller.py" > "$LOG_DIR/poller.log" 2>&1 &
echo $! > "$LOG_DIR/poller.pid"

echo ""
echo "✅ US System Started"
echo "  Bot PID: $(cat $LOG_DIR/bot.pid)"
echo "  Poller PID: $(cat $LOG_DIR/poller.pid)"
echo "  Logs: $LOG_DIR/"
echo ""
echo "Commands:"
echo "  Stop: ./stop_us_system.sh"
echo "  Status: tail -f $LOG_DIR/poller.log"
