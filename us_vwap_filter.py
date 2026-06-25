#!/usr/bin/env python3
"""
US VWAP Direction Filter — v4.12
===================================
Check if VWAP is rising before entry — prevents entering falling trends.

Author: Mino (kimi-k2.6)
Version: 4.12
Date: 2026-06-23
"""

import pandas as pd
from typing import Tuple, Optional


def calc_vwap(df: pd.DataFrame) -> Optional[float]:
    """Calculate VWAP from DataFrame."""
    try:
        if df is None or df.empty:
            return None
        
        # Handle multi-column yfinance format (MultiIndex)
        if isinstance(df.columns, pd.MultiIndex):
            df_flat = pd.DataFrame()
            for col in ["High", "Low", "Close", "Volume"]:
                if col in df.columns.get_level_values(0):
                    df_flat[col] = df[col].iloc[:, 0] if isinstance(df[col], pd.DataFrame) else df[col]
            df = df_flat
        
        required_cols = ["High", "Low", "Close", "Volume"]
        if not all(col in df.columns for col in required_cols):
            return None
        
        # Ensure numeric
        for col in required_cols:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=required_cols)
        if df.empty:
            return None
        
        tp = (df["High"] + df["Low"] + df["Close"]) / 3
        cum_vol = df["Volume"].cumsum()
        if cum_vol.iloc[-1] == 0:
            return None
        
        vwap = (tp * df["Volume"]).cumsum().iloc[-1] / cum_vol.iloc[-1]
        return float(vwap)
    except:
        return None


def get_vwap_direction(df: pd.DataFrame, lookback: int = 5) -> Tuple[str, float, str]:
    """Determine VWAP direction over recent bars.
    
    Args:
        df: DataFrame with OHLCV data
        lookback: Number of bars to check (default 5)
    
    Returns:
        (direction, slope_pct, reason)
        direction: "rising", "falling", "flat"
    """
    try:
        if df is None or len(df) < lookback + 1:
            return "flat", 0.0, "Insufficient data"
        
        # Handle multi-column yfinance format (MultiIndex)
        if isinstance(df.columns, pd.MultiIndex):
            df_flat = pd.DataFrame()
            for col in ["High", "Low", "Close", "Volume"]:
                if col in df.columns.get_level_values(0):
                    df_flat[col] = df[col].iloc[:, 0] if isinstance(df[col], pd.DataFrame) else df[col]
            df = df_flat
        
        # Ensure required columns exist
        required = ["High", "Low", "Close", "Volume"]
        if not all(col in df.columns for col in required):
            return "flat", 0.0, f"Missing columns: {[c for c in required if c not in df.columns]}"
        
        # Ensure numeric types
        for col in required:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        
        # Drop rows with NaN
        df = df.dropna(subset=required)
        
        if len(df) < lookback:
            return "flat", 0.0, f"Not enough valid bars ({len(df)} < {lookback})"
        
        # Drop rows with NaN
        df = df.dropna(subset=required)
        
        if len(df) < lookback:
            return "flat", 0.0, f"Not enough valid bars ({len(df)} < {lookback})"
        
        # Calculate VWAP for each bar
        df = df.copy()
        df["tp"] = (df["High"] + df["Low"] + df["Close"]) / 3
        df["cum_tp_vol"] = (df["tp"] * df["Volume"]).cumsum()
        df["cum_vol"] = df["Volume"].cumsum()
        df["vwap"] = df["cum_tp_vol"] / df["cum_vol"]
        
        # Get VWAP values for last N bars
        recent_vwap = df["vwap"].dropna().tail(lookback)
        if len(recent_vwap) < lookback:
            return "flat", 0.0, f"Only {len(recent_vwap)} valid VWAP values"
        
        # Calculate slope
        first_vwap = float(recent_vwap.iloc[0])
        last_vwap = float(recent_vwap.iloc[-1])
        
        if first_vwap <= 0 or pd.isna(first_vwap) or pd.isna(last_vwap):
            return "flat", 0.0, "Invalid VWAP values"
        
        slope_pct = (last_vwap - first_vwap) / first_vwap * 100
        
        # Determine direction
        if slope_pct >= 0.02:
            direction = "rising"
            reason = f"VWAP rising: {slope_pct:+.2f}% over {lookback} bars"
        elif slope_pct <= -0.02:
            direction = "falling"
            reason = f"VWAP falling: {slope_pct:.2f}% over {lookback} bars"
        else:
            direction = "flat"
            reason = f"VWAP flat: {slope_pct:+.2f}% over {lookback} bars"
        
        return direction, slope_pct, reason
        
    except Exception as e:
        return "flat", 0.0, f"Error: {e}"


