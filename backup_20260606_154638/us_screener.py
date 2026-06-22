"""
US Premarket Screener — Sharia-Compliant
=========================================

Scans Sharia-compliant US stocks pre-market for:
- Gap-up candidates (strong pre-market volume + momentum)
- Breakout setups (above previous day high)
- VWAP reclaim candidates

Runs at 09:20 ET (16:20 GMT+3) — 10 minutes before market open.

Output: us_picks.json with top 5-10 candidates.

Usage:
    python3 us_screener.py
    
    # Or import:
    from us_screener import run_premarket_screen
    picks = run_premarket_screen()
"""

import json
import os
import time
import logging
from datetime import datetime, date, time as dt_time, timedelta
from typing import List, Dict, Optional, Tuple
import pytz

import yfinance as yf
import pandas as pd
import numpy as np

from us_sharia_universe import get_sharia_universe
from us_market_regime import classify_premarket

# Load environment variables from .env file
_ENV_FILE = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_ENV_FILE):
    with open(_ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())

# ── Logging ─────────────────────────────────────────────────────────────────
log = logging.getLogger("us_screener")
if not log.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    ))
    log.addHandler(handler)
    log.setLevel(logging.INFO)

# ── Constants ──────────────────────────────────────────────────────────────
ET = pytz.timezone("America/New_York")
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "us_picks.json")

# Screening parameters
MIN_PRICE = 5.0           # Minimum stock price
MAX_PRICE = 500.0         # Maximum stock price (avoid BRK.A)
MIN_VOLUME_PREMARKET = 10000  # Minimum pre-market volume
MIN_GAP_PCT = 0.01        # Minimum 1% gap for consideration
MAX_GAP_PCT = 0.15        # Maximum 15% gap (avoid extreme)
MIN_MKT_CAP = 1_000_000_000  # $1B minimum market cap

# Scoring weights
WEIGHT_GAP = 0.25
WEIGHT_VOLUME = 0.25
WEIGHT_TREND = 0.25
WEIGHT_MOMENTUM = 0.25


def get_premarket_data(ticker: str) -> Optional[Dict]:
    """
    Fetch pre-market data for a ticker.
    
    Returns:
        {
            "symbol": ticker,
            "close_prev": float,
            "open_today": float,
            "high_premarket": float,
            "low_premarket": float,
            "volume_premarket": int,
            "gap_pct": float,
            "price_now": float,
        }
    """
    try:
        t = yf.Ticker(ticker)
        
        # Get pre-market data (today's session)
        df = t.history(period="2d", interval="1m", prepost=True)
        if df.empty or len(df) < 10:
            return None
        
        df.index = df.index.tz_convert(ET)
        
        # Today's date in ET
        today = datetime.now(ET).date()
        yesterday = today - timedelta(days=1)
        
        # Previous close
        prev_day_data = df[df.index.date == yesterday]
        if prev_day_data.empty:
            # Try last trading day
            prev_day_data = df[df.index.date < today]
            if prev_day_data.empty:
                return None
        
        close_prev = float(prev_day_data["Close"].iloc[-1].iloc[0]) if hasattr(prev_day_data["Close"].iloc[-1], "iloc") else float(prev_day_data["Close"].iloc[-1])
        
        # Pre-market data (before 09:30 ET)
        premarket = df[
            (df.index.date == today) &
            (df.index.time < dt_time(9, 30))
        ]
        
        if premarket.empty:
            return None
        
        open_today = float(premarket["Open"].iloc[0]) if len(premarket) > 0 else close_prev
        high_pm = float(premarket["High"].max()) if len(premarket) > 0 else close_prev
        low_pm = float(premarket["Low"].min()) if len(premarket) > 0 else close_prev
        volume_pm = int(premarket["Volume"].sum()) if "Volume" in premarket.columns else 0
        price_now = float(premarket["Close"].iloc[-1].iloc[0]) if hasattr(premarket["Close"].iloc[-1], "iloc") else float(premarket["Close"].iloc[-1])
        
        gap_pct = (open_today - close_prev) / close_prev if close_prev > 0 else 0
        
        # Get market cap info
        info = t.info
        mkt_cap = info.get("marketCap", 0)
        sector = info.get("sector", "Unknown")
        
        return {
            "symbol": ticker,
            "close_prev": close_prev,
            "open_today": open_today,
            "high_premarket": high_pm,
            "low_premarket": low_pm,
            "volume_premarket": volume_pm,
            "gap_pct": gap_pct,
            "price_now": price_now,
            "market_cap": mkt_cap,
            "sector": sector,
        }
    except Exception as e:
        log.debug(f"Error fetching {ticker}: {e}")
        return None


def calculate_score(data: Dict) -> float:
    """Calculate momentum score for a stock."""
    gap = data["gap_pct"]
    volume = data["volume_premarket"]
    price = data["price_now"]
    mkt_cap = data["market_cap"]
    
    # Normalize gap (0-15% → 0-100)
    gap_score = min(max(gap / MAX_GAP_PCT, 0), 1) * 100
    
    # Volume score (log scale, 10K-1M → 0-100)
    vol_score = min(np.log10(max(volume, 1)) / 5 * 100, 100)
    
    # Price score (avoid extremes, $5-$100 optimal)
    price_score = 100 - abs(price - 50) / 50 * 100
    price_score = max(0, min(100, price_score))
    
    # Market cap score ($1B-$100B optimal)
    cap_b = mkt_cap / 1e9
    cap_score = min(cap_b / 100 * 100, 100)
    
    # Combined score
    score = (
        WEIGHT_GAP * gap_score +
        WEIGHT_VOLUME * vol_score +
        WEIGHT_TREND * price_score +
        WEIGHT_MOMENTUM * cap_score
    )
    
    return score


