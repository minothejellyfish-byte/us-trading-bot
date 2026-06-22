#!/usr/bin/env python3
"""
US Exit Triggers Fix — v4.12
==============================
Adds missing exit triggers to US poller:
1. Trailing stop
2. VWAP breakdown exit
3. Recovery score (1-min)

Author: Mino (kimi-k2.6)
Version: 4.12
Date: 2026-06-23
"""

import json
import os
from datetime import datetime, time, timedelta
from typing import Dict, Tuple, Optional
from pathlib import Path

import pytz
import pandas as pd

ET = pytz.timezone("America/New_York")
BASE_DIR = Path("/home/mino/us-exec")

# ─── Trailing Stop ──────────────────────────────────────────────────────────

def check_trailing_stop(entry_price: float, peak_price: float, 
                        current_price: float, trail_pct: float = 0.03) -> Tuple[bool, str]:
    """Check if trailing stop should trigger.
    
    Args:
        entry_price: Entry price
        peak_price: Highest price since entry
        current_price: Current price
        trail_pct: Trailing percentage (default 3%)
    
    Returns:
        (should_exit, reason)
    """
    if peak_price <= 0 or current_price <= 0:
        return False, "Invalid prices"
    
    # Calculate drop from peak
    drop_from_peak = (peak_price - current_price) / peak_price
    
    # Only activate trailing stop if we're in profit
    if peak_price <= entry_price:
        return False, f"Not in profit yet (peak ${peak_price:.2f} <= entry ${entry_price:.2f})"
    
    # Check if drop exceeds trail percentage
    if drop_from_peak >= trail_pct:
        return True, f"Trailing stop: dropped {drop_from_peak*100:.1f}% from peak ${peak_price:.2f} (limit: {trail_pct*100:.1f}%)"
    
    return False, f"Drop from peak: {drop_from_peak*100:.1f}% (limit: {trail_pct*100:.1f}%)"


# ─── VWAP Breakdown Exit ──────────────────────────────────────────────────

def check_vwap_breakdown(df: pd.DataFrame, vwap: float, 
                         bars_required: int = 3) -> Tuple[bool, str]:
    """Check if price has broken down below VWAP for multiple bars.
    
    Args:
        df: DataFrame with OHLCV data
        vwap: VWAP value
        bars_required: Number of consecutive bars below VWAP (default 3)
    
    Returns:
        (should_exit, reason)
    """
    if df is None or df.empty or vwap is None or vwap <= 0:
        return False, "No data"
    
    if len(df) < bars_required:
        return False, f"Insufficient data ({len(df)} bars, need {bars_required})"
    
    # Check last N bars
    last_bars = df.tail(bars_required)
    closes = []
    
    for idx in range(len(last_bars)):
        try:
            close = float(last_bars["Close"].iloc[idx])
            if hasattr(close, 'iloc'):
                close = float(close.iloc[0])
            closes.append(close)
        except:
            return False, "Error extracting close prices"
    
    # Check if all closes are below VWAP
    below_count = sum(1 for c in closes if c < vwap)
    
    if below_count >= bars_required:
        return True, f"VWAP breakdown: {below_count} bars below VWAP ${vwap:.2f}"
    
    return False, f"{below_count}/{bars_required} bars below VWAP"


# ─── Recovery Score (1-min) ────────────────────────────────────────────────

def calc_recovery_score(df: pd.DataFrame, lookback: int = 5) -> Tuple[float, str]:
    """Calculate recovery score based on recent price action.
    
    Returns score 0-100 where:
    - 0-30: Strong downtrend (consider exit)
    - 30-70: Neutral/choppy
    - 70-100: Recovery/uptrend
    
    Args:
        df: DataFrame with OHLCV data
        lookback: Number of bars to look back (default 5)
    
    Returns:
        (score, description)
    """
    if df is None or len(df) < lookback:
        return 50, "Insufficient data"
    
    try:
        closes = []
        for i in range(lookback):
            close = df["Close"].iloc[-(i+1)]
            if hasattr(close, 'iloc'):
                close = float(close.iloc[0])
            else:
                close = float(close)
            closes.append(close)
        
        # Calculate momentum (slope of last N closes)
        if len(closes) >= 3:
            recent = closes[:3]  # Most recent 3
            older = closes[-3:]   # Older 3
            
            avg_recent = sum(recent) / len(recent)
            avg_older = sum(older) / len(older)
            
            if avg_older > 0:
                momentum = (avg_recent - avg_older) / avg_older * 100
            else:
                momentum = 0
            
            # Convert momentum to score (-5% to +5% maps to 0-100)
            score = 50 + (momentum * 10)  # 1% = 10 points
            score = max(0, min(100, score))  # Clamp to 0-100
            
            if score < 30:
                desc = f"Strong downtrend ({momentum:+.2f}%)"
            elif score < 45:
                desc = f"Weak recovery ({momentum:+.2f}%)"
            elif score < 55:
                desc = f"Neutral ({momentum:+.2f}%)"
            elif score < 70:
                desc = f"Moderate uptrend ({momentum:+.2f}%)"
            else:
                desc = f"Strong uptrend ({momentum:+.2f}%)"
            
            return score, desc
        
        return 50, "Insufficient bars"
        
    except Exception as e:
        return 50, f"Error: {e}"


# ─── Exit Decision Engine ──────────────────────────────────────────────────

