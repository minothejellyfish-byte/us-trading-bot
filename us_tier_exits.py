#!/usr/bin/env python3
"""
US Tiered Exit Triggers — v4.12
=================================
Tiered position reduction system for US paper trading.

Unlike TASI's strict tier system, US paper uses softer tiers to learn:
- Tier 1 (mild drawdown): Reduce 25% (was 30% in TASI)
- Tier 2 (moderate drawdown): Reduce 50% (was 60% in TASI)
- Tier 3 (severe drawdown): Full exit (same as TASI)

Author: Mino (kimi-k2.6)
Version: 4.12
Date: 2026-06-23
"""

import json
import os
from datetime import datetime
from typing import Dict, Tuple, Optional
from pathlib import Path

import pytz

ET = pytz.timezone("America/New_York")
BASE_DIR = Path("/home/mino/us-exec")

# ─── Tier Configuration ─────────────────────────────────────────────────────

# Paper trading — softer than TASI
TIER_CONFIG = {
    "TRENDING": {
        "tier1": {"drawdown": 0.025, "reduce": 0.25},  # -2.5% → reduce 25%
        "tier2": {"drawdown": 0.05, "reduce": 0.50},     # -5.0% → reduce 50%
        "tier3": {"drawdown": 0.10, "reduce": 1.00},     # -10.0% → full exit
    },
    "NEUTRAL": {
        "tier1": {"drawdown": 0.020, "reduce": 0.25},   # -2.0% → reduce 25%
        "tier2": {"drawdown": 0.04, "reduce": 0.50},     # -4.0% → reduce 50%
        "tier3": {"drawdown": 0.08, "reduce": 1.00},     # -8.0% → full exit
    },
    "DEFENSIVE": {
        "tier1": {"drawdown": 0.015, "reduce": 0.25},  # -1.5% → reduce 25%
        "tier2": {"drawdown": 0.03, "reduce": 0.50},     # -3.0% → reduce 50%
        "tier3": {"drawdown": 0.06, "reduce": 1.00},     # -6.0% → full exit
    },
}

# Track which tiers have been triggered
_tier_triggered: Dict[str, set] = {}  # symbol -> set of triggered tiers


def get_tier_config(regime: str = "NEUTRAL") -> Dict:
    """Get tier configuration for a regime."""
    return TIER_CONFIG.get(regime, TIER_CONFIG["NEUTRAL"])


def check_tier_exit(symbol: str, entry_price: float, current_price: float,
                   regime: str = "NEUTRAL", current_qty: int = 0) -> Tuple[Optional[int], str]:
    """Check if a tier exit should trigger.
    
    Args:
        symbol: Stock symbol
        entry_price: Entry price
        current_price: Current price
        regime: Market regime
        current_qty: Current position quantity
    
    Returns:
        (qty_to_sell, reason) or (None, "") if no action needed
    """
    if entry_price <= 0 or current_price <= 0 or current_qty <= 0:
        return None, "Invalid parameters"
    
    drawdown = (current_price - entry_price) / entry_price
    if drawdown >= 0:
        return None, "In profit, no tier exit needed"
    
    config = get_tier_config(regime)
    
    # Get triggered tiers for this symbol
    triggered = _tier_triggered.get(symbol, set())
    
    # Check tiers in order (3 → 2 → 1)
    for tier_name in ["tier3", "tier2", "tier1"]:
        if tier_name in triggered:
            continue  # Already triggered this tier
        
        tier = config[tier_name]
        if abs(drawdown) >= tier["drawdown"]:
            # Calculate qty to sell
            reduce_pct = tier["reduce"]
            qty_to_sell = int(current_qty * reduce_pct)
            
            if qty_to_sell <= 0:
                continue
            
            # Mark tier as triggered
            if symbol not in _tier_triggered:
                _tier_triggered[symbol] = set()
            _tier_triggered[symbol].add(tier_name)
            
            remaining = current_qty - qty_to_sell
            reason = (f"Tier {tier_name[-1]} exit: {drawdown*100:.1f}% drawdown "
                     f"(>= {tier['drawdown']*100:.1f}%) — "
                     f"selling {qty_to_sell}/{current_qty} ({reduce_pct*100:.0f}%), "
                     f"remaining: {remaining}")
            
            return qty_to_sell, reason
    
    return None, f"Drawdown: {drawdown*100:.1f}% — no tier triggered"


def reset_tier_tracking(symbol: str):
    """Reset tier tracking for a symbol (call on new entry)."""
    if symbol in _tier_triggered:
        del _tier_triggered[symbol]


def get_tier_status(symbol: str) -> Dict:
    """Get current tier status for a symbol."""
    triggered = _tier_triggered.get(symbol, set())
    return {
        "symbol": symbol,
        "triggered_tiers": list(triggered),
        "tiers_remaining": 3 - len(triggered),
    }


# ─── Integration with Bookkeeper ──────────────────────────────────────────

def execute_tier_exit(symbol: str, entry_price: float, current_price: float,
                     regime: str = "NEUTRAL") -> Tuple[bool, str]:
    """Execute tier exit with bookkeeper confirmation.
    
    Returns:
        (executed, reason)
    """
    try:
        from us_bookkeeper import get_positions
        positions = get_positions()
        pos = positions.get(symbol, {})
        
        if not pos or pos.get("closed", True):
            return False, "No open position in bookkeeper"
        
        current_qty = pos.get("qty", 0)
        if current_qty <= 0:
            return False, "Invalid quantity in bookkeeper"
        
        qty_to_sell, reason = check_tier_exit(symbol, entry_price, current_price,
                                               regime, current_qty)
        
        if qty_to_sell is None:
            return False, reason
        
        # Execute the sale
        from us_poller import auto_sell
        result = auto_sell(symbol, qty_to_sell, reason)
        
        if result:
            # Update bookkeeper
            from us_bookkeeper import close_position
            close_position(symbol, current_price, f"tier_exit_{reason}")
            return True, reason
        else:
            return False, "auto_sell failed"
            
    except Exception as e:
        return False, f"Error: {e}"


# ─── Test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== US Tiered Exit Triggers Test ===\n")
    
    # Test NEUTRAL regime
    print("NEUTRAL Regime Tiers:")
    config = get_tier_config("NEUTRAL")
    for tier, vals in config.items():
        print(f"  {tier}: -{vals['drawdown']*100:.1f}% → reduce {vals['reduce']*100:.0f}%")
    
    print("\nTest Cases:")
    test_cases = [
        ("AAPL", 100, 98.5, "NEUTRAL", 100, None, "No tier triggered (-1.5%)"),
        ("AAPL", 100, 97.5, "NEUTRAL", 100, 25, "Tier 1: -2.5%"),
        ("AAPL", 100, 95.0, "NEUTRAL", 100, 50, "Tier 2: -5.0%"),
        ("AAPL", 100, 90.0, "NEUTRAL", 100, 100, "Tier 3: -10.0%"),
    ]
    
    for symbol, entry, current, regime, qty, expected_qty, desc in test_cases:
        reset_tier_tracking(symbol)
        qty_to_sell, reason = check_tier_exit(symbol, entry, current, regime, qty)
        status = "✅" if qty_to_sell == expected_qty else "❌"
        print(f"  {status} {desc}: sell {qty_to_sell} — {reason}")
    
    print("\n=== Test Complete ===")
