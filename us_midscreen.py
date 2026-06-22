#!/usr/bin/env python3
"""
US Mid-Session Screener
========================

Uses Alpaca real-time data to find intraday opportunities:
- Gap-up candidates (strong volume + momentum)
- VWAP reclaim setups
- Breakout above pre-market high
- Relative strength leaders

Runs at:
- 10:00 ET (17:00 GMT+3) — early momentum
- 11:30 ET (18:30 GMT+3) — mid-morning
- 13:30 ET (20:30 GMT+3) — afternoon setups

Output: Appends to us_picks.json with midscreen picks
"""

import json
import os
import time as time_mod
import logging
from datetime import datetime, date, time, timedelta
from typing import List, Dict, Optional, Tuple
import pytz

import yfinance as yf
import pandas as pd
import numpy as np

from alpaca_api import AlpacaTrader
from us_sharia_universe import get_sharia_universe, is_sharia_compliant
from us_market_regime import get_current_regime

# Simple cache for yfinance data
class YFinanceCache:
    def __init__(self, max_age_seconds=300):  # 5 minutes cache
        self.cache = {}
        self.max_age = max_age_seconds
    
    def get(self, key):
        if key in self.cache:
            data, timestamp = self.cache[key]
            if time_mod.time() - timestamp < self.max_age:
                return data
            else:
                del self.cache[key]
        return None
    
    def set(self, key, data):
        self.cache[key] = (data, time_mod.time())

# Global cache instance
_yf_cache = YFinanceCache()

# Load environment variables
_ENV_FILE = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_ENV_FILE):
    with open(_ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())

# ── Logging ─────────────────────────────────────────────────────────────────
log = logging.getLogger("us_midscreen")
if not log.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    ))
    log.addHandler(handler)
    log.setLevel(logging.INFO)

# ── Constants ──────────────────────────────────────────────────────────────
ET = pytz.timezone("America/New_York")
PICKS_FILE = os.path.join(os.path.dirname(__file__), "us_picks.json")

# Screening parameters — EXTREME RISK (match main screener)
MIN_PRICE = 0.01          # EXTREME: Any price
MAX_PRICE = 5000.0        # EXTREME: No upper limit
MIN_VOLUME = 0            # EXTREME: Accept any volume
MIN_RELATIVE_VOLUME = 0.5   # EXTREME: Lower threshold
MIN_CHANGE_PCT = -0.05    # EXTREME: Accept down to -5%
MAX_CHANGE_PCT = 0.50     # EXTREME: Up to 50%
MIN_MKT_CAP = 10_000_000  # EXTREME: $10M minimum

# Scoring weights
WEIGHT_CHANGE = 0.30
WEIGHT_VOLUME = 0.25
WEIGHT_VWAP = 0.25
WEIGHT_RANGE = 0.20


def get_intraday_data(symbol: str, trader: AlpacaTrader) -> Optional[Dict]:
    """
    Fetch intraday data from Alpaca.
    
    Returns:
        {
            "symbol": ticker,
            "open": float,
            "high": float,
            "low": float,
            "current": float,
            "prev_close": float,
            "volume": int,
            "avg_volume": int,
            "vwap": float,
            "change_pct": float,
            "range_pct": float,
            "above_vwap": bool,
            "above_open": bool,
        }
    """
    try:
        # Check cache first for yfinance data
        cache_key = f"{symbol}_intraday_yf"
        cached_yf_data = _yf_cache.get(cache_key)
        
        # Get 1-minute bars for today
        bars = trader.get_bars(symbol, timeframe="1Min", limit=390)  # Full day
        if not bars or len(bars) < 5:
            return None
        
        df = pd.DataFrame(bars)
        df["t"] = pd.to_datetime(df["t"])
        df = df.sort_values("t")
        
        # Calculate metrics
        open_price = float(df["o"].iloc[0])
        high = float(df["h"].max())
        low = float(df["l"].min())
        current = float(df["c"].iloc[-1])
        volume = int(df["v"].sum())
        
        # VWAP calculation
        df["tp"] = (df["h"] + df["l"] + df["c"]) / 3
        df["cum_vol"] = df["v"].cumsum()
        df["cum_tp_vol"] = (df["tp"] * df["v"]).cumsum()
        vwap = float(df["cum_tp_vol"].iloc[-1] / df["cum_vol"].iloc[-1]) if df["cum_vol"].iloc[-1] > 0 else None
        
        # Get previous close for change %
        prev_close = open_price  # Default fallback
        avg_volume = volume  # Default fallback
        
        # Try cached yfinance data first
        if cached_yf_data:
            prev_close = cached_yf_data["prev_close"]
            avg_volume = cached_yf_data["avg_volume"]
        else:
            # Try yfinance for previous close and average volume
            try:
                t = yf.Ticker(symbol)
                
                # Get previous close
                hist = t.history(period="2d", interval="1d")
                if len(hist) >= 2:
                    prev_close = float(hist["Close"].iloc[-2])
                
                # Get average volume (20-day)
                hist_vol = t.history(period="20d", interval="1d")
                if not hist_vol.empty:
                    avg_volume = int(hist_vol["Volume"].mean())
                
                # Cache the yfinance data
                _yf_cache.set(cache_key, {
                    "prev_close": prev_close,
                    "avg_volume": avg_volume
                })
            except Exception as e:
                log.debug(f"yfinance fetch failed for {symbol}: {e}")
        
        change_pct = (current - prev_close) / prev_close if prev_close > 0 else 0
        range_pct = (high - low) / open_price if open_price > 0 else 0
        
        return {
            "symbol": symbol,
            "open": open_price,
            "high": high,
            "low": low,
            "current": current,
            "prev_close": prev_close,
            "volume": volume,
            "avg_volume": avg_volume,
            "vwap": vwap,
            "change_pct": change_pct,
            "range_pct": range_pct,
            "above_vwap": vwap is not None and current > vwap,
            "above_open": current > open_price,
        }
    except Exception as e:
        log.warning(f"Error fetching {symbol}: {e}")
        import traceback
        log.debug(f"Full traceback for {symbol}: {traceback.format_exc()}")
        return None


