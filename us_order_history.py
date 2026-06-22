#!/usr/bin/env python3
"""
US Order History CSV Generator
==============================
Generates CSV files for order history and PnL tracking.

Files:
- history/us_orders.csv — All orders with timestamps
- history/us_pnl.csv — Daily PnL summary
- history/us_positions.csv — Position history

Author: Mino (kimi-k2.6)
Version: 4.12
Date: 2026-06-23
"""

import csv
import json
import os
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, List, Optional
import pytz

ET = pytz.timezone("America/New_York")
BASE_DIR = Path("/home/mino/us-exec")
HISTORY_DIR = BASE_DIR / "history"

# Ensure history directory exists
HISTORY_DIR.mkdir(exist_ok=True)

# File paths
ORDERS_CSV = HISTORY_DIR / "us_orders.csv"
PNL_CSV = HISTORY_DIR / "us_pnl.csv"
POSITIONS_CSV = HISTORY_DIR / "us_positions.csv"

# ─── CSV Helpers ─────────────────────────────────────────────────────────────

def ensure_csv_headers(filepath: Path, headers: List[str]):
    """Create CSV with headers if it doesn't exist."""
    if not filepath.exists():
        with open(filepath, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(headers)

def append_csv_row(filepath: Path, row: List):
    """Append a row to CSV file."""
    with open(filepath, 'a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(row)

def read_csv_rows(filepath: Path) -> List[Dict]:
    """Read all rows from CSV as dicts."""
    if not filepath.exists():
        return []
    with open(filepath) as f:
        reader = csv.DictReader(f)
        return list(reader)

# ─── Order History ───────────────────────────────────────────────────────────

def log_order(symbol: str, side: str, qty: int, price: float, 
              order_type: str = "market", status: str = "filled",
              order_id: str = "", signal: str = "", regime: str = ""):
    """Log an order to CSV history."""
    ensure_csv_headers(ORDERS_CSV, [
        "date", "timestamp", "symbol", "side", "qty", "price", 
        "order_type", "status", "order_id", "signal", "regime"
    ])
    
    now = datetime.now(ET)
    row = [
        now.date().isoformat(),
        now.isoformat(),
        symbol,
        side,
        qty,
        round(price, 2),
        order_type,
        status,
        order_id,
        signal,
        regime,
    ]
    append_csv_row(ORDERS_CSV, row)

# ─── PnL Tracking ────────────────────────────────────────────────────────────

def log_daily_pnl(day: date = None):
    """Log daily PnL to CSV."""
    if day is None:
        day = date.today()
    
    ensure_csv_headers(PNL_CSV, [
        "date", "total_trades", "wins", "losses", "win_rate",
        "gross_pnl", "net_pnl", "avg_pnl", "avg_win", "avg_loss",
        "largest_win", "largest_loss", "capital_start", "capital_end",
        "drawdown_pct", "notes"
    ])
    
    # Load trades
    trades_file = BASE_DIR / "us_trades.json"
    if not trades_file.exists():
        return
    
    with open(trades_file) as f:
        data = json.load(f)
    
    trades = data.get("trades", []) if isinstance(data, dict) else data
    day_trades = [t for t in trades if t.get("date") == day.isoformat()]
    
    if not day_trades:
        return
    
    # Calculate stats
    wins = [t for t in day_trades if t.get("net_pnl", 0) > 0]
    losses = [t for t in day_trades if t.get("net_pnl", 0) <= 0]
    
    gross_pnl = sum(t.get("gross_pnl", 0) for t in day_trades)
    net_pnl = sum(t.get("net_pnl", 0) for t in day_trades)
    
    avg_pnl = net_pnl / len(day_trades) if day_trades else 0
    avg_win = sum(t.get("net_pnl", 0) for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t.get("net_pnl", 0) for t in losses) / len(losses) if losses else 0
    
    # Capital
    capital_file = BASE_DIR / "us_capital.json"
    capital_data = {}
    if capital_file.exists():
        with open(capital_file) as f:
            capital_data = json.load(f)
    
    capital_end = capital_data.get("available_capital", 100000)
    capital_start = capital_end - net_pnl
    drawdown = ((capital_start - capital_end) / capital_start * 100) if capital_start > 0 else 0
    
    row = [
        day.isoformat(),
        len(day_trades),
        len(wins),
        len(losses),
        round(len(wins) / len(day_trades) * 100, 1) if day_trades else 0,
        round(gross_pnl, 2),
        round(net_pnl, 2),
        round(avg_pnl, 2),
        round(avg_win, 2),
        round(avg_loss, 2),
        round(max((t.get("net_pnl", 0) for t in wins), default=0), 2),
        round(min((t.get("net_pnl", 0) for t in losses), default=0), 2),
        round(capital_start, 2),
        round(capital_end, 2),
        round(drawdown, 2),
        "",  # notes
    ]
    append_csv_row(PNL_CSV, row)

# ─── Position History ─────────────────────────────────────────────────────────

def log_position(symbol: str, qty: int, entry_price: float, 
                 exit_price: float = None, entry_time: str = None,
                 exit_time: str = None, exit_reason: str = "",
                 pnl: float = 0, pnl_pct: float = 0, regime: str = ""):
    """Log position lifecycle to CSV."""
    ensure_csv_headers(POSITIONS_CSV, [
        "date", "symbol", "qty", "entry_price", "exit_price",
        "entry_time", "exit_time", "exit_reason", "pnl", "pnl_pct", "regime"
    ])
    
    now = datetime.now(ET)
    row = [
        now.date().isoformat(),
        symbol,
        qty,
        round(entry_price, 2),
        round(exit_price, 2) if exit_price else "",
        entry_time or now.isoformat(),
        exit_time or "",
        exit_reason,
        round(pnl, 2),
        round(pnl_pct, 2),
        regime,
    ]
    append_csv_row(POSITIONS_CSV, row)

# ─── Report Generation ──────────────────────────────────────────────────────

def generate_order_report(day: date = None) -> str:
    """Generate order report for a specific day."""
    if day is None:
        day = date.today()
    
    rows = read_csv_rows(ORDERS_CSV)
    day_rows = [r for r in rows if r.get("date") == day.isoformat()]
    
    if not day_rows:
        return f"No orders for {day.isoformat()}"
    
    lines = [f"📋 Order History — {day.isoformat()}", ""]
    
    for r in day_rows:
        emoji = "🟢" if r.get("side") == "buy" else "🔴"
        lines.append(
            f"{emoji} {r['symbol']}: {r['side'].upper()} {r['qty']} @ ${r['price']} "
            f"({r['status']}) signal={r.get('signal', '')}"
        )
    
    return "\n".join(lines)

def generate_pnl_report(days: int = 7) -> str:
    """Generate PnL report for last N days."""
    rows = read_csv_rows(PNL_CSV)
    
    if not rows:
        return "No PnL data available"
    
    # Get last N days
    today = date.today()
    cutoff = (today - timedelta(days=days)).isoformat()
    recent = [r for r in rows if r.get("date", "") >= cutoff]
    
    lines = [f"💰 PnL Report — Last {days} Days", ""]
    
    total_pnl = 0
    total_wins = 0
    total_losses = 0
    
    for r in recent:
        pnl = float(r.get("net_pnl", 0))
        emoji = "🟢" if pnl > 0 else "🔴" if pnl < 0 else "⚪"
        lines.append(
            f"{emoji} {r['date']}: ${pnl:+.2f} | "
            f"WR: {r.get('win_rate', 0)}% | "
            f"Trades: {r.get('total_trades', 0)}"
        )
        total_pnl += pnl
        total_wins += int(r.get("wins", 0))
        total_losses += int(r.get("losses", 0))
    
    lines.append("")
    lines.append(f"📊 Total: ${total_pnl:+.2f}")
    lines.append(f"✅ Wins: {total_wins} | ❌ Losses: {total_losses}")
    
    return "\n".join(lines)

# ─── Export to TASI Format ─────────────────────────────────────────────────

def export_to_tasi_format():
    """Export US data to TASI-compatible format."""
    # This would convert US data to match TASI's history/daily_pnl.csv format
    # For future integration
    pass

# ─── Test ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Testing US Order History CSV...")
    
    # Test order logging
    log_order("AAPL", "buy", 10, 175.50, signal="vwap_reclaim", regime="TRENDING")
    log_order("AAPL", "sell", 10, 180.00, signal="target_hit", regime="TRENDING")
    
    print("✅ Orders logged")
    
    # Test PnL logging
    log_daily_pnl()
    print("✅ PnL logged")
    
    # Test position logging
    log_position("AAPL", 10, 175.50, 180.00, 
                 exit_reason="Target hit", pnl=41.45, pnl_pct=2.56, regime="TRENDING")
    print("✅ Position logged")
    
    # Test reports
    print("\n" + generate_order_report())
    print("\n" + generate_pnl_report())
    
    print("\n✅ CSV history system complete")
