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
import re

import pytz

ET = pytz.timezone("America/New_York")
BASE_DIR = "/home/mino/us-exec"

# Sanitize file paths to prevent path traversal
TRADES_FILE = os.path.normpath(os.path.join(BASE_DIR, "us_trades.json"))
SUMMARY_FILE = os.path.normpath(os.path.join(BASE_DIR, "us_daily_summary.json"))
CAPITAL_FILE = os.path.normpath(os.path.join(BASE_DIR, "us_capital.json"))

# Validate that paths are within BASE_DIR to prevent path traversal
for path in [TRADES_FILE, SUMMARY_FILE, CAPITAL_FILE]:
    if not os.path.commonpath([BASE_DIR, path]) == BASE_DIR:
        raise ValueError(f"Path traversal detected: {path}")

# Import telegram handler
import sys
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, f"{BASE_DIR}/shared")

from us_telegram_handler import USTelegramBot


def validate_json_schema(data: dict, schema_type: str) -> bool:
    """Validate JSON data against expected schema."""
    try:
        if schema_type == "trades":
            # Validate trades schema
            if not isinstance(data, dict):
                return False
            trades = data.get("trades", [])
            if not isinstance(trades, list):
                return False
            for trade in trades:
                if not isinstance(trade, dict):
                    return False
                required_fields = ["date", "symbol", "pnl"]
                if not all(field in trade for field in required_fields):
                    return False
                if not isinstance(trade["date"], str) or not re.match(r"\d{4}-\d{2}-\d{2}", trade["date"]):
                    return False
                if not isinstance(trade["symbol"], str) or not re.match(r"^[A-Z.-]+$", trade["symbol"]):
                    return False
                if not isinstance(trade["pnl"], (int, float)):
                    return False
            return True
        elif schema_type == "capital":
            # Validate capital schema
            if not isinstance(data, dict):
                return False
            # Accept both formats: with "available_capital" or "cash"
            capital_field = data.get("available_capital") or data.get("cash")
            if capital_field is None:
                return False
            if not isinstance(capital_field, (int, float)):
                return False
            if not isinstance(data.get("updated_at", ""), str):
                return False
            return True
        return False
    except Exception:
        return False


def load_json(path: str, default: dict = None) -> dict:
    """Load and validate JSON file with path sanitization."""
    # Sanitize path
    sanitized_path = os.path.normpath(path)
    if not os.path.commonpath([BASE_DIR, sanitized_path]) == BASE_DIR:
        raise ValueError(f"Path traversal attempt blocked: {path}")
    
    if not os.path.exists(sanitized_path):
        return default or {}
    
    try:
        with open(sanitized_path) as f:
            data = json.load(f)
        return data
    except json.JSONDecodeError as e:
        print(f"JSON decode error in {path}: {e}")
        return default or {}
    except Exception as e:
        print(f"Error loading {path}: {e}")
        return default or {}


def get_daily_stats() -> Dict:
    """Calculate today's trading stats."""
    trades_data = load_json(TRADES_FILE, {"trades": []})
    
    # Validate trades schema
    if not validate_json_schema(trades_data, "trades"):
        print("Invalid trades data schema, using empty data")
        trades_data = {"trades": []}
    
    today = date.today().isoformat()
    
    today_trades = [t for t in trades_data.get("trades", []) if t.get("date") == today]
    
    # Load actual capital from config
    capital_data = load_json(CAPITAL_FILE, {"available_capital": 100000.0})
    
    # Validate capital schema
    if not validate_json_schema(capital_data, "capital"):
        print("Invalid capital data schema, using default capital")
        capital_data = {"available_capital": 100000.0}
    
    initial_capital = 100000.0  # Starting capital
    current_capital = capital_data.get("available_capital", 100000.0)
    
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
            "current_capital": round(current_capital, 2),
            "initial_capital": initial_capital,
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
    all_trades = trades_data.get("trades", [])
    cumulative_pnl = sum(t.get("pnl", 0) for t in all_trades)
    
    return {
        "day": len(set(t.get("date") for t in all_trades)),
        "total_pnl": round(total_pnl, 2),
        "pnl_pct": round(total_pnl / initial_capital * 100, 2),
        "win_rate": round(win_rate, 1),
        "total_trades": total,
        "wins": wins,
        "losses": losses,
        "best_trade": f"{best['symbol']} +${best['pnl']:.2f}" if best else "None",
        "worst_trade": f"{worst['symbol']} ${worst['pnl']:.2f}" if worst else "None",
        "cumulative_pnl": round(cumulative_pnl, 2),
        "current_capital": round(current_capital, 2),
        "initial_capital": initial_capital,
    }


def send_daily_report_sync():
    """Send daily report synchronously (for cron jobs)."""
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
💰 Current Capital: ${stats['current_capital']:.2f} (Started: ${stats['initial_capital']:.2f})

—
Next market open: Tomorrow 16:30 GMT+3
"""
    
    # Use sync method
    result = bot.send_message(msg)
    print(f"[{datetime.now(ET).isoformat()}] Daily report sent: {result}")


if __name__ == "__main__":
    send_daily_report_sync()