def calculate_score(data: Dict) -> float:
    """Calculate intraday momentum score."""
    change = data["change_pct"]
    volume = data["volume"]
    avg_volume = data["avg_volume"]
    vwap = data["vwap"]
    current = data["current"]
    range_pct = data["range_pct"]
    
    # Change score (0-10% → 0-100)
    change_score = min(max(change / MAX_CHANGE_PCT, 0), 1) * 100
    
    # Relative volume score (1x-3x → 0-100)
    rel_vol = volume / max(avg_volume, 1)
    vol_score = min(max((rel_vol - 1) / 2, 0), 1) * 100
    
    # VWAP score (above = 100, below = 0)
    vwap_score = 100 if data["above_vwap"] else 0
    
    # Range score (0-5% → 0-100)
    range_score = min(range_pct / 0.05, 1) * 100
    
    # Combined score
    score = (
        WEIGHT_CHANGE * change_score +
        WEIGHT_VOLUME * vol_score +
        WEIGHT_VWAP * vwap_score +
        WEIGHT_RANGE * range_score
    )
    
    return score


def screen_stock(data: Dict, regime_name: str = "NEUTRAL") -> Optional[Dict]:
    """Apply filters to intraday data with regime-based adjustments."""
    current = data["current"]
    change = data["change_pct"]
    volume = data["volume"]
    avg_volume = data["avg_volume"]
    rel_vol = volume / max(avg_volume, 1)
    
    # Regime-based adjustments
    if regime_name == "BULL":
        # In bull market, be more aggressive on momentum
        min_change_pct = MIN_CHANGE_PCT * 0.5  # Lower threshold
        max_change_pct = MAX_CHANGE_PCT * 1.5  # Higher threshold
        min_rel_volume = MIN_RELATIVE_VOLUME * 0.8  # Lower threshold
    elif regime_name == "BEAR":
        # In bear market, be more conservative
        min_change_pct = MIN_CHANGE_PCT * 1.5  # Higher threshold
        max_change_pct = MAX_CHANGE_PCT * 0.8  # Lower threshold
        min_rel_volume = MIN_RELATIVE_VOLUME * 1.2  # Higher threshold
    elif regime_name == "VOLATILE":
        # In volatile market, focus on volume
        min_change_pct = MIN_CHANGE_PCT
        max_change_pct = MAX_CHANGE_PCT * 1.2  # Slightly higher
        min_rel_volume = MIN_RELATIVE_VOLUME * 1.5  # Higher threshold
    else:  # NEUTRAL or DEFENSIVE
        min_change_pct = MIN_CHANGE_PCT
        max_change_pct = MAX_CHANGE_PCT
        min_rel_volume = MIN_RELATIVE_VOLUME
    
    # Price filter
    if current < MIN_PRICE or current > MAX_PRICE:
        return None
    
    # Change filter with regime adjustments
    if change < min_change_pct or change > max_change_pct:
        return None
    
    # Volume filter with regime adjustments
    if rel_vol < min_rel_volume:
        return None
    
    # Calculate score
    score = calculate_score(data)
    
    # Entry zone: current price ± 0.5%
    entry_low = round(current * 0.995, 2)
    entry_high = round(current * 1.005, 2)
    
    return {
        "symbol": data["symbol"],
        "score": round(score, 1),
        "price": round(current, 2),
        "entry_low": entry_low,
        "entry_high": entry_high,
        "change_pct": round(change * 100, 2),
        "volume": volume,
        "avg_volume": avg_volume,
        "rel_volume": round(rel_vol, 2),
        "vwap": round(data["vwap"], 2) if data["vwap"] else None,
        "above_vwap": data["above_vwap"],
        "source": "midscreen",
        "time": datetime.now(ET).strftime("%H:%M:%S"),
    }


