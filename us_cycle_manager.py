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


# ─── Position Upgrade Thresholds (TASI v4.9 style) ────────────────────────

POSITION_UPGRADE_THRESHOLDS = {
    "TRENDING":  1.4,  # 40% better - stick with strong momentum
    "NEUTRAL":   1.3,  # 30% better - balanced
    "DEFENSIVE": 1.2,  # 20% better - cut losers faster
}


def _calculate_drop_score(symbol: str, pos: Dict, price: float, df,
                         regime_params: Dict, picks_all: List[Dict]) -> float:
    """Calculate drop score — lower = weaker position, candidate for upgrade.
    
    Components:
    - PnL (30%): Current gain/loss
    - Recovery (25%): Candle recovery score
    - Profit rate (20%): Progress toward target vs time held
    - Momentum (15%): Score vs best available picks
    - Liquidity (10%): Current volume vs average
    """
    entry = pos.get("entry_price", 0)
    entry_time = pos.get("entry_time", "")
    
    # PnL component (30%)
    if entry and price and entry > 0:
        pnl_pct = (price - entry) / entry
        pnl_score = 50 + pnl_pct * 1000  # 0% = 50, +5% = 100, -5% = 0
        pnl_score = max(0, min(100, pnl_score))
    else:
        pnl_score = 50
    
    # Recovery component (25%)
    recovery_score = 50  # default neutral
    if df is not None and len(df) >= 10:
        try:
            recent = df.tail(10)
            closes = []
            for i in range(len(recent)):
                c = recent["Close"].iloc[i]
                if hasattr(c, 'iloc'):
                    c = float(c.iloc[0])
                else:
                    c = float(c)
                closes.append(c)
            
            rising = sum(1 for i in range(1, len(closes)) if closes[i] > closes[i-1])
            recovery_prob = rising / (len(closes) - 1) if len(closes) > 1 else 0.5
            recovery_score = recovery_prob * 100
        except:
            pass
    
    # Profit rate component (20%)
    target_pct = regime_params.get("target_pct", 0.02)
    if entry_time and entry and price:
        try:
            et = datetime.fromisoformat(entry_time)
            if et.tzinfo is None:
                et = et.replace(tzinfo=ET)
            mins_held = (datetime.now(ET) - et).total_seconds() / 60
            pnl_pct = (price - entry) / entry
            progress = pnl_pct / target_pct if target_pct else 0
            time_efficiency = progress / max(mins_held / 60, 0.5)
            profit_rate_score = max(0, min(100, 50 + time_efficiency * 50))
        except:
            profit_rate_score = 50
    else:
        profit_rate_score = 50
    
    # Momentum component (15%)
    current_pick = next((p for p in picks_all if p.get("symbol", "").replace(".SR", "") == symbol.replace(".SR", "")), None)
    current_score = current_pick.get("score", 0) if current_pick else 0
    best_score = max((p.get("score", 0) for p in picks_all), default=current_score)
    momentum_score = (current_score / max(best_score, 1)) * 100
    
    # Liquidity component (10%) — simplified for US
    liquidity_score = 50  # default
    if df is not None and len(df) >= 2:
        try:
            avg_vol = float(df["Volume"].mean())
            last_vol = float(df["Volume"].iloc[-1])
            if hasattr(last_vol, 'iloc'):
                last_vol = float(last_vol.iloc[0])
            liq_ratio = last_vol / avg_vol if avg_vol > 0 else 1.0
            liquidity_score = min(100, liq_ratio * 50)
        except:
            pass
    
    # Weighted composite
    drop_score = (
        pnl_score * 0.30 +
        recovery_score * 0.25 +
        profit_rate_score * 0.20 +
        momentum_score * 0.15 +
        liquidity_score * 0.10
    )
    
    return drop_score


def _calculate_upgrade_qty(symbol: str, price: float, capital: Dict,
                            position_pct: float) -> int:
    """Calculate qty for upgrade based on position_pct of total capital.
    
    Validates against available cash.
    """
    total_capital = capital.get("grand_total", capital.get("available_capital", 0))
    available = capital.get("money_transfer", capital.get("available_capital", 0))
    
    if total_capital <= 0 or price <= 0:
        return 1
    
    target_value = total_capital * position_pct
    qty = max(1, int(target_value / price))
    
    # Validate against available cash (95% buffer)
    order_value = qty * price
    if order_value > available * 0.95:
        qty = max(1, int((available * 0.95) / price))
    
    return qty


# ─── Position Upgrade Logic ─────────────────────────────────────────────────