class ExitDecision:
    """Combines multiple exit signals into a decision."""
    
    def __init__(self, symbol: str, entry_price: float, peak_price: float,
                 current_price: float, df: pd.DataFrame = None,
                 vwap: float = None, regime: str = "NEUTRAL"):
        self.symbol = symbol
        self.entry_price = entry_price
        self.peak_price = peak_price
        self.current_price = current_price
        self.df = df
        self.vwap = vwap
        self.regime = regime
        self.signals = []
        self.should_exit = False
        self.reason = ""
        
    def check_all(self) -> Tuple[bool, str]:
        """Check all exit conditions and return decision."""
        
        # 1. Hard stop (always check)
        gain_pct = (self.current_price - self.entry_price) / self.entry_price
        hard_stop_pct = self._get_hard_stop_pct()
        
        if gain_pct <= -hard_stop_pct:
            self.signals.append(f"Hard stop: {gain_pct*100:.1f}% (<= -{hard_stop_pct*100:.1f}%)")
            self.should_exit = True
            self.reason = f"Hard stop triggered: {gain_pct*100:.1f}% loss"
            return True, self.reason
        
        # 2. Target hit
        target_pct = self._get_target_pct()
        if gain_pct >= target_pct:
            self.signals.append(f"Target: {gain_pct*100:.1f}% (>= {target_pct*100:.1f}%)")
            self.should_exit = True
            self.reason = f"Target hit: {gain_pct*100:.1f}% gain"
            return True, self.reason
        
        # 3. Trailing stop (only if in profit)
        if self.peak_price > self.entry_price:
            trail_pct = self._get_trail_pct()
            should_exit, reason = check_trailing_stop(
                self.entry_price, self.peak_price, 
                self.current_price, trail_pct
            )
            if should_exit:
                self.signals.append(f"Trailing stop: {reason}")
                self.should_exit = True
                self.reason = reason
                return True, self.reason
        
        # 4. VWAP breakdown (if VWAP available)
        if self.df is not None and self.vwap is not None:
            should_exit, reason = check_vwap_breakdown(self.df, self.vwap)
            if should_exit:
                self.signals.append(f"VWAP breakdown: {reason}")
                self.should_exit = True
                self.reason = reason
                return True, self.reason
        
        # 5. Recovery score (if DataFrame available)
        if self.df is not None:
            score, desc = calc_recovery_score(self.df)
            if score < 20:  # Very weak recovery
                self.signals.append(f"Recovery score: {score}/100 — {desc}")
                self.should_exit = True
                self.reason = f"Weak recovery: {desc}"
                return True, self.reason
        
        # No exit triggered
        reasons = " | ".join(self.signals) if self.signals else "No exit signals"
        return False, reasons
    
    def _get_hard_stop_pct(self) -> float:
        """Get hard stop percentage based on regime."""
        stops = {
            "TRENDING": 0.07,
            "NEUTRAL": 0.05,
            "DEFENSIVE": 0.04,
        }
        return stops.get(self.regime, 0.05)
    
    def _get_target_pct(self) -> float:
        """Get target percentage based on regime."""
        targets = {
            "TRENDING": 0.15,
            "NEUTRAL": 0.12,
            "DEFENSIVE": 0.10,
        }
        return targets.get(self.regime, 0.12)
    
    def _get_trail_pct(self) -> float:
        """Get trailing stop percentage based on regime."""
        trails = {
            "TRENDING": 0.02,
            "NEUTRAL": 0.03,
            "DEFENSIVE": 0.04,
        }
        return trails.get(self.regime, 0.03)


# ─── Integration Helpers ────────────────────────────────────────────────────

def should_exit_position(symbol: str, entry_price: float, peak_price: float,
                         current_price: float, df: pd.DataFrame = None,
                         vwap: float = None, regime: str = "NEUTRAL") -> Tuple[bool, str]:
    """Quick check if a position should be exited.
    
    Returns:
        (should_exit, reason)
    """
    decision = ExitDecision(symbol, entry_price, peak_price, 
                           current_price, df, vwap, regime)
    return decision.check_all()


# ─── Test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== US Exit Triggers Test ===\n")
    
    # Test trailing stop
    print("1. Trailing Stop Test:")
    tests = [
        (100, 110, 107, 0.03, False, "In profit, within trail"),
        (100, 110, 106, 0.03, False, "In profit, at trail limit"),
        (100, 110, 105.5, 0.03, True, "In profit, exceeded trail"),
        (100, 100, 95, 0.03, False, "Not in profit"),
    ]
    for entry, peak, curr, trail, expected, desc in tests:
        result, reason = check_trailing_stop(entry, peak, curr, trail)
        status = "✅" if result == expected else "❌"
        print(f"  {status} {desc}: {result} — {reason}")
    
    print("\n2. VWAP Breakdown Test:")
    # Create sample data
    sample_data = {
        'Close': [105, 104, 103, 102, 101],
        'Volume': [1000, 1000, 1000, 1000, 1000]
    }
    df = pd.DataFrame(sample_data)
    result, reason = check_vwap_breakdown(df, 102, bars_required=3)
    print(f"  3 bars below VWAP 102: {result} — {reason}")
    
    print("\n3. Recovery Score Test:")
    # Uptrend data
    uptrend = pd.DataFrame({'Close': [100, 101, 102, 103, 104]})
    score, desc = calc_recovery_score(uptrend)
    print(f"  Uptrend (100→104): Score {score}/100 — {desc}")
    
    # Downtrend data
    downtrend = pd.DataFrame({'Close': [104, 103, 102, 101, 100]})
    score, desc = calc_recovery_score(downtrend)
    print(f"  Downtrend (104→100): Score {score}/100 — {desc}")
    
    print("\n4. Exit Decision Engine Test:")
    decision = ExitDecision("AAPL", 100, 110, 105, regime="NEUTRAL")
    should_exit, reason = decision.check_all()
    print(f"  AAPL entry=$100 peak=$110 current=$105: {should_exit} — {reason}")
    
    print("\n✅ All tests complete")
