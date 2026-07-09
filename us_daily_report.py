#!/usr/bin/env python3
"""
US Daily Report — Sends P&L summary to Telegram
Run via cron at 23:10 GMT+3 (after market close)

Reads from Alpaca API first (source of truth), falls back to local files.
Reconciles any discrepancies before generating report.
"""

import json
import os
import asyncio
from datetime import datetime, date
from typing import Dict, List
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

# Import bookkeeper for reconciliation and API-first reads
sys.path.insert(0, BASE_DIR)
from us_bookkeeper import reconcile_trades, get_daily_pnl, sync_capital


def load_json(path: str, default: dict = None) -> dict:
    """Load and validate JSON file with path sanitization."""
    sanitized_path = os.path.normpath(path)
    if not os.path.commonpath([BASE_DIR, sanitized_path]) == BASE_DIR:
        raise ValueError(f"Path traversal attempt blocked: {path}")
    
    if not os.path.exists(sanitized_path):
        return default or {}
    
    try:
        with open(sanitized_path) as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"JSON decode error in {path}: {e}")
        return default or {}
    except Exception as e:
        print(f"Error loading {path}: {e}")
        return default or {}


def get_local_trades(today: str) -> List[Dict]:
    """Get today's trades from local file (fallback)."""
    trades_data = load_json(TRADES_FILE, {"trades": []})
    return [t for t in trades_data.get("trades", []) if t.get("date") == today]


def get_daily_stats() -> Dict:
    """Calculate today's trading stats."""
    today = date.today().isoformat()
    
    # ── Step 1: Reconcile trades with Alpaca API ─────────────────────────
    reconciliation = None
    try:
        reconciliation = reconcile_trades(today)
        print(f"Reconciliation: {reconciliation}")
    except Exception as e:
        print(f"Reconciliation failed: {e}")
    
    # ── Step 2: Get P&L from Alpaca API (source of truth) ─────────────────
    alpaca_pnl = None
    try:
        alpaca_pnl = get_daily_pnl(today)
        print(f"Alpaca P&L: ${alpaca_pnl.get('total_pnl', 0):.2f} ({alpaca_pnl.get('wins', 0)}W/{alpaca_pnl.get('losses', 0)}L)")
    except Exception as e:
        print(f"Alpaca P&L fetch failed: {e}")
    
    # ── Step 3: Get capital from Alpaca API ──────────────────────────────
    capital_data = None
    try:
        capital_data = sync_capital()
        print(f"Alpaca capital: ${capital_data.get('cash', 0):.2f}")
    except Exception as e:
        print(f"Alpaca capital sync failed: {e}")
    
    # ── Step 4: Build stats from best available source ────────────────────
    if alpaca_pnl and alpaca_pnl.get("trades"):
        # Use Alpaca as primary source
        source = "alpaca-api"
        trades = alpaca_pnl.get("trades", [])
        total_pnl = alpaca_pnl.get("total_pnl", 0)
        wins = alpaca_pnl.get("wins", 0)
        losses = alpaca_pnl.get("losses", 0)
        total = wins + losses
        win_rate = (wins / total * 100) if total > 0 else 0
        best_trade = alpaca_pnl.get("best_trade")
        worst_trade = alpaca_pnl.get("worst_trade")
    else:
        # Fallback to local file
        source = "local-fallback"
        trades = get_local_trades(today)
        total_pnl = sum(t.get("pnl", 0) for t in trades)
        wins = len([t for t in trades if t.get("pnl", 0) > 0])
        losses = len([t for t in trades if t.get("pnl", 0) < 0])
        total = len(trades)
        win_rate = (wins / total * 100) if total > 0 else 0
        sorted_trades = sorted(trades, key=lambda t: t.get("pnl", 0), reverse=True)
        best_trade = sorted_trades[0] if sorted_trades else None
        worst_trade = sorted_trades[-1] if sorted_trades else None
    
    # Capital
    if capital_data:
        current_capital = capital_data.get("cash", 100000.0)
    else:
        capital_data_local = load_json(CAPITAL_FILE, {"cash": 100000.0})
        current_capital = capital_data_local.get("cash", 100000.0)
    
    initial_capital = 100000.0
    
    # Cumulative (always from local file for historical data)
    all_trades_data = load_json(TRADES_FILE, {"trades": []})
    all_trades = all_trades_data.get("trades", [])
    cumulative_pnl = sum(t.get("pnl", 0) for t in all_trades)
    
    # Build result
    stats = {
        "day": len(set(t.get("date") for t in all_trades if t.get("date"))),
        "total_pnl": round(total_pnl, 2),
        "pnl_pct": round(total_pnl / initial_capital * 100, 2),
        "win_rate": round(win_rate, 1),
        "total_trades": total,
        "wins": wins,
        "losses": losses,
        "best_trade": f"{best_trade.get('symbol', 'N/A')} +${best_trade.get('pnl', 0):.2f}" if best_trade and best_trade.get('pnl', 0) >= 0 else (f"{best_trade.get('symbol', 'N/A')} ${best_trade.get('pnl', 0):.2f}" if best_trade else "None"),
        "worst_trade": f"{worst_trade.get('symbol', 'N/A')} ${worst_trade.get('pnl', 0):.2f}" if worst_trade else "None",
        "cumulative_pnl": round(cumulative_pnl, 2),
        "current_capital": round(current_capital, 2),
        "initial_capital": initial_capital,
        "source": source,
        "reconciliation": reconciliation,
    }
    
    print(f"Stats built from: {source} | P&L=${total_pnl:.2f} | Trades={total}")
    return stats


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
    
    # Source indicator
    source_emoji = "🌐" if stats.get("source") == "alpaca-api" else "📁"
    source_text = "Alpaca API" if stats.get("source") == "alpaca-api" else "Local file"
    
    # Reconciliation note
    recon = stats.get("reconciliation")
    recon_text = ""
    if recon:
        if recon.get("missing_found", 0) > 0:
            recon_text = f"\n⚠️ Reconciled: {recon['missing_found']} missing trade(s) added from Alpaca"
        else:
            recon_text = "\n✅ Local file in sync with Alpaca"
    
    msg = f"""{pnl_emoji} US Paper Trading Report

📅 Day {stats['day']} of 10 — {date.today().strftime('%A, %b %d')}

💰 P&L: ${stats['total_pnl']:.2f} ({stats['pnl_pct']:.2f}%)
📈 Win Rate: {stats['win_rate']:.1f}%
🎯 Trades: {stats['total_trades']} ({stats['wins']}W / {stats['losses']}L)
🏆 Best: {stats['best_trade']}
💩 Worst: {stats['worst_trade']}

📊 Cumulative: ${stats['cumulative_pnl']:.2f}
💰 Current Capital: ${stats['current_capital']:.2f} (Started: ${stats['initial_capital']:.2f})
{source_emoji} Source: {source_text}{recon_text}

—
Next market open: Tomorrow 16:30 GMT+3
"""
    
    # Use sync method
    result = bot.send_message(msg)
    print(f"[{datetime.now(ET).isoformat()}] Daily report sent: {result}")


if __name__ == "__main__":
    send_daily_report_sync()
