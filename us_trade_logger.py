#!/usr/bin/env python3
"""
US Trade Logger
===============

Logs every trade with full details:
- Entry/exit times and prices
- P&L calculation
- Commission tracking
- Regime context
- Signal type (VWAP, breakout, zone hold)

Output:
- us_trades.json — full trade history
- us_daily_summary.json — daily aggregated stats
"""

import json
import os
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional
import pytz

ET = pytz.timezone("America/New_York")

BASE_DIR = "/home/mino/us-exec"
TRADES_FILE = f"{BASE_DIR}/us_trades.json"
DAILY_FILE = f"{BASE_DIR}/us_daily_summary.json"

ALPACA_COMMISSION = 0.00  # Alpaca has $0 commission
ALPACA_SPREAD = 0.001     # 0.1% estimated spread cost


def log_trade(symbol: str, side: str, qty: int, price: float,
              signal: str = "", regime: str = "", notes: str = "") -> Dict:
    """Log a trade entry or exit."""
    
    trade = {
        "id": f"{symbol}_{datetime.now(ET).strftime('%H%M%S')}",
        "symbol": symbol,
        "side": side.upper(),
        "qty": qty,
        "price": round(price, 2),
        "timestamp": datetime.now(ET).isoformat(),
        "date": date.today().isoformat(),
        "signal": signal,
        "regime": regime,
        "notes": notes,
    }
    
    # Load existing trades
    trades = load_trades()
    trades.append(trade)
    
    # Save
    with open(TRADES_FILE, "w") as f:
        json.dump(trades, f, indent=2)
    
    return trade


def close_trade(symbol: str, exit_price: float, exit_reason: str,
                regime: str = "") -> Optional[Dict]:
    """Close an open position and calculate P&L."""
    
    # Load positions
    positions_file = f"{BASE_DIR}/us_positions.json"
    try:
        with open(positions_file) as f:
            data = json.load(f)
            positions = data.get("positions", {})
    except:
        return None
    
    if symbol not in positions:
        return None
    
    pos = positions[symbol]
    entry_price = pos.get("entry_price", 0)
    qty = pos.get("qty", 0)
    entry_time = pos.get("entry_time", "")
    entry_signal = pos.get("signal", "")
    
    # Calculate P&L
    gross_pnl = (exit_price - entry_price) * qty
    spread_cost = (entry_price + exit_price) * qty * ALPACA_SPREAD
    net_pnl = gross_pnl - spread_cost
    pnl_pct = ((exit_price - entry_price) / entry_price * 100) if entry_price else 0
    
    # Duration
    duration_min = 0
    if entry_time:
        try:
            entry_dt = datetime.fromisoformat(entry_time)
            exit_dt = datetime.now(ET)
            duration_min = (exit_dt - entry_dt).total_seconds() / 60
        except:
            pass
    
    closed_trade = {
        "id": pos.get("order_id", f"{symbol}_{datetime.now(ET).strftime('%H%M%S')}"),
        "symbol": symbol,
        "qty": qty,
        "entry_price": round(entry_price, 2),
        "entry_time": entry_time,
        "entry_signal": entry_signal,
        "exit_price": round(exit_price, 2),
        "exit_time": datetime.now(ET).isoformat(),
        "exit_reason": exit_reason,
        "exit_regime": regime,
        "gross_pnl": round(gross_pnl, 2),
        "spread_cost": round(spread_cost, 2),
        "net_pnl": round(net_pnl, 2),
        "pnl_pct": round(pnl_pct, 2),
        "duration_min": round(duration_min, 1),
        "date": date.today().isoformat(),
    }
    
    # Load trades and append
    trades = load_trades()
    trades.append(closed_trade)
    
    with open(TRADES_FILE, "w") as f:
        json.dump(trades, f, indent=2)
    
    return closed_trade


def load_trades() -> List[Dict]:
    """Load all trades."""
    if not os.path.exists(TRADES_FILE):
        return []
    with open(TRADES_FILE) as f:
        data = json.load(f)
        # Handle both {"trades": [...]} and raw list formats
        if isinstance(data, dict):
            return data.get("trades", [])
        elif isinstance(data, list):
            return data
        return []


