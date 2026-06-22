#!/usr/bin/env python3
"""
US Dynamic Time Stops — v4.12
================================
Regime-aware time stop system for US paper trading.

TRENDING: No time stop (let trends run)
NEUTRAL: Time stop based on entry time
DEFENSIVE: Earlier time stop, tighter loss threshold

Author: Mino (kimi-k2.6)
Version: 4.12
Date: 2026-06-23
"""

from datetime import datetime, time, timedelta
from typing import Tuple, Dict
import pytz

ET = pytz.timezone("America/New_York")


def get_time_stop(entry_time: str, regime: str = "NEUTRAL") -> Tuple[int, float, str]:
    """Calculate dynamic time stop based on entry time and regime.
    
    Args:
        entry_time: ISO format entry time
        regime: TRENDING / NEUTRAL / DEFENSIVE
    
    Returns:
        (max_hold_minutes, loss_threshold_pct, reason)
    """
    try:
        entry_dt = datetime.fromisoformat(entry_time)
        if entry_dt.tzinfo is None:
            entry_dt = entry_dt.replace(tzinfo=ET)
        entry_hour = entry_dt.hour
        entry_min = entry_dt.minute
    except:
        # Default if parsing fails
        return 30, -0.01, "Default time stop (parse error)"
    
    if regime == "TRENDING":
        # TRENDING: No hard time stop, but soft check at 14:30
        # Let trends run to hard close
        max_hold = 180  # 3 hours max (up to 15:45)
        loss_thresh = -0.02  # -2% loss threshold (softer)
        reason = "TRENDING: No hard time stop, max 3 hours"
        
    elif regime == "NEUTRAL":
        # NEUTRAL: Time-based exit windows
        # Early entry (before 11:00) → exit by 14:30
        # Mid entry (11:00-13:00) → exit by 14:30  
        # Late entry (after 13:00) → exit after 45 min
        if entry_hour < 11:
            max_hold = 210  # 3.5 hours
            loss_thresh = -0.015  # -1.5%
            reason = "NEUTRAL: Early entry → exit by 14:30"
        elif entry_hour < 13:
            max_hold = 120  # 2 hours
            loss_thresh = -0.01  # -1%
            reason = "NEUTRAL: Mid entry → exit after 2 hours"
        else:
            max_hold = 45  # 45 minutes
            loss_thresh = -0.005  # -0.5%
            reason = "NEUTRAL: Late entry → exit after 45 min"
            
    else:  # DEFENSIVE
        # DEFENSIVE: Tight time stops
        # Early entry → exit by 13:00
        # Mid entry → exit after 60 min
        # Late entry → exit after 30 min
        if entry_hour < 11:
            max_hold = 120  # 2 hours
            loss_thresh = -0.01  # -1%
            reason = "DEFENSIVE: Early entry → exit by 13:00"
        elif entry_hour < 13:
            max_hold = 60  # 1 hour
            loss_thresh = -0.005  # -0.5%
            reason = "DEFENSIVE: Mid entry → exit after 1 hour"
        else:
            max_hold = 30  # 30 minutes
            loss_thresh = -0.003  # -0.3%
            reason = "DEFENSIVE: Late entry → exit after 30 min"
    
    return max_hold, loss_thresh, reason


def check_time_stop(entry_time: str, regime: str = "NEUTRAL",
                   current_time: datetime = None,
                   gain_pct: float = 0) -> Tuple[bool, str]:
    """Check if time stop should trigger.
    
    Returns:
        (should_exit, reason)
    """
    max_hold, loss_thresh, reason = get_time_stop(entry_time, regime)
    
    if current_time is None:
        current_time = datetime.now(ET)
    
    try:
        entry_dt = datetime.fromisoformat(entry_time)
        if entry_dt.tzinfo is None:
            entry_dt = entry_dt.replace(tzinfo=ET)
    except:
        return False, "Failed to parse entry time"
    
    # Calculate minutes held
    mins_held = (current_time - entry_dt).total_seconds() / 60
    
    # Check if time exceeded
    if mins_held >= max_hold:
        return True, f"Time stop: held {mins_held:.0f} min (>= {max_hold} min) | {reason}"
    
    # Check if loss threshold exceeded
    if gain_pct <= loss_thresh:
        return True, f"Time stop loss: {gain_pct*100:.1f}% (<= {loss_thresh*100:.1f}%) | {reason}"
    
    return False, f"Held {mins_held:.0f} min (< {max_hold}) | {reason}"


# ─── Test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== Dynamic Time Stops Test ===\n")
    
    # Test different entry times and regimes
    test_cases = [
        ("TRENDING", "09:45", 0.5),
        ("TRENDING", "13:00", 0.5),
        ("NEUTRAL", "09:45", -0.5),
        ("NEUTRAL", "12:00", 0.0),
        ("NEUTRAL", "14:00", 0.0),
        ("DEFENSIVE", "09:45", -0.2),
        ("DEFENSIVE", "12:00", -0.1),
        ("DEFENSIVE", "14:00", 0.0),
    ]
    
    for regime, entry_time_str, gain in test_cases:
        # Create ISO timestamp
        now = datetime.now(ET)
        parts = entry_time_str.split(":")
        entry_dt = now.replace(hour=int(parts[0]), minute=int(parts[1]), second=0)
        entry_iso = entry_dt.isoformat()
        
        # Check time stop
        max_hold, loss_thresh, reason = get_time_stop(entry_iso, regime)
        should_exit, msg = check_time_stop(entry_iso, regime, now, gain)
        
        status = "🛑 EXIT" if should_exit else "⏱ HOLD"
        print(f"{status} {regime} entry {entry_time_str} gain={gain*100:.1f}%")
        print(f"  Max hold: {max_hold} min | Loss thresh: {loss_thresh*100:.1f}%")
        print(f"  {msg}")
        print()
    
    print("=== Test Complete ===")
