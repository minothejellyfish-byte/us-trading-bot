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
from datetime import datetime, date, time as dt_time, timedelta
from typing import List, Dict, Optional, Tuple
import pytz

import yfinance as yf
import pandas as pd
import numpy as np

from alpaca_api import AlpacaTrader
from us_sharia_universe import get_sharia_universe, is_sharia_compliant
from us_market_regime import get_current_regime

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

# Screening parameters
MIN_PRICE = 5.0
MAX_PRICE = 500.0
MIN_VOLUME = 500000        # Minimum daily volume
MIN_RELATIVE_VOLUME = 1.5  # 1.5x average volume
MIN_CHANGE_PCT = 0.005     # 0.5% minimum move
MAX_CHANGE_PCT = 0.10      # 10% max (avoid extreme)
MIN_MKT_CAP = 1_000_000_000  # $1B minimum

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
        # Try yfinance for previous close
        try:
            t = yf.Ticker(symbol)
            hist = t.history(period="2d", interval="1d")
            if len(hist) >= 2:
                prev_close = float(hist["Close"].iloc[-2])
            else:
                prev_close = open_price  # Fallback
        except:
            prev_close = open_price
        
        change_pct = (current - prev_close) / prev_close if prev_close > 0 else 0
        range_pct = (high - low) / open_price if open_price > 0 else 0
        
        # Get average volume (20-day)
        try:
            t = yf.Ticker(symbol)
            hist = t.history(period="20d", interval="1d")
            avg_volume = int(hist["Volume"].mean()) if not hist.empty else volume
        except:
            avg_volume = volume
        
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
        log.debug(f"Error fetching {symbol}: {e}")
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


def screen_stock(data: Dict) -> Optional[Dict]:
    """Apply filters to intraday data."""
    current = data["current"]
    change = data["change_pct"]
    volume = data["volume"]
    avg_volume = data["avg_volume"]
    rel_vol = volume / max(avg_volume, 1)
    
    # Price filter
    if current < MIN_PRICE or current > MAX_PRICE:
        return None
    
    # Change filter
    if change < MIN_CHANGE_PCT or change > MAX_CHANGE_PCT:
        return None
    
    # Volume filter
    if rel_vol < MIN_RELATIVE_VOLUME:
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


def run_midscreen(trader: AlpacaTrader, max_stocks: int = 100, top_n: int = 5) -> List[Dict]:
    """Run mid-session screening."""
    now = datetime.now(ET)
    log.info(f"Starting mid-screen at {now.strftime('%H:%M')} ET")
    
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
            pick = screen_stock(data)
            if pick:
                picks.append(pick)
                log.info(f"  ✅ {ticker}: score={pick['score']}, change={pick['change_pct']}%, vol={pick['rel_volume']}x")
        
        if screened % 10 == 0:
            log.info(f"  Progress: {screened}/{len(screen_universe)} screened, {len(picks)} picks")
        
        # Rate limiting
        time_mod.sleep(0.2)
    
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
    if dt_time(9, 30) <= now_time < dt_time(10, 30):
        mode = "midscreen1"
        label = "Early Momentum"
    elif dt_time(11, 0) <= now_time < dt_time(12, 0):
        mode = "midscreen2"
        label = "Mid-Morning"
    elif dt_time(13, 0) <= now_time < dt_time(14, 30):
        mode = "rescreen"
        label = "Afternoon"
    else:
        log.warning(f"Outside mid-screen hours ({now_time}) — exiting")
        return
    
    log.info(f"US Mid-Screen: {label} ({mode})")
    
    # Check regime
    try:
        regime = get_current_regime()
        regime_name = regime.get("regime", "NEUTRAL")
        # Skip mid-screen in DEFENSIVE regime
        if regime_name == "DEFENSIVE" and mode != "midscreen1":
            log.info(f"Regime is DEFENSIVE — skipping {mode}")
            return
    except Exception as e:
        log.warning(f"Regime check failed: {e}")
        regime_name = "NEUTRAL"
    
    # Initialize Alpaca
    trader = AlpacaTrader()
    
    # Run screen
    picks = run_midscreen(trader, max_stocks=100, top_n=5)
    
    # Save with regime
    try:
        with open(PICKS_FILE) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {
            "date": date.today().isoformat(),
            "time": datetime.now(ET).strftime("%H:%M:%S"),
            "timezone": "America/New_York",
            "mode": "premarket",
            "regime": regime_name,
            "picks": [],
        }
    
    # Add midscreen picks with mode label
    for pick in picks:
        pick["source"] = mode
        data["picks"].append(pick)
    
    # Update metadata
    data["last_midscreen"] = datetime.now(ET).strftime("%H:%M:%S")
    data["midscreen_count"] = data.get("midscreen_count", 0) + len(picks)
    data["regime"] = regime_name
    
    with open(PICKS_FILE, "w") as f:
        json.dump(data, f, indent=2)
    
    log.info(f"Saved {len(picks)} {mode} picks to {PICKS_FILE}")
    
    # Print summary
    print(f"\n{'='*60}")
    print(f"US MID-SCREEN RESULTS — {label}")
    print(f"Regime: {regime_name}")
    print(f"{'='*60}")
    print(f"Time: {now.strftime('%H:%M')} ET")
    print(f"Picks: {len(picks)}")
    print(f"\n{'Rank':<5} {'Symbol':<8} {'Score':<8} {'Price':<10} {'Change%':<10} {'Vol(x)':<8}")
    print("-" * 60)
    for i, p in enumerate(picks, 1):
        print(f"{i:<5} {p['symbol']:<8} {p['score']:<8.1f} ${p['price']:<9.2f} {p['change_pct']:<9.2f}% {p['rel_volume']:<7.1f}x")
    print(f"{'='*60}")
    
    return picks


if __name__ == "__main__":
    main()
