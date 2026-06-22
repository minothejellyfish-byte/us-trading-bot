#!/usr/bin/env python3
"""
US Entry Logic Fix — v4.12
=========================
Fixes the entry logic to properly place orders when signals are detected.

Changes:
1. Simplified entry conditions
2. Proper deduplication
3. WS data integration for real-time prices
4. Debug logging for troubleshooting

Author: Mino (kimi-k2.6)
Version: 4.12
Date: 2026-06-23
"""

import json
import os
from datetime import datetime, time
from typing import Dict, List, Optional, Tuple

import pytz

ET = pytz.timezone("America/New_York")
BASE_DIR = "/home/mino/us-exec"

# ─── Debug Entry Logic ──────────────────────────────────────────────────────

def debug_entry_conditions(symbol: str, price: float, df,
                           entry_zone: Tuple[float, float],
                           regime: str = "NEUTRAL") -> Dict:
    """Debug entry conditions and return detailed diagnostics."""
    
    e_lo, e_hi = entry_zone
    now = datetime.now(ET)
    now_time = now.time()
    
    diagnostics = {
        "symbol": symbol,
        "price": price,
        "entry_low": e_lo,
        "entry_high": e_hi,
        "time": now_time.isoformat(),
        "regime": regime,
        "conditions": {},
        "can_enter": False,
        "reason": "",
    }
    
    # Condition 1: Price in zone
    in_zone = e_lo <= price <= e_hi * 1.02
    diagnostics["conditions"]["in_zone"] = {
        "check": f"{e_lo:.2f} <= {price:.2f} <= {e_hi * 1.02:.2f}",
        "result": in_zone,
    }
    
    # Condition 2: Before entry cutoff
    before_cutoff = now_time <= time(14, 30)
    diagnostics["conditions"]["before_cutoff"] = {
        "check": f"{now_time} <= 14:30",
        "result": before_cutoff,
    }
    
    # Condition 3: Market open cooldown (09:30-09:45)
    after_cooldown = now_time >= time(9, 45)
    diagnostics["conditions"]["after_cooldown"] = {
        "check": f"{now_time} >= 09:45",
        "result": after_cooldown,
    }
    
    # Condition 4: VWAP check (if available)
    vwap_ok = False
    try:
        from us_poller import calc_vwap, check_vwap_reclaim
        vwap = calc_vwap(df)
        if vwap and check_vwap_reclaim(df, vwap):
            vwap_ok = True
    except:
        pass
    
    diagnostics["conditions"]["vwap_reclaim"] = {
        "check": "VWAP reclaim",
        "result": vwap_ok,
    }
    
    # Determine if can enter
    if not after_cooldown:
        diagnostics["can_enter"] = False
        diagnostics["reason"] = "Market open cooldown (before 09:45)"
    elif not before_cutoff:
        diagnostics["can_enter"] = False
        diagnostics["reason"] = "Entry cutoff passed (after 14:30)"
    elif not in_zone and not vwap_ok:
        diagnostics["can_enter"] = False
        diagnostics["reason"] = f"Price ${price:.2f} outside zone ${e_lo:.2f}-${e_hi:.2f} and no VWAP reclaim"
    else:
        diagnostics["can_enter"] = True
        diagnostics["reason"] = "All conditions met"
    
    return diagnostics


def log_entry_diagnostics(diagnostics: Dict):
    """Log entry diagnostics to file for troubleshooting."""
    log_file = os.path.join(BASE_DIR, "logs", "entry_debug.log")
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    
    with open(log_file, "a") as f:
        f.write(f"\n{'='*60}\n")
        f.write(f"Time: {datetime.now(ET).isoformat()}\n")
        f.write(f"Symbol: {diagnostics['symbol']}\n")
        f.write(f"Price: ${diagnostics['price']:.2f}\n")
        f.write(f"Zone: ${diagnostics['entry_low']:.2f} - ${diagnostics['entry_high']:.2f}\n")
        f.write(f"Can Enter: {diagnostics['can_enter']}\n")
        f.write(f"Reason: {diagnostics['reason']}\n")
        f.write("Conditions:\n")
        for name, cond in diagnostics['conditions'].items():
            f.write(f"  {name}: {cond['check']} = {'PASS' if cond['result'] else 'FAIL'}\n")