def screen_stock(data: Dict) -> Optional[Dict]:
    """
    Apply filters to pre-market data.
    
    Returns pick dict if passes, None otherwise.
    """
    price = data["price_now"]
    gap = data["gap_pct"]
    vol = data["volume_premarket"]
    cap = data["market_cap"]
    
    # Price filter
    if price < MIN_PRICE or price > MAX_PRICE:
        return None
    
    # Gap filter
    if gap < MIN_GAP_PCT or gap > MAX_GAP_PCT:
        return None
    
    # Volume filter
    if vol < MIN_VOLUME_PREMARKET:
        return None
    
    # Market cap filter
    if cap < MIN_MKT_CAP:
        return None
    
    # Calculate score
    score = calculate_score(data)
    
    # Calculate entry zone
    # For gap-up: zone is previous close to current pre-market price
    entry_low = data["close_prev"] * 1.005  # Slight buffer above close
    entry_high = price * 1.01  # 1% above current
    
    return {
        "symbol": data["symbol"],
        "score": round(score, 1),
        "price": round(price, 2),
        "entry_low": round(entry_low, 2),
        "entry_high": round(entry_high, 2),
        "gap_pct": round(gap * 100, 2),
        "volume_premarket": vol,
        "market_cap": cap,
        "sector": data["sector"],
        "source": "premarket",
        "pm_metrics": {
            "close_prev": round(data["close_prev"], 2),
            "open_today": round(data["open_today"], 2),
            "high_pm": round(data["high_premarket"], 2),
            "low_pm": round(data["low_premarket"], 2),
        }
    }


def run_premarket_screen(max_stocks: int = 50, top_n: int = 10) -> List[Dict]:
    """
    Run full pre-market screening.
    
    Args:
        max_stocks: Max universe to screen (for speed)
        top_n: Number of picks to return
    
    Returns:
        List of top picks sorted by score.
    """
    now = datetime.now(ET)
    log.info(f"Starting pre-market screen at {now.strftime('%H:%M')} ET")
    
    # Get Sharia universe
    universe = get_sharia_universe()
    log.info(f"Universe: {len(universe)} Sharia-compliant stocks")
    
    # Limit for speed (sample random if too many)
    if len(universe) > max_stocks:
        import random
        random.seed(42)  # Reproducible
        screen_universe = random.sample(universe, max_stocks)
    else:
        screen_universe = universe
    
    log.info(f"Screening {len(screen_universe)} stocks...")
    
    picks = []
    screened = 0
    
    for ticker in screen_universe:
        data = get_premarket_data(ticker)
        screened += 1
        
        if data:
            pick = screen_stock(data)
            if pick:
                picks.append(pick)
                log.info(f"  ✅ {ticker}: score={pick['score']}, gap={pick['gap_pct']}%, vol={pick['volume_premarket']}")
        
        # Progress every 10
        if screened % 10 == 0:
            log.info(f"  Progress: {screened}/{len(screen_universe)} screened, {len(picks)} picks")
        
        # Rate limiting
        time.sleep(0.5)
    
    # Sort by score
    picks.sort(key=lambda x: x["score"], reverse=True)
    top_picks = picks[:top_n]
    
    log.info(f"Screen complete: {len(top_picks)} picks from {screened} screened")
    
    return top_picks


def save_picks(picks: List[Dict], filepath: str = OUTPUT_FILE):
    """Save picks to JSON file."""
    data = {
        "date": date.today().isoformat(),
        "time": datetime.now(ET).strftime("%H:%M:%S"),
        "timezone": "America/New_York",
        "mode": "premarket",
        "universe_size": len(get_sharia_universe()),
        "screened_count": len(picks),
        "picks": picks,
    }
    
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)
    
    log.info(f"Saved {len(picks)} picks to {filepath}")


def main():
    """Main entry point."""
    # Classify regime first
    try:
        regime = classify_premarket()
        regime_name = regime.get("regime", "NEUTRAL")
        log.info(f"Regime: {regime_name} — {regime.get('reason', '')}")
    except Exception as e:
        log.warning(f"Regime classification failed: {e}")
        regime_name = "NEUTRAL"
    
    # Check market status
    now = datetime.now(ET)
    market_open = dt_time(9, 30)
    
    if now.time() >= market_open:
        log.warning("Market already open — this is a pre-market screener")
    
    # Run screen
    picks = run_premarket_screen(max_stocks=50, top_n=10)
    
    # Save with regime info
    data = {
        "date": date.today().isoformat(),
        "time": datetime.now(ET).strftime("%H:%M:%S"),
        "timezone": "America/New_York",
        "mode": "premarket",
        "regime": regime_name,
        "universe_size": len(get_sharia_universe()),
        "screened_count": len(picks),
        "picks": picks,
    }
    
    with open(OUTPUT_FILE, "w") as f:
        json.dump(data, f, indent=2)
    
    log.info(f"Saved {len(picks)} picks to {OUTPUT_FILE}")
    
    # Print summary
    print(f"\n{'='*60}")
    print(f"PRE-MARKET SCREEN RESULTS")
    print(f"Regime: {regime_name}")
    print(f"{'='*60}")
    print(f"Time: {now.strftime('%H:%M')} ET")
    print(f"Picks: {len(picks)}")
    print(f"\n{'Rank':<5} {'Symbol':<8} {'Score':<8} {'Price':<10} {'Gap%':<8} {'Sector'}")
    print("-" * 60)
    for i, p in enumerate(picks, 1):
        print(f"{i:<5} {p['symbol']:<8} {p['score']:<8.1f} ${p['price']:<9.2f} {p['gap_pct']:<7.2f}% {p['sector']}")
    print(f"{'='*60}")
    
    return picks


if __name__ == "__main__":
    main()