def run_midscreen(trader: AlpacaTrader, regime_name: str = "NEUTRAL", max_stocks: int = 100, top_n: int = 5) -> List[Dict]:
    """Run mid-session screening with regime-based filtering."""
    now = datetime.now(ET)
    log.info(f"Starting mid-screen at {now.strftime('%H:%M')} ET with regime: {regime_name}")
    
    # Get Sharia universe
    universe = get_sharia_universe()
    log.info(f"Universe: {len(universe)} Sharia-compliant stocks")
    
    # Limit for speed
    if len(universe) > max_stocks:
        import random
        random.seed(42)
        screen_universe = random.sample(universe, max_stocks)
    else:
        screen_universe = universe
    
    log.info(f"Screening {len(screen_universe)} stocks...")
    
    picks = []
    screened = 0
    
    for ticker in screen_universe:
        data = get_intraday_data(ticker, trader)
        screened += 1
        
        if data:
            pick = screen_stock(data, regime_name)
            if pick:
                picks.append(pick)
                log.info(f"  ✅ {ticker}: score={pick['score']}, change={pick['change_pct']}%, vol={pick['rel_volume']}x")
        
        if screened % 10 == 0:
            log.info(f"  Progress: {screened}/{len(screen_universe)} screened, {len(picks)} picks")
        
        # Remove rate limiting - using caching instead
        # time_mod.sleep(0.2)
    
    # Sort by score
    picks.sort(key=lambda x: x["score"], reverse=True)
    top_picks = picks[:top_n]
    
    log.info(f"Screen complete: {len(top_picks)} picks from {screened} screened")
    
    return top_picks


def save_picks(picks: List[Dict], mode: str = "midscreen"):
    """Append midscreen picks to existing us_picks.json."""
    try:
        with open(PICKS_FILE) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {
            "date": date.today().isoformat(),
            "time": datetime.now(ET).strftime("%H:%M:%S"),
            "timezone": "America/New_York",
            "mode": "premarket",
            "picks": [],
        }
    
    # Add midscreen picks with mode label
    for pick in picks:
        pick["source"] = mode
        data["picks"].append(pick)
    
    # Update metadata
    data["last_midscreen"] = datetime.now(ET).strftime("%H:%M:%S")
    data["midscreen_count"] = data.get("midscreen_count", 0) + len(picks)
    
    with open(PICKS_FILE, "w") as f:
        json.dump(data, f, indent=2)
    
    log.info(f"Saved {len(picks)} {mode} picks to {PICKS_FILE}")