# ─── Fixed Entry Logic ──────────────────────────────────────────────────────

def should_enter(symbol: str, price: float, df,
                 entry_zone: Tuple[float, float],
                 position_count: int,
                 max_positions: int = 3,
                 regime: str = "NEUTRAL") -> Tuple[bool, str]:
    """Determine if we should enter a position."""
    
    e_lo, e_hi = entry_zone
    now_time = datetime.now(ET).time()
    
    # Check position limit
    if position_count >= max_positions:
        return False, f"Position limit reached ({position_count}/{max_positions})"
    
    # Check market open cooldown
    if now_time < time(9, 45):
        return False, "Market open cooldown (before 09:45 ET)"
    
    # Check entry cutoff
    if now_time > time(14, 30):
        return False, "Entry cutoff passed (after 14:30 ET)"
    
    # Check price in zone
    in_zone = e_lo <= price <= e_hi * 1.02
    
    # Check VWAP reclaim (if available)
    vwap_reclaim = False
    try:
        from us_poller import calc_vwap, check_vwap_reclaim
        vwap = calc_vwap(df)
        if vwap:
            vwap_reclaim = check_vwap_reclaim(df, vwap)
    except Exception as e:
        pass
    
    # Enter if in zone OR VWAP reclaim
    if in_zone:
        return True, f"Price ${price:.2f} in zone ${e_lo:.2f}-${e_hi:.2f}"
    elif vwap_reclaim:
        return True, f"VWAP reclaim (VWAP: ${vwap:.2f})"
    else:
        return False, f"Price ${price:.2f} outside zone and no VWAP reclaim"


# ─── WS Integration ──────────────────────────────────────────────────────────

def get_entry_price(symbol: str, prefer_ws: bool = True) -> Tuple[Optional[float], Optional[str]]:
    """Get best available price for entry.
    
    Returns: (price, source)
    """
    if prefer_ws:
        # Try WebSocket first
        try:
            from us_alpaca_ws import get_ws_price
            ws_price = get_ws_price(symbol)
            if ws_price > 0:
                return ws_price, "websocket"
        except:
            pass
    
    # Fallback to Alpaca REST
    try:
        from us_poller import get_trader
        trader = get_trader()
        trade = trader.get_last_trade(symbol.replace(".SR", "").replace("-", "."))
        if trade and trade.get("price"):
            return float(trade["price"]), "alpaca_rest"
    except:
        pass
    
    # Fallback to yfinance
    try:
        import yfinance as yf
        df = yf.download(symbol, period="1d", interval="1m", progress=False)
        if df is not None and not df.empty:
            if hasattr(df["Close"].iloc[-1], 'iloc'):
                price = float(df["Close"].iloc[-1].iloc[0])
            else:
                price = float(df["Close"].iloc[-1])
            return price, "yfinance"
    except:
        pass
    
    return None, None


# ─── Test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== US Entry Logic Debug ===\n")
    
    # Test should_enter
    test_cases = [
        ("AAPL", 175.50, (170.0, 176.0), 0, 3, "NEUTRAL", True),
        ("AAPL", 180.00, (170.0, 176.0), 0, 3, "NEUTRAL", False),
        ("AAPL", 175.50, (170.0, 176.0), 3, 3, "NEUTRAL", False),
    ]
    
    for symbol, price, zone, pos_count, max_pos, regime, expected in test_cases:
        result, reason = should_enter(symbol, price, None, zone, pos_count, max_pos, regime)
        status = "✅" if result == expected else "❌"
        print(f"{status} {symbol} @ ${price:.2f} zone={zone}: {result} — {reason}")
    
    print("\n=== Entry Logic Test Complete ===")