def should_enter_vwap_direction(df: pd.DataFrame, regime: str = "NEUTRAL") -> Tuple[bool, str]:
    """Check if VWAP direction allows entry.
    
    Paper trading: More lenient than TASI.
    - TRENDING: Allow flat or rising (more opportunities)
    - NEUTRAL: Require rising VWAP
    - DEFENSIVE: Require strongly rising VWAP
    """
    direction, slope_pct, reason = get_vwap_direction(df)
    
    if regime == "TRENDING":
        # TRENDING: Allow flat or rising
        if direction in ("rising", "flat"):
            return True, f"TRENDING: {reason} (entry allowed)"
        else:
            return False, f"TRENDING: {reason} (entry blocked — falling)"
    
    elif regime == "NEUTRAL":
        # NEUTRAL: Require rising
        if direction == "rising":
            return True, f"NEUTRAL: {reason} (entry allowed)"
        else:
            return False, f"NEUTRAL: {reason} (entry blocked — not rising)"
    
    else:  # DEFENSIVE
        # DEFENSIVE: Require strongly rising (slope > 0.05%)
        if direction == "rising" and slope_pct > 0.05:
            return True, f"DEFENSIVE: {reason} (entry allowed — strong rise)"
        else:
            return False, f"DEFENSIVE: {reason} (entry blocked — need strong rise)"


# ─── Test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== VWAP Direction Filter Test ===\n")
    
    # Create sample data: rising VWAP
    rising_data = {
        "High": [101, 102, 103, 104, 105, 106],
        "Low": [99, 100, 101, 102, 103, 104],
        "Close": [100, 101, 102, 103, 104, 105],
        "Volume": [1000, 1000, 1000, 1000, 1000, 1000],
    }
    df_rising = pd.DataFrame(rising_data)
    
    # Create sample data: falling VWAP
    falling_data = {
        "High": [105, 104, 103, 102, 101, 100],
        "Low": [103, 102, 101, 100, 99, 98],
        "Close": [104, 103, 102, 101, 100, 99],
        "Volume": [1000, 1000, 1000, 1000, 1000, 1000],
    }
    df_falling = pd.DataFrame(falling_data)
    
    # Test rising
    print("Rising VWAP:")
    direction, slope, reason = get_vwap_direction(df_rising)
    print(f"  Direction: {direction}, Slope: {slope:.3f}%")
    print(f"  Reason: {reason}")
    
    for regime in ["TRENDING", "NEUTRAL", "DEFENSIVE"]:
        allowed, msg = should_enter_vwap_direction(df_rising, regime)
        status = "✅" if allowed else "❌"
        print(f"  {status} {regime}: {msg}")
    
    print()
    
    # Test falling
    print("Falling VWAP:")
    direction, slope, reason = get_vwap_direction(df_falling)
    print(f"  Direction: {direction}, Slope: {slope:.3f}%")
    print(f"  Reason: {reason}")
    
    for regime in ["TRENDING", "NEUTRAL", "DEFENSIVE"]:
        allowed, msg = should_enter_vwap_direction(df_falling, regime)
        status = "✅" if allowed else "❌"
        print(f"  {status} {regime}: {msg}")
    
    print("\n=== Test Complete ===")
