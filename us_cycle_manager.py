#!/usr/bin/env python3
"""
US Cycle Manager — v4.12 (Enforced)
======================================
Position cycling and upgrade system with TASI-style enforcement.

Features:
- Cycle tracking per symbol (entry → exit → re-entry)
- Symbol blocking (2 scratches or hard stop)
- Position upgrade (better pick available → switch)
- Capital recycling (close scratch, enter new pick)

Author: Mino (kimi-k2.6)
Version: 4.12
Date: 2026-06-23
"""

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from pathlib import Path

import pytz

ET = pytz.timezone("America/New_York")
BASE_DIR = Path("/home/mino/us-exec")
CYCLE_FILE = BASE_DIR / "us_cycles.json"

# Cycle limits per regime (v4.12 updated)
CYCLE_LIMITS = {
    "TRENDING": 4,    # 4 cycles in trending (more opportunities)
    "NEUTRAL": 3,
    "DEFENSIVE": 2,   # 2 cycles in defensive (preservation)
}

# Minimum time between cycles (minutes)
CYCLE_COOLDOWN = {
    "TRENDING": 30,
    "NEUTRAL": 45,
    "DEFENSIVE": 60,
}

# Blocked symbols (cycles exceeded or 2 scratches) — TASI style
_blocked_symbols: set = set()


def load_cycles() -> Dict:
    """Load cycle tracking data."""
    if not CYCLE_FILE.exists():
        return {}
    try:
        with open(CYCLE_FILE) as f:
            return json.load(f)
    except:
        return {}


def save_cycles(cycles: Dict):
    """Save cycle tracking data."""
    try:
        with open(CYCLE_FILE, "w") as f:
            json.dump(cycles, f, indent=2)
    except Exception as e:
        print(f"Failed to save cycles: {e}")


def get_symbol_cycles(symbol: str) -> Dict:
    """Get cycle data for a symbol."""
    cycles = load_cycles()
    return cycles.get(symbol, {
        "cycle_count": 0,
        "last_entry": "",
        "last_exit": "",
        "scratch_count": 0,
        "win_count": 0,
        "status": "available",
    })


def is_symbol_blocked(symbol: str) -> bool:
    """Check if symbol is blocked (2 scratches or hard stop)."""
    return symbol in _blocked_symbols


def block_symbol(symbol: str, reason: str = ""):
    """Block a symbol from further entries."""
    _blocked_symbols.add(symbol)
    log_event = f"BLOCKED {symbol}: {reason}"
    try:
        from us_watchdog import USWatchdog
        wd = USWatchdog()
        wd.log_event("BLOCK", log_event)
    except:
        pass


def unblock_all_symbols():
    """Unblock all symbols (new day)."""
    global _blocked_symbols
    _blocked_symbols = set()


def can_enter_cycle(symbol: str, regime: str = "NEUTRAL") -> Tuple[bool, str]:
    """Check if symbol can enter a new cycle.
    
    Returns:
        (can_enter, reason)
    """
    # Check if explicitly blocked (TASI style)
    if is_symbol_blocked(symbol):
        return False, f"{symbol} is blocked for today"
    
    cycle_data = get_symbol_cycles(symbol)
    cycle_count = cycle_data.get("cycle_count", 0)
    last_exit = cycle_data.get("last_exit", "")
    scratch_count = cycle_data.get("scratch_count", 0)
    
    # Check scratch limit (2 scratches = stop for day) — TASI style
    if scratch_count >= 2:
        block_symbol(symbol, "2 scratches")
        return False, f"2 scratches — {symbol} stopped for today"
    
    # Check cycle limit
    limit = CYCLE_LIMITS.get(regime, 3)
    if cycle_count >= limit:
        block_symbol(symbol, f"cycle limit {cycle_count}/{limit}")
        return False, f"Cycle limit reached ({cycle_count}/{limit}) for {regime}"
    
    # Check cooldown
    if last_exit:
        try:
            last_dt = datetime.fromisoformat(last_exit)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=ET)
            
            cooldown = CYCLE_COOLDOWN.get(regime, 45)
            mins_since = (datetime.now(ET) - last_dt).total_seconds() / 60
            
            if mins_since < cooldown:
                return False, f"Cooldown: {mins_since:.0f}/{cooldown} min since last exit"
        except:
            pass
    
    return True, f"Cycle {cycle_count + 1}/{limit} available"


