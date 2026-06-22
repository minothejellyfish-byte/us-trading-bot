#!/bin/bash
# US Trading System — Stop Script

BASE_DIR="/home/mino/us-exec"
LOG_DIR="$BASE_DIR/logs"

echo "🛑 Stopping US Trading System..."

# Stop bot
if [ -f "$LOG_DIR/bot.pid" ]; then
    kill $(cat "$LOG_DIR/bot.pid") 2>/dev/null || true
    rm "$LOG_DIR/bot.pid"
    echo "  Bot stopped"
fi

# Stop poller
if [ -f "$LOG_DIR/poller.pid" ]; then
    kill $(cat "$LOG_DIR/poller.pid") 2>/dev/null || true
    rm "$LOG_DIR/poller.pid"
    echo "  Poller stopped"
fi

echo "✅ US System Stopped"