def should_upgrade_position(current_symbol: str, current_score: float,
                           candidate_symbol: str, candidate_score: float,
                           regime: str = "NEUTRAL",
                           current_price: Optional[float] = None,
                           entry_price: Optional[float] = None) -> Tuple[bool, str, Dict]:
    """Check if we should upgrade to a better pick (TASI v4.9 style).
    
    Returns:
        (should_upgrade, reason, details)
    """
    details = {}
    
    # Get regime-aware threshold
    pu_thresh = POSITION_UPGRADE_THRESHOLDS.get(regime, 1.3)
    
    # Check if candidate is significantly better
    if current_score <= 0:
        return False, "Current score invalid", details
    
    improvement = candidate_score / current_score
    
    if improvement < pu_thresh:
        return False, f"Improvement {improvement:.1f}x < {pu_thresh}x threshold", details
    
    # Check if current position is NOT deep underwater
    if current_price and entry_price and entry_price > 0:
        gain_pct = (current_price - entry_price) / entry_price
        if gain_pct < -0.02:  # Don't switch if down >2%
            return False, f"Current position underwater {gain_pct*100:.1f}% (threshold: -2%)", details
        details["current_gain_pct"] = gain_pct
    
    # Check cycle availability for candidate
    can_enter, reason = can_enter_cycle(candidate_symbol, regime)
    if not can_enter:
        return False, f"Cannot enter {candidate_symbol}: {reason}", details
    
    details["improvement"] = improvement
    details["threshold"] = pu_thresh
    
    return True, f"Upgrade: {improvement:.1f}x improvement ({current_score:.0f} → {candidate_score:.0f})", details


def evaluate_position_upgrade(positions: Dict, picks: List[Dict],
                               regime: str = "NEUTRAL", regime_params: Dict = None) -> Optional[Dict]:
    """Evaluate if any position should be upgraded.
    
    Returns upgrade plan or None if no upgrade needed.
    """
    if regime_params is None:
        regime_params = {}
    
    # Get open positions
    open_positions = [(s, p) for s, p in positions.items() if not p.get("closed", True)]
    if not open_positions:
        return None
    
    # Calculate drop score for each open position
    scored_positions = []
    for sym, pos in open_positions:
        # Simplified: we don't have df here, use basic metrics
        entry = pos.get("entry_price", 0)
        # Use a simplified drop score based on time held
        entry_time = pos.get("entry_time", "")
        if entry_time:
            try:
                et = datetime.fromisoformat(entry_time)
                if et.tzinfo is None:
                    et = et.replace(tzinfo=ET)
                mins_held = (datetime.now(ET) - et).total_seconds() / 60
                # Simple drop score: older = higher drop score (weaker)
                drop_score = mins_held / 10  # Simple linear
            except:
                drop_score = 50
        else:
            drop_score = 50
        
        scored_positions.append((sym, pos, drop_score))
    
    # Sort by drop score (weakest first)
    scored_positions.sort(key=lambda x: x[2])
    
    # Get weakest position
    if not scored_positions:
        return None
    
    current_sym, current_pos, drop_score = scored_positions[0]
    
    # Find best available pick that's NOT currently held
    held_symbols = [s for s, _ in open_positions]
    best_new = None
    for p in sorted(picks, key=lambda x: x.get("score", 0), reverse=True):
        sym = p.get("symbol", "").replace(".SR", "").replace("-", ".")
        if sym not in held_symbols:
            best_new = p
            break
    
    if not best_new:
        return None
    
    # Get scores
    current_pick = next((p for p in picks if p.get("symbol", "").replace(".SR", "").replace("-", ".") == current_sym.replace(".SR", "").replace("-", ".")), None)
    current_score = current_pick.get("score", 0) if current_pick else 0
    candidate_score = best_new.get("score", 0)
    candidate_sym = best_new.get("symbol", "").replace(".SR", "").replace("-", ".")
    
    # Check upgrade
    current_price = current_pos.get("current_price") or current_pos.get("entry_price", 0)
    entry_price = current_pos.get("entry_price", 0)
    
    should_upgrade, reason, details = should_upgrade_position(
        current_sym, current_score, candidate_sym, candidate_score,
        regime, current_price, entry_price
    )
    
    if not should_upgrade:
        return None
    
    return {
        "current_symbol": current_sym,
        "current_pos": current_pos,
        "new_symbol": candidate_sym,
        "new_pick": best_new,
        "reason": reason,
        "details": details,
    }


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