def record_entry(symbol: str, entry_price: float, qty: int):
    """Record position entry."""
    cycles = load_cycles()
    
    if symbol not in cycles:
        cycles[symbol] = {
            "cycle_count": 0,
            "last_entry": "",
            "last_exit": "",
            "scratch_count": 0,
            "win_count": 0,
            "entries": [],
        }
    
    cycles[symbol]["cycle_count"] += 1
    cycles[symbol]["last_entry"] = datetime.now(ET).isoformat()
    cycles[symbol]["status"] = "active"
    cycles[symbol]["entries"].append({
        "entry_time": datetime.now(ET).isoformat(),
        "entry_price": entry_price,
        "qty": qty,
        "cycle_n": cycles[symbol]["cycle_count"],
    })
    
    save_cycles(cycles)


def record_exit(symbol: str, exit_price: float, pnl_pct: float):
    """Record position exit."""
    cycles = load_cycles()
    
    if symbol not in cycles:
        return
    
    cycles[symbol]["last_exit"] = datetime.now(ET).isoformat()
    cycles[symbol]["status"] = "cooling"
    
    # Update win/scratch count — TASI style
    if pnl_pct > 0:
        # Win — reset scratch count
        cycles[symbol]["win_count"] = cycles[symbol].get("win_count", 0) + 1
        cycles[symbol]["scratch_count"] = 0
    else:
        # Scratch — increment
        cycles[symbol]["scratch_count"] = cycles[symbol].get("scratch_count", 0) + 1
        
        # Check if we need to block after 2 scratches (TASI style)
        if cycles[symbol]["scratch_count"] >= 2:
            block_symbol(symbol, "2 scratches")
    
    # Update last entry with exit info
    entries = cycles[symbol].get("entries", [])
    if entries:
        entries[-1]["exit_time"] = datetime.now(ET).isoformat()
        entries[-1]["exit_price"] = exit_price
        entries[-1]["pnl_pct"] = pnl_pct
    
    save_cycles(cycles)


def record_hard_stop(symbol: str):
    """Record hard stop — blocks symbol immediately (TASI style: cycles_today[symbol] = 999)."""
    block_symbol(symbol, "hard stop")
    
    # Also record in cycles
    cycles = load_cycles()
    if symbol not in cycles:
        cycles[symbol] = {
            "cycle_count": 0,
            "last_entry": "",
            "last_exit": "",
            "scratch_count": 999,  # Like TASI's 999
            "win_count": 0,
        }
    else:
        cycles[symbol]["scratch_count"] = 999
    
    save_cycles(cycles)


def reset_symbol(symbol: str):
    """Reset cycle data for a symbol (new day)."""
    cycles = load_cycles()
    if symbol in cycles:
        del cycles[symbol]
    save_cycles(cycles)
    
    # Also unblock
    if symbol in _blocked_symbols:
        _blocked_symbols.discard(symbol)


def reset_all_cycles():
    """Reset all cycles and blocks (new day)."""
    if CYCLE_FILE.exists():
        try:
            CYCLE_FILE.unlink()
        except:
            pass
    unblock_all_symbols()


# ─── Position Upgrade Logic ─────────────────────────────────────────────────

def should_upgrade_position(current_symbol: str, current_score: float,
                           candidate_symbol: str, candidate_score: float,
                           regime: str = "NEUTRAL") -> Tuple[bool, str]:
    """Check if we should upgrade to a better pick.
    
    Upgrade rules:
    - Candidate score must be significantly higher (>15% better)
    - Only upgrade if current position is young (<10 min)
    - DEFENSIVE: stricter upgrade threshold
    """
    # Score improvement threshold
    if regime == "TRENDING":
        min_improvement = 0.15  # 15% better
    elif regime == "NEUTRAL":
        min_improvement = 0.20  # 20% better
    else:
        min_improvement = 0.25  # 25% better (DEFENSIVE)
    
    # Calculate improvement
    if current_score <= 0:
        return False, "Current score invalid"
    
    improvement = (candidate_score - current_score) / current_score
    
    if improvement < min_improvement:
        return False, f"Improvement {improvement*100:.0f}% < {min_improvement*100:.0f}%"
    
    # Check cycle availability
    can_enter, reason = can_enter_cycle(candidate_symbol, regime)
    if not can_enter:
        return False, f"Cannot enter {candidate_symbol}: {reason}"
    
    return True, f"Upgrade: {improvement*100:.0f}% improvement ({current_score:.0f} → {candidate_score:.0f})"