def get_daily_summary(day: date = None) -> Dict:
    """Calculate daily performance summary."""
    if day is None:
        day = date.today()
    
    day_str = day.isoformat()
    trades = load_trades()
    day_trades = [t for t in trades if t.get("date") == day_str]
    
    # Separate entries and exits
    entries = [t for t in day_trades if t.get("side") == "BUY" or "entry_price" in t]
    exits = [t for t in day_trades if "exit_price" in t]
    
    # Calculate stats
    wins = [t for t in exits if t.get("net_pnl", 0) > 0]
    losses = [t for t in exits if t.get("net_pnl", 0) <= 0]
    
    total_pnl = sum(t.get("net_pnl", 0) for t in exits)
    avg_pnl = total_pnl / len(exits) if exits else 0
    avg_win = sum(t.get("net_pnl", 0) for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t.get("net_pnl", 0) for t in losses) / len(losses) if losses else 0
    
    win_rate = len(wins) / len(exits) * 100 if exits else 0
    
    # Duration stats
    durations = [t.get("duration_min", 0) for t in exits if t.get("duration_min")]
    avg_duration = sum(durations) / len(durations) if durations else 0
    
    summary = {
        "date": day_str,
        "total_trades": len(entries),
        "closed_trades": len(exits),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 1),
        "total_pnl": round(total_pnl, 2),
        "avg_pnl_per_trade": round(avg_pnl, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "avg_duration_min": round(avg_duration, 1),
        "largest_win": round(max((t.get("net_pnl", 0) for t in wins), default=0), 2),
        "largest_loss": round(min((t.get("net_pnl", 0) for t in losses), default=0), 2),
    }
    
    return summary


def save_daily_summary():
    """Save daily summary to file."""
    summary = get_daily_summary()
    
    # Load existing summaries
    summaries = {}
    if os.path.exists(DAILY_FILE):
        with open(DAILY_FILE) as f:
            summaries = json.load(f)
    
    summaries[summary["date"]] = summary
    
    with open(DAILY_FILE, "w") as f:
        json.dump(summaries, f, indent=2)
    
    return summary


def get_weekly_summary() -> Dict:
    """Calculate rolling 7-day summary."""
    trades = load_trades()
    
    # Get last 7 days
    today = date.today()
    week_ago = today - timedelta(days=7)
    
    week_trades = [t for t in trades 
                   if t.get("date") and 
                   date.fromisoformat(t["date"]) >= week_ago]
    
    exits = [t for t in week_trades if "exit_price" in t]
    wins = [t for t in exits if t.get("net_pnl", 0) > 0]
    
    total_pnl = sum(t.get("net_pnl", 0) for t in exits)
    
    return {
        "period": f"{week_ago.isoformat()} to {today.isoformat()}",
        "total_trades": len(exits),
        "wins": len(wins),
        "losses": len(exits) - len(wins),
        "win_rate": round(len(wins) / len(exits) * 100, 1) if exits else 0,
        "total_pnl": round(total_pnl, 2),
        "avg_pnl_per_trade": round(total_pnl / len(exits), 2) if exits else 0,
    }


def format_trade_report(trade: Dict) -> str:
    """Format a single trade for Telegram."""
    symbol = trade.get("symbol", "")
    pnl = trade.get("net_pnl", 0)
    pnl_pct = trade.get("pnl_pct", 0)
    emoji = "🟢" if pnl > 0 else "🔴" if pnl < 0 else "⚪"
    
    lines = [
        f"{emoji} <b>{symbol}</b> {trade.get('side', '')}",
        f"Qty: {trade.get('qty', 0)} @ ${trade.get('price', 0):.2f}",
    ]
    
    if "exit_price" in trade:
        lines.extend([
            f"Entry: ${trade.get('entry_price', 0):.2f}",
            f"Exit: ${trade.get('exit_price', 0):.2f}",
            f"P&L: ${pnl:+.2f} ({pnl_pct:+.2f}%)",
            f"Duration: {trade.get('duration_min', 0):.0f} min",
            f"Reason: {trade.get('exit_reason', '')}",
        ])
    
    return "\n".join(lines)


def format_daily_report(summary: Dict) -> str:
    """Format daily summary for Telegram."""
    pnl = summary.get("total_pnl", 0)
    emoji = "🟢" if pnl > 0 else "🔴" if pnl < 0 else "⚪"
    
    lines = [
        f"{emoji} <b>US DAILY REPORT — {summary.get('date', '')}</b>",
        "",
        f"Trades: {summary.get('total_trades', 0)}",
        f"Closed: {summary.get('closed_trades', 0)}",
        f"Wins: {summary.get('wins', 0)} / Losses: {summary.get('losses', 0)}",
        f"Win Rate: {summary.get('win_rate', 0):.1f}%",
        "",
        f"Total P&L: ${pnl:+.2f}",
        f"Avg per Trade: ${summary.get('avg_pnl_per_trade', 0):+.2f}",
        f"Avg Win: ${summary.get('avg_win', 0):+.2f}",
        f"Avg Loss: ${summary.get('avg_loss', 0):+.2f}",
        "",
        f"Avg Duration: {summary.get('avg_duration_min', 0):.1f} min",
    ]
    
    return "\n".join(lines)


# ── Test ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Test logging
    log_trade("AAPL", "BUY", 10, 175.50, signal="vwap_reclaim", regime="TRENDING")
    
    # Test closing
    close_trade("AAPL", 180.00, "Target hit", regime="TRENDING")
    
    # Get summary
    summary = save_daily_summary()
    print(format_daily_report(summary))
    
    # Weekly
    weekly = get_weekly_summary()
    print(f"\nWeekly: {weekly}")