def main():
    """Main entry point."""
    now = datetime.now(ET)
    now_time = now.time()
    
    # Determine mode based on time
    if time(9, 30) <= now_time < time(10, 30):
        mode = "midscreen1"
        label = "Early Momentum"
    elif time(11, 0) <= now_time < time(12, 0):
        mode = "midscreen2"
        label = "Mid-Morning"
    elif time(13, 0) <= now_time < time(14, 30):
        mode = "rescreen"
        label = "Afternoon"
    else:
        log.warning(f"Outside mid-screen hours ({now_time}) — exiting")
        return
    
    log.info(f"US Mid-Screen: {label} ({mode})")
    
    # Check regime
    regime_name = "NEUTRAL"
    try:
        regime = get_current_regime()
        regime_name = regime.get("regime", "NEUTRAL")
        # Skip mid-screen in DEFENSIVE regime (except for early momentum)
        if regime_name == "DEFENSIVE" and mode != "midscreen1":
            log.info(f"Regime is DEFENSIVE — skipping {mode}")
            return
    except Exception as e:
        log.warning(f"Regime check failed: {e}")
        import traceback
        log.debug(f"Regime check traceback: {traceback.format_exc()}")
        regime_name = "NEUTRAL"
    
    # Initialize Alpaca
    try:
        trader = AlpacaTrader()
    except Exception as e:
        log.error(f"Failed to initialize AlpacaTrader: {e}")
        import traceback
        log.debug(f"AlpacaTrader initialization traceback: {traceback.format_exc()}")
        return
    
    # ── Step 1: Check existing picks ─────────────────────────────────────────
    log.info("Step 1: Checking existing picks...")
    existing_picks = []
    try:
        with open(PICKS_FILE) as f:
            data = json.load(f)
            existing_picks = data.get("picks", [])
            log.info(f"Found {len(existing_picks)} existing picks")
    except (FileNotFoundError, json.JSONDecodeError) as e:
        log.warning(f"No existing picks file: {e}")
        data = {
            "date": date.today().isoformat(),
            "time": datetime.now(ET).strftime("%H:%M:%S"),
            "timezone": "America/New_York",
            "mode": "premarket",
            "regime": regime_name,
            "picks": [],
        }
    except Exception as e:
        log.error(f"Unexpected error loading picks file: {e}")
        import traceback
        log.debug(f"Picks file load traceback: {traceback.format_exc()}")
        data = {
            "date": date.today().isoformat(),
            "time": datetime.now(ET).strftime("%H:%M:%S"),
            "timezone": "America/New_York",
            "mode": "premarket",
            "regime": regime_name,
            "picks": [],
        }

    # Validate existing picks
    valid_picks = []
    removed_picks = []
    
    for pick in existing_picks:
        symbol = pick.get("symbol", "")
        if not symbol:
            continue
            
        # Check current data
        current_data = get_intraday_data(symbol, trader)
        if not current_data:
            removed_picks.append(symbol)
            log.info(f"  ❌ {symbol}: No data — removing")
            continue
        
        # Check if still valid
        change_pct = current_data.get("change_pct", 0)
        volume = current_data.get("volume", 0)
        
        # Remove if: dropped more than -5%, volume dried up, or below $0.01
        if change_pct < -0.05:
            removed_picks.append(symbol)
            log.info(f"  ❌ {symbol}: Dropped {change_pct*100:.1f}% — removing")
            continue
        
        if volume < 100:
            removed_picks.append(symbol)
            log.info(f"  ❌ {symbol}: Volume dried up ({volume}) — removing")
            continue
        
        # Still valid — update with current data
        pick["price"] = round(current_data.get("current", pick.get("price", 0)), 2)
        pick["change_pct"] = round(change_pct * 100, 2)
        pick["volume"] = volume
        pick["vwap"] = round(current_data.get("vwap", 0), 2) if current_data.get("vwap") else None
        pick["above_vwap"] = current_data.get("above_vwap", False)
        valid_picks.append(pick)
        log.info(f"  ✅ {symbol}: Still valid (change={change_pct*100:.1f}%, vol={volume})")
    
    log.info(f"Validation: {len(valid_picks)} valid, {len(removed_picks)} removed")
    
    # ── Step 2: Find new momentum plays ──────────────────────────────────────
    log.info("Step 2: Finding new momentum plays...")
    new_picks = run_midscreen(trader, regime_name=regime_name, max_stocks=100, top_n=5)
    
    # Combine: existing valid + new (avoid duplicates)
    existing_symbols = {p["symbol"] for p in valid_picks}
    combined_picks = valid_picks.copy()
    
    for new_pick in new_picks:
        if new_pick["symbol"] not in existing_symbols:
            combined_picks.append(new_pick)
            log.info(f"  ➕ {new_pick['symbol']}: New momentum play added")
    
    # Update data
    data["picks"] = combined_picks
    data["last_midscreen"] = datetime.now(ET).strftime("%H:%M:%S")
    data["midscreen_count"] = data.get("midscreen_count", 0) + len(new_picks)
    data["regime"] = regime_name
    data["validation"] = {
        "valid_count": len(valid_picks),
        "removed_count": len(removed_picks),
        "removed_symbols": removed_picks,
        "new_count": len(new_picks),
    }
    
    try:
        with open(PICKS_FILE, "w") as f:
            json.dump(data, f, indent=2)
        log.info(f"Saved {len(data['picks'])} {mode} picks to {PICKS_FILE}")
    except Exception as e:
        log.error(f"Failed to save picks to {PICKS_FILE}: {e}")
        import traceback
        log.debug(f"Save picks traceback: {traceback.format_exc()}")
        raise
    
    # Print summary
    print(f"\n{'='*60}")
    print(f"US MID-SCREEN RESULTS — {label}")
    print(f"Regime: {regime_name}")
    print(f"{'='*60}")
    print(f"Time: {now.strftime('%H:%M')} ET")
    print(f"Picks: {len(data['picks'])}")
    print(f"\n{'Rank':<5} {'Symbol':<8} {'Score':<8} {'Price':<10} {'Change%':<10} {'Vol(x)':<8}")
    print("-" * 60)
    for i, p in enumerate(data['picks'], 1):
        rv = p.get('rel_volume', 0)
        print(f"{i:<5} {p['symbol']:<8} {p['score']:<8.1f} ${p['price']:<9.2f} {p['change_pct']:<9.2f}% {rv:<7.1f}x")
    print(f"{'='*60}")
    
    return data["picks"]


if __name__ == "__main__":
    main()
