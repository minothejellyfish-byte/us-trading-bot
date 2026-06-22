#!/usr/bin/env python3
"""
US Daily Report — Sends P&L summary to Telegram
Run via cron at 23:10 GMT+3 (after market close)
"""

import json
import os
import asyncio
from datetime import datetime, date
from typing import Dict

import pytz

ET = pytz.timezone("America/New_York")
BASE_DIR = "/home/mino/us-exec"
TRADES_FILE = f"{BASE_DIR}/us_trades.json"
SUMMARY_FILE = f"{BASE_DIR}/us_daily_summary.json"

# Import telegram handler
import sys
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, f"{BASE_DIR}/shared")

from us_telegram_handler import USTelegramBot


def load_json(path: str, default: dict = None) -> dict:
    if not os.path.exists(path):
        return default or {}
    with open(path) as f:
        return json.load(f)


def get_daily_stats() -> Dict:
    """Calculate today's trading stats."""
    trades = load_json(TRADES_FILE, {"trades": []})
    today = date.today().isoformat()
    
    today_trades = [t for t in trades.get("trades", []) if t.get("date") == today]
    
    if not today_trades:
        return {
            "day": 1,
            "total_pnl": 0.0,
            "pnl_pct": 0.0,
            "win_rate": 0.0,
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "best_trade": "None",
            "worst_trade": "None",
            "cumulative_pnl": 0.0,
        }
    
    # Calculate P&L
    total_pnl = sum(t.get("pnl", 0) for t in today_trades)
    wins = len([t for t in today_trades if t.get("pnl", 0) > 0])
    losses = len([t for t in today_trades if t.get("pnl", 0) < 0])
    total = len(today_trades)
    win_rate = (wins / total * 100) if total > 0 else 0
    
    # Best/worst
    sorted_trades = sorted(today_trades, key=lambda t: t.get("pnl", 0), reverse=True)
    best = sorted_trades[0] if sorted_trades else None
    worst = sorted_trades[-1] if sorted_trades else None
    
    # Cumulative
    all_trades = trades.get("trades", [])
    cumulative_pnl = sum(t.get("pnl", 0) for t in all_trades)
    
    return {
        "day": len(set(t.get("date") for t in all_trades)),
        "total_pnl": round(total_pnl, 2),
        "pnl_pct": round(total_pnl / 100000 * 100, 2),
        "win_rate": round(win_rate, 1),
        "total_trades": total,
        "wins": wins,
        "losses": losses,
        "best_trade": f"{best['symbol']} +${best['pnl']:.2f}" if best else "None",
        "worst_trade": f"{worst['symbol']} ${worst['pnl']:.2f}" if worst else "None",
        "cumulative_pnl": round(cumulative_pnl, 2),
    }


async def send_daily_report():
    stats = get_daily_stats()
    bot = USTelegramBot()
    
    # Determine emoji based on P&L
    if stats["total_pnl"] > 0:
        pnl_emoji = "🟢"
    elif stats["total_pnl"] < 0:
        pnl_emoji = "🔴"
    else:
        pnl_emoji = "⚪"
    
    msg = f"""{pnl_emoji} US Paper Trading Report

📅 Day {stats['day']} of 10 — {date.today().strftime('%A, %b %d')}

💰 P&L: ${stats['total_pnl']:.2f} ({stats['pnl_pct']:.2f}%)
📈 Win Rate: {stats['win_rate']:.1f}%
🎯 Trades: {stats['total_trades']} ({stats['wins']}W / {stats['losses']}L)
🏆 Best: {stats['best_trade']}
💩 Worst: {stats['worst_trade']}

📊 Cumulative: ${stats['cumulative_pnl']:.2f}

—
Next market open: Tomorrow 16:30 GMT+3
"""
    
    await bot.send_message(msg)
    print(f"[{datetime.now(ET).isoformat()}] Daily report sent")


if __name__ == "__main__":
    asyncio.run(send_daily_report())