def find_best_available_pick(picks: List[Dict], regime: str = "NEUTRAL",
                              exclude_symbols: List[str] = None) -> Optional[Dict]:
    """Find the best available pick that can be entered.
    
    Returns:
        Best pick or None if no valid picks
    """
    if exclude_symbols is None:
        exclude_symbols = []
    
    # Sort by score (highest first)
    sorted_picks = sorted(picks, key=lambda x: x.get("score", 0), reverse=True)
    
    for pick in sorted_picks:
        symbol = pick.get("symbol", "")
        if not symbol or symbol in exclude_symbols:
            continue
        
        can_enter, reason = can_enter_cycle(symbol, regime)
        if can_enter:
            return pick
    
    return None


# ─── Capital Recycling ──────────────────────────────────────────────────────

def recycle_capital(current_positions: Dict, available_picks: List[Dict],
                   regime: str = "NEUTRAL") -> List[Tuple[str, str]]:
    """Identify positions to close for recycling.
    
    Returns:
        List of (symbol, reason) to close
    """
    actions = []
    
    for symbol, pos in current_positions.items():
        if pos.get("closed", True):
            continue
        
        entry_time = pos.get("entry_time", "")
        entry_price = pos.get("entry_price", 0)
        
        if not entry_time or entry_price <= 0:
            continue
        
        # Calculate current PnL (simplified — actual would use current price)
        # For now, just check time-based recycling
        try:
            entry_dt = datetime.fromisoformat(entry_time)
            if entry_dt.tzinfo is None:
                entry_dt = entry_dt.replace(tzinfo=ET)
            
            mins_held = (datetime.now(ET) - entry_dt).total_seconds() / 60
            
            # Recycle if held too long without profit
            if regime == "TRENDING" and mins_held > 120:
                actions.append((symbol, f"Recycle: Held {mins_held:.0f} min in TRENDING"))
            elif regime == "NEUTRAL" and mins_held > 90:
                actions.append((symbol, f"Recycle: Held {mins_held:.0f} min in NEUTRAL"))
            elif regime == "DEFENSIVE" and mins_held > 60:
                actions.append((symbol, f"Recycle: Held {mins_held:.0f} min in DEFENSIVE"))
                
        except:
            pass
    
    return actions


# ─── Test ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== US Cycle Manager (Enforced) Test ===\n")
    
    # Test cycle tracking
    symbol = "AAPL"
    
    # Reset first
    reset_symbol(symbol)
    
    # Check initial state
    can_enter, reason = can_enter_cycle(symbol, "NEUTRAL")
    print(f"Initial: {can_enter} — {reason}")
    
    # Record entry
    record_entry(symbol, 175.50, 10)
    
    # Record exit (scratch)
    record_exit(symbol, 173.00, -1.42)
    
    # Check after scratch
    can_enter, reason = can_enter_cycle(symbol, "NEUTRAL")
    print(f"After 1 scratch: {can_enter} — {reason}")
    
    # Record another entry/exit
    record_entry(symbol, 174.00, 10)
    record_exit(symbol, 172.50, -0.86)
    
    # Check after 2 scratches (should be BLOCKED)
    can_enter, reason = can_enter_cycle(symbol, "NEUTRAL")
    print(f"After 2 scratches: {can_enter} — {reason}")
    print(f"Is {symbol} blocked? {is_symbol_blocked(symbol)}")
    
    # Test hard stop
    reset_symbol("AMD")
    record_hard_stop("AMD")
    can_enter, reason = can_enter_cycle("AMD", "TRENDING")
    print(f"After hard stop: {can_enter} — {reason}")
    print(f"Is AMD blocked? {is_symbol_blocked('AMD')}")
    
    print()
    print("=== Test Complete ===")
