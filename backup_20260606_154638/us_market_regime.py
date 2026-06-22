#!/usr/bin/env python3
"""
US Market Regime Classifier
============================

Classifies US market as TRENDING / NEUTRAL / DEFENSIVE based on:
- SPY (S&P 500 ETF) momentum
- VIX (volatility index)
- Sector breadth

Pre-market: classify_premarket() — called before 09:30
Intraday: classify_intraday() — called every 30 min
"""

import json
import logging
import os
from datetime import datetime

import requests
import yfinance as yf

# ─── Config ──────────────────────────────────────────────────────────────────

REGIME_FILE = "/home/mino/us-exec/us_regime.json"

REGIME_PARAMS = {
    "TRENDING":  {
        "strategy":         "Aggressive",
        "max_positions":    3,
        "position_pct":     0.40,
        "alt_position_pct": 0.25,
        "target_pct":       0.025,   # +2.5% target
        "trail_trigger":    0.025,   # trail after +2.5%
        "trail_stop":       0.03,    # -3% from peak
        "hard_stop":        0.05,    # -5% hard stop (tighter than TASI)
        "time_stop_mins":   30,
        "time_stop_pct":    0.01,
        "midscreen":        True,    # Use mid-screen picks
    },
    "NEUTRAL":   {
        "strategy":         "Standard",
        "max_positions":    3,
        "position_pct":     0.30,
        "alt_position_pct": 0.30,
        "target_pct":       0.02,    # +2% target
        "trail_trigger":    0.02,    # trail after +2%
        "trail_stop":       0.03,    # -3% from peak
        "hard_stop":        0.05,    # -5% hard stop
        "time_stop_mins":   30,
        "time_stop_pct":    0.01,
        "midscreen":        True,
    },
    "DEFENSIVE": {
        "strategy":         "Conservative",
        "max_positions":    2,
        "position_pct":     0.20,
        "alt_position_pct": 0.20,
        "target_pct":       0.015,   # +1.5% target
        "trail_trigger":    0.015,   # trail after +1.5%
        "trail_stop":       0.02,    # -2% from peak
        "hard_stop":        0.04,    # -4% hard stop
        "time_stop_mins":   20,
        "time_stop_pct":    0.005,
        "midscreen":        False,   # Skip mid-screen
    },
}

_NEUTRAL_DEFAULT = {
    "regime": "NEUTRAL",
    "params": REGIME_PARAMS["NEUTRAL"],
    "reason": "Default — no data available.",
    "classified_at": None,
}

log = logging.getLogger("us_regime")


def _read_regime_file() -> dict:
    """Read regime.json."""
    try:
        if os.path.exists(REGIME_FILE):
            with open(REGIME_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return dict(_NEUTRAL_DEFAULT)


def _write_regime_file(data: dict):
    with open(REGIME_FILE, "w") as f:
        json.dump(data, f, indent=2, default=str)


def _get_vix_level() -> float:
    """Get current VIX level."""
    try:
        vix = yf.Ticker("^VIX")
        hist = vix.history(period="2d", interval="1d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception as e:
        log.warning(f"VIX fetch failed: {e}")
    return 20.0  # Default moderate volatility


def classify_premarket() -> dict:
    """Classify regime before market open based on SPY + VIX."""
    try:
        # Get SPY data
        spy = yf.Ticker("SPY")
        spy_hist = spy.history(period="15d", interval="1d")
        
        if spy_hist.empty or len(spy_hist) < 5:
            log.warning("Insufficient SPY data — defaulting NEUTRAL")
            result = dict(_NEUTRAL_DEFAULT)
            result["classified_at"] = datetime.now().isoformat()
            _write_regime_file(result)
            return result
        
        # Calculate SPY momentum
        spy_close = spy_hist["Close"].iloc[-1]
        spy_5d = spy_hist["Close"].iloc[-5]
        spy_10d = spy_hist["Close"].iloc[-10] if len(spy_hist) >= 10 else spy_5d
        
        spy_change_5d = (spy_close - spy_5d) / spy_5d * 100
        spy_change_10d = (spy_close - spy_10d) / spy_10d * 100
        
        # Get VIX
        vix = _get_vix_level()
        
        # Regime logic
        # TRENDING: SPY up >1% over 5 days, VIX <20 (low fear)
        # DEFENSIVE: SPY down >1% over 5 days OR VIX >25 (high fear)
        # NEUTRAL: Everything else
        
        if spy_change_5d > 1.0 and vix < 20:
            regime = "TRENDING"
            reason = f"SPY +{spy_change_5d:.1f}% over 5 days, VIX {vix:.1f} (low fear)"
        elif spy_change_5d < -1.0 or vix > 25:
            regime = "DEFENSIVE"
            reason = f"SPY {spy_change_5d:+.1f}% over 5 days, VIX {vix:.1f} (elevated fear)"
        else:
            regime = "NEUTRAL"
            reason = f"SPY {spy_change_5d:+.1f}% over 5 days, VIX {vix:.1f} (moderate)"
        
        result = {
            "regime": regime,
            "params": REGIME_PARAMS[regime],
            "reason": reason,
            "spy_5d_change": round(spy_change_5d, 2),
            "spy_10d_change": round(spy_change_10d, 2),
            "vix": round(vix, 2),
            "classified_at": datetime.now().isoformat(),
        }
        
        _write_regime_file(result)
        log.info(f"Regime: {regime} — {reason}")
        return result
        
    except Exception as e:
        log.error(f"Regime classification failed: {e}")
        result = dict(_NEUTRAL_DEFAULT)
        result["classified_at"] = datetime.now().isoformat()
        _write_regime_file(result)
        return result


def classify_intraday() -> dict:
    """Re-check regime during session (lighter check)."""
    current = _read_regime_file()
    
    # Only reclassify if significant VIX spike
    try:
        vix = _get_vix_level()
        if vix > 30 and current["regime"] != "DEFENSIVE":
            old = current["regime"]
            current["regime"] = "DEFENSIVE"
            current["params"] = REGIME_PARAMS["DEFENSIVE"]
            current["reason"] = f"VIX spike to {vix:.1f} — switching to defensive"
            current["vix"] = round(vix, 2)
            current["classified_at"] = datetime.now().isoformat()
            _write_regime_file(current)
            log.info(f"Regime shift: {old} → DEFENSIVE (VIX spike)")
    except Exception as e:
        log.warning(f"Intraday re-check failed: {e}")
    
    return current


def get_current_regime() -> dict:
    """Get current regime (load or classify if stale)."""
    current = _read_regime_file()
    
    # Check if stale (>2 hours old)
    classified_at = current.get("classified_at")
    if classified_at:
        try:
            dt = datetime.fromisoformat(classified_at)
            age_hours = (datetime.now() - dt).total_seconds() / 3600
            if age_hours > 2:
                log.info("Regime stale (>2h) — reclassifying")
                return classify_premarket()
        except:
            pass
    
    return current


def get_regime_params() -> dict:
    """Get parameters for current regime."""
    regime = get_current_regime()
    return regime.get("params", REGIME_PARAMS["NEUTRAL"])


# ── Test ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    result = classify_premarket()
    print(f"Regime: {result['regime']}")
    print(f"Reason: {result['reason']}")
    print(f"VIX: {result.get('vix', '?')}")
    print(f"Params: {result['params']}")
