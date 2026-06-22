#!/usr/bin/env python3
"""
US Market Regime Classifier
============================

Classifies US market as TRENDING / NEUTRAL / DEFENSIVE based on:
- SPY (S&P 500 ETF) momentum
- VIX (volatility index)
- Sector breadth and rotation

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


# Sector ETFs for breadth analysis
SECTOR_ETFs = {
    "XLC": "Communication Services",
    "XLY": "Consumer Discretionary",
    "XLP": "Consumer Staples",
    "XLE": "Energy",
    "XLF": "Financials",
    "XLV": "Healthcare",
    "XLI": "Industrials",
    "XLB": "Materials",
    "XLRE": "Real Estate",
    "XLK": "Technology",
    "XLU": "Utilities",
}


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


def _get_sector_performance() -> dict:
    """Get sector performance over different timeframes."""
    sector_perf = {}
    try:
        for etf, name in SECTOR_ETFs.items():
            ticker = yf.Ticker(etf)
            hist = ticker.history(period="15d", interval="1d")
            if not hist.empty and len(hist) >= 5:
                current = float(hist["Close"].iloc[-1])
                close_5d = float(hist["Close"].iloc[-5])
                change_5d = (current - close_5d) / close_5d * 100
                sector_perf[etf] = {
                    "name": name,
                    "change_5d": change_5d,
                    "current": current
                }
    except Exception as e:
        log.warning(f"Sector performance fetch failed: {e}")
    return sector_perf


def _analyze_sector_rotation(sector_perf: dict) -> tuple[str, str]:
    """Analyze sector rotation and breadth."""
    if not sector_perf:
        return "NEUTRAL", "No sector data available"
    
    # Sort sectors by performance
    sorted_sectors = sorted(sector_perf.items(), key=lambda x: x[1]["change_5d"], reverse=True)
    
    # Get top and bottom performers
    top_3 = sorted_sectors[:3]
    bottom_3 = sorted_sectors[-3:]
    
    # Count positive sectors
    positive_sectors = sum(1 for s in sector_perf.values() if s["change_5d"] > 0)
    total_sectors = len(sector_perf)
    
    # Breadth analysis
    breadth_pct = (positive_sectors / total_sectors * 100) if total_sectors > 0 else 50
    
    # Rotation analysis
    top_sectors = ", ".join([f"{s[1]['name']} ({s[1]['change_5d']:.1f}%)" for s in top_3])
    
    return breadth_pct, top_sectors


def classify_premarket() -> dict:
    """Classify regime before market open based on SPY + VIX + sector analysis."""
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
        spy_close = float(spy_hist["Close"].iloc[-1])
        spy_5d = float(spy_hist["Close"].iloc[-5])
        spy_10d = float(spy_hist["Close"].iloc[-10]) if len(spy_hist) >= 10 else spy_5d
        
        spy_change_5d = (spy_close - spy_5d) / spy_5d * 100
        spy_change_10d = (spy_close - spy_10d) / spy_10d * 100
        
        # Get VIX
        vix = _get_vix_level()
        
        # Get sector performance
        sector_perf = _get_sector_performance()
        breadth_pct, top_sectors = _analyze_sector_rotation(sector_perf)
        
        # Regime logic
        # TRENDING: SPY up >1% over 5 days, VIX <20 (low fear), broad sector participation
        # DEFENSIVE: SPY down >1% over 5 days OR VIX >25 (high fear) OR weak sector breadth
        # NEUTRAL: Everything else
        
        if spy_change_5d > 1.0 and vix < 20 and breadth_pct > 60:
            regime = "TRENDING"
            reason = f"SPY +{spy_change_5d:.1f}% over 5 days, VIX {vix:.1f} (low fear), {breadth_pct:.0f}% sector breadth"
        elif spy_change_5d < -1.0 or vix > 25 or breadth_pct < 40:
            regime = "DEFENSIVE"
            reason = f"SPY {spy_change_5d:+.1f}% over 5 days, VIX {vix:.1f} (elevated fear), {breadth_pct:.0f}% sector breadth"
        else:
            regime = "NEUTRAL"
            reason = f"SPY {spy_change_5d:+.1f}% over 5 days, VIX {vix:.1f} (moderate), {breadth_pct:.0f}% sector breadth"
        
        result = {
            "regime": regime,
            "params": REGIME_PARAMS[regime],
            "reason": reason,
            "spy_5d_change": round(spy_change_5d, 2),
            "spy_10d_change": round(spy_change_10d, 2),
            "vix": round(vix, 2),
            "sector_breadth": round(breadth_pct, 1),
            "top_sectors": top_sectors,
            "classified_at": datetime.now().isoformat(),
        }
        
        _write_regime_file(result)
        log.info(f"Regime: {regime} — {reason}")
        return result
        
    except Exception as e:
        log.error(f"Regime classification failed: {e}")
        import traceback
        log.debug(f"Regime classification traceback: {traceback.format_exc()}")
        result = dict(_NEUTRAL_DEFAULT)
        result["classified_at"] = datetime.now().isoformat()
        _write_regime_file(result)
        return result


def classify_intraday() -> dict:
    """Re-check regime during session (lighter check with 30-min window)."""
    current = _read_regime_file()
    
    # Reclassify if stale (reduce from 2 hours to 30 minutes)
    classified_at = current.get("classified_at")
    if classified_at:
        try:
            dt = datetime.fromisoformat(classified_at)
            age_minutes = (datetime.now() - dt).total_seconds() / 60
            if age_minutes > 30:  # Reduced from 2 hours to 30 minutes
                log.info("Regime stale (>30min) — reclassifying")
                return classify_premarket()
        except Exception as e:
            log.warning(f"Failed to parse classification time: {e}")
    
    # Check for significant VIX spike or market changes
    try:
        vix = _get_vix_level()
        
        # Check for VIX spike that would warrant regime change
        current_vix = current.get("vix", 20.0)
        vix_spike = vix > current_vix * 1.3  # 30% increase in VIX
        
        # Also check if we should switch to defensive due to high VIX
        if (vix > 30 and current["regime"] != "DEFENSIVE") or vix_spike:
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
    
    # Check if stale (>30 minutes old - reduced from 2 hours)
    classified_at = current.get("classified_at")
    if classified_at:
        try:
            dt = datetime.fromisoformat(classified_at)
            age_minutes = (datetime.now() - dt).total_seconds() / 60
            if age_minutes > 30:  # Reduced from 2 hours to 30 minutes
                log.info("Regime stale (>30min) — reclassifying")
                return classify_premarket()
        except:
            pass
    
    return current


def is_market_open() -> bool:
    """Check if US market is currently open."""
    try:
        from datetime import time
        import pytz
        
        # US Eastern Time
        ET = pytz.timezone("America/New_York")
        now = datetime.now(ET)
        now_time = now.time()
        
        # Market hours: 9:30 AM to 4:00 PM ET
        market_open = time(9, 30)
        market_close = time(16, 0)
        
        # Check if it's a weekday (Monday=0, Sunday=6)
        is_weekday = now.weekday() < 5
        
        # Check if current time is within market hours
        is_market_hours = market_open <= now_time <= market_close
        
        return is_weekday and is_market_hours
    except Exception as e:
        log.warning(f"Market open check failed: {e}")
        # Fallback to basic time check
        return True  # Assume market is open if we can't determine


def get_regime_params() -> dict:
    """Get parameters for current regime."""
    regime = get_current_regime()
    return regime.get("params", REGIME_PARAMS["NEUTRAL"])


def is_market_open() -> bool:
    """Check if US market is currently open."""
    try:
        from datetime import time
        import pytz
        
        # US Eastern Time
        ET = pytz.timezone("America/New_York")
        now = datetime.now(ET)
        now_time = now.time()
        
        # Market hours: 9:30 AM to 4:00 PM ET
        market_open = time(9, 30)
        market_close = time(16, 0)
        
        # Check if it's a weekday (Monday=0, Sunday=6)
        is_weekday = now.weekday() < 5
        
        # Check if current time is within market hours
        is_market_hours = market_open <= now_time <= market_close
        
        return is_weekday and is_market_hours
    except Exception as e:
        log.warning(f"Market open check failed: {e}")
        # Fallback to basic time check
        return True  # Assume market is open if we can't determine
