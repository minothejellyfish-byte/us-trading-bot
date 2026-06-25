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
import requests  # For Alpaca API
import pandas as pd
import numpy as np

from us_sharia_universe import get_sharia_universe
from us_market_regime import classify_premarket

# Simple cache for yfinance data
# ── Telegram Config ──────────────────────────────────────────────────────────
BOT_TOKEN = os.environ.get("US_BOT_TOKEN", "")
CHAT_ID = os.environ.get("US_CHAT_ID", "5529987063")

def tg_send(msg: str) -> None:
    """Send a message via Telegram bot."""
    if not BOT_TOKEN:
        return
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"}
        requests.post(url, json=payload, timeout=10)
    except Exception:
        pass


class YFinanceCache:
    def __init__(self, max_age_seconds=300):  # 5 minutes cache
        self.cache = {}
        self.max_age = max_age_seconds
    
    def get(self, key):
        if key in self.cache:
            data, timestamp = self.cache[key]
            if time.time() - timestamp < self.max_age:
                return data
            else:
                del self.cache[key]
        return None
    
    def set(self, key, data):
        self.cache[key] = (data, time.time())

# Global cache instance
_yf_cache = YFinanceCache()

# Load environment variables from .env file
_ENV_FILE = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_ENV_FILE):
    with open(_ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())

# Alpaca API Configuration
ALPACA_API_KEY = os.environ.get("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "")
ALPACA_DATA_URL = "https://data.alpaca.markets/v2"

if not ALPACA_API_KEY and os.path.exists(_ENV_FILE):
    try:
        with open(_ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    if key.strip() == "ALPACA_API_KEY":
                        ALPACA_API_KEY = value.strip()
                    elif key.strip() == "ALPACA_SECRET_KEY":
                        ALPACA_SECRET_KEY = value.strip()
    except Exception as e:
        log.warning(f"Could not load Alpaca credentials from .env: {e}")

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

# Screening parameters — EXTREME RISK for paper trading
# Will tune down after validating strategy

MIN_PRICE = 0.01          # EXTREME: Allow any price (was $0.50)
MAX_PRICE = 5000.0        # EXTREME: No upper limit (was $1000)
MIN_VOLUME_PREMARKET = 0  # EXTREME: Accept 0 volume — Alpaca provides real data (was 2000)
MIN_GAP_PCT = -0.05       # EXTREME: Accept gap-down up to -5% (was 0.1% min)
MAX_GAP_PCT = 0.50        # EXTREME: Accept gaps up to 50% (was 25%)
MIN_MKT_CAP = 10_000_000  # EXTREME: $10M minimum (was $100M)

# Scoring weights — favor momentum over safety
WEIGHT_GAP = 0.35         # EXTREME: Higher gap weight (was 0.20)
WEIGHT_VOLUME = 0.15      # EXTREME: Lower volume weight (was 0.25)
WEIGHT_TREND = 0.25       # EXTREME: Reduced (was 0.30)
WEIGHT_MOMENTUM = 0.25    # Same (was 0.25)


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
        # Check cache first
        cache_key = f"{ticker}_premarket"
        cached_data = _yf_cache.get(cache_key)
        if cached_data:
            log.debug(f"Cache hit for {ticker}")
            return cached_data
        
        t = yf.Ticker(ticker)
        
        # Get pre-market data (today's session)
        df = t.history(period="2d", interval="1m", prepost=True)
        log.debug(f"{ticker}: yfinance returned {len(df)} rows")
        if df.empty or len(df) < 10:
            log.warning(f"  ❌ {ticker}: yfinance returned empty/too few rows ({len(df)})")
            return None
        
        df.index = df.index.tz_convert(ET)
        
        # Today's date in ET
        today = datetime.now(ET).date()
        yesterday = today - timedelta(days=1)
        
        log.debug(f"{ticker}: today={today}, yesterday={yesterday}")
        log.debug(f"{ticker}: dates in data={sorted(set(df.index.date))}")
        
        # Previous close
        prev_day_data = df[df.index.date == yesterday]
        if prev_day_data.empty:
            # Try last trading day
            prev_day_data = df[df.index.date < today]
            if prev_day_data.empty:
                log.warning(f"  ❌ {ticker}: no previous day data found")
                return None
        
        close_prev = float(prev_day_data["Close"].iloc[-1].iloc[0]) if hasattr(prev_day_data["Close"].iloc[-1], "iloc") else float(prev_day_data["Close"].iloc[-1])
        
        # Pre-market data (before 09:30 ET)
        premarket = df[
            (df.index.date == today) &
            (df.index.time < dt_time(9, 30))
        ]
        
        log.debug(f"{ticker}: premarket rows={len(premarket)}")
        
        if premarket.empty:
            log.warning(f"  ❌ {ticker}: no premarket data (market not open yet or no data)")
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
        
        result = {
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
        
        # Cache the result
        _yf_cache.set(cache_key, result)
        log.info(f"  ✅ {ticker}: fetched premarket data (gap={gap_pct*100:.2f}%, vol={volume_pm})")
        return result
    except Exception as e:
        log.warning(f"  ❌ {ticker}: Exception fetching data: {e}")
        import traceback
        log.debug(f"Full traceback for {ticker}: {traceback.format_exc()}")
        return None


def get_premarket_data_alpaca(ticker: str) -> Optional[Dict]:
    """
    Fetch pre-market data using Alpaca API.
    Returns same format as get_premarket_data() for compatibility.
    """
    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        log.debug(f"Alpaca credentials not available, skipping")
        return None
    
    try:
        today = datetime.now(ET).date()
        yesterday = today - timedelta(days=1)
        
        # Format dates for Alpaca API
        start_str = f"{today}T04:00:00-04:00"
        end_str = f"{today}T09:30:00-04:00"
        
        headers = {
            "APCA-API-KEY-ID": ALPACA_API_KEY,
            "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY
        }
        
        url = f"{ALPACA_DATA_URL}/stocks/{ticker}/bars"
        params = {
            "timeframe": "1Min",
            "start": start_str,
            "end": end_str,
            "limit": 1000,
            "feed": "sip"
        }
        
        response = requests.get(url, headers=headers, params=params, timeout=10)
        
        if response.status_code != 200:
            log.debug(f"{ticker}: Alpaca API returned {response.status_code}")
            return None
        
        data = response.json()
        bars = data.get("bars", [])
        
        if not bars:
            log.debug(f"{ticker}: No pre-market bars from Alpaca")
            return None
        
        opens = [b["o"] for b in bars]
        highs = [b["h"] for b in bars]
        lows = [b["l"] for b in bars]
        closes = [b["c"] for b in bars]
        volumes = [b["v"] for b in bars]
        
        # Get previous close
        yesterday_end = f"{yesterday}T16:00:00-04:00"
        yesterday_start = f"{yesterday}T15:55:00-04:00"
        
        prev_url = f"{ALPACA_DATA_URL}/stocks/{ticker}/bars"
        prev_params = {
            "timeframe": "1Min",
            "start": yesterday_start,
            "end": yesterday_end,
            "limit": 10,
            "feed": "sip"
        }
        
        prev_response = requests.get(prev_url, headers=headers, params=prev_params, timeout=10)
        prev_close = closes[0]
        
        if prev_response.status_code == 200:
            prev_data = prev_response.json()
            prev_bars = prev_data.get("bars", [])
            if prev_bars:
                prev_close = prev_bars[-1]["c"]
        
        open_today = opens[0]
        gap_pct = (open_today - prev_close) / prev_close if prev_close > 0 else 0
        
        result = {
            "symbol": ticker,
            "close_prev": prev_close,
            "open_today": open_today,
            "high_premarket": max(highs),
            "low_premarket": min(lows),
            "volume_premarket": sum(volumes),
            "gap_pct": gap_pct,
            "price_now": closes[-1],
            "market_cap": 0,  # Alpaca doesn't provide market cap
            "sector": "Unknown",
        }
        
        log.info(f"  ✅ {ticker}: Alpaca premarket (gap={gap_pct*100:.2f}%, vol={sum(volumes)})")
        return result
        
    except Exception as e:
        log.warning(f"  ❌ {ticker}: Alpaca error: {e}")
        return None


def calculate_score(data: Dict, regime: str = "NEUTRAL") -> float:
    """Calculate momentum score for a stock with regime-based weights."""
    gap = data["gap_pct"]
    volume = data["volume_premarket"]
    price = data["price_now"]
    mkt_cap = data["market_cap"]
    
    # Regime-based weight adjustment - AGGRESSIVE for paper trading
    if regime == "BULL":
        # In bull market, momentum and trend matter more
        weight_gap = 0.20
        weight_volume = 0.20
        weight_trend = 0.30
        weight_momentum = 0.30
    elif regime == "BEAR":
        # In bear market, focus on quality and lower volatility
        weight_gap = 0.15
        weight_volume = 0.20
        weight_trend = 0.35
        weight_momentum = 0.30
    elif regime == "VOLATILE":
        # In volatile market, volume and market cap matter more
        weight_gap = 0.20
        weight_volume = 0.30
        weight_trend = 0.25
        weight_momentum = 0.25
    elif regime == "DEFENSIVE":
        # AGGRESSIVE: In defensive/flat market, look for ANY momentum
        weight_gap = 0.15
        weight_volume = 0.30
        weight_trend = 0.25
        weight_momentum = 0.30
    else:  # NEUTRAL or unknown
        # Default weights
        weight_gap = 0.20
        weight_volume = 0.25
        weight_trend = 0.30
        weight_momentum = 0.25
    
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
        weight_gap * gap_score +
        weight_volume * vol_score +
        weight_trend * price_score +
        weight_momentum * cap_score
    )
    
    return score


def screen_stock(data: Dict, regime: str = "NEUTRAL") -> Optional[Dict]:
    """
    Apply EXTREME RISK filters for paper trading.
    Will tune down after validating strategy.
    """
    price = data["price_now"]
    gap = data["gap_pct"]
    vol = data["volume_premarket"]
    cap = data["market_cap"]
    
    # Price filter — EXTREME
    if price < MIN_PRICE or price > MAX_PRICE:
        return None
    
    # Gap filter — EXTREME: accept gap-down up to -5%
    if gap < MIN_GAP_PCT or gap > MAX_GAP_PCT:
        log.info(f"  ❌ {data['symbol']}: gap={gap*100:.2f}% outside range [{MIN_GAP_PCT*100:.1f}%-{MAX_GAP_PCT*100:.1f}%]")
        return None
    
    # Volume filter — EXTREME: accept 0 volume (Alpaca provides real data)
    if vol < MIN_VOLUME_PREMARKET:
        log.info(f"  ❌ {data['symbol']}: volume={vol} below {MIN_VOLUME_PREMARKET}")
        return None
    
    # Market cap filter — EXTREME: accept 0 cap (Alpaca doesn't provide it)
    if cap < MIN_MKT_CAP and cap > 0:
        log.info(f"  ❌ {data['symbol']}: cap=${cap/1e9:.2f}B below ${MIN_MKT_CAP/1e9:.1f}B")
        return None
    elif cap == 0:
        log.info(f"  ⚠️ {data['symbol']}: cap unknown (Alpaca), accepting for paper trading")
    
    # Calculate score with regime adjustment
    score = calculate_score(data, regime)
    
    # EXTREME: Lower score threshold for paper trading — MORE PICKS = BETTER
    score_threshold = 20 if regime == "DEFENSIVE" else 25
    
    if score < score_threshold:
        log.info(f"  ❌ {data['symbol']}: score={score:.1f} below threshold {score_threshold}")
        return None
    
    # Log ALL passing stocks with scores (for analysis)
    log.info(f"  ✅ {data['symbol']}: score={score:.1f}, gap={gap*100:.2f}%, vol={vol}, price=${price:.2f}")
    
    # Calculate entry zone — EXTREME: wider zone for after-market
    entry_low = data["close_prev"] * 0.98  # 2% below close (catch dips)
    entry_high = price * 1.03  # 3% above current
    
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


def run_premarket_screen(max_stocks: int = None, top_n: int = 10, regime: str = "NEUTRAL") -> List[Dict]:
    """
    Run full pre-market screening.
    
    Args:
        max_stocks: Max universe to screen (None = screen all, for paper trading)
        top_n: Number of picks to return
        regime: Market regime for scoring adjustment
    
    Returns:
        List of top picks sorted by score.
    """
    now = datetime.now(ET)
    log.info(f"Starting AFTER-MARKET screen at {now.strftime('%H:%M')} ET with regime: {regime}")
    
    # Get Sharia universe
    universe = get_sharia_universe()
    log.info(f"Universe: {len(universe)} Sharia-compliant stocks")
    
    # Screen ALL stocks (no random sampling for paper trading)
    if max_stocks and len(universe) > max_stocks:
        import random
        random.seed(42)  # Reproducible
        screen_universe = random.sample(universe, max_stocks)
        log.info(f"WARNING: Limiting to {max_stocks} random stocks (speed mode)")
    else:
        screen_universe = universe
    
    log.info(f"Screening {len(screen_universe)} stocks with Alpaca ONLY...")
    
    picks = []
    screened = 0
    alpaca_failures = 0
    
    for ticker in screen_universe:
        # Use Alpaca ONLY for all data
        data = get_premarket_data_alpaca(ticker)
        if not data:
            alpaca_failures += 1
        screened += 1
        
        if data:
            pick = screen_stock(data, regime)
            if pick:
                picks.append(pick)
                log.info(f"  ✅ {ticker}: score={pick['score']}, gap={pick['gap_pct']}%, vol={pick['volume_premarket']}")
        
        # Progress every 10
        if screened % 10 == 0:
            log.info(f"  Progress: {screened}/{len(screen_universe)} screened, {len(picks)} picks, {alpaca_failures} Alpaca failures")
    
    # Sort by score
    picks.sort(key=lambda x: x["score"], reverse=True)
    top_picks = picks[:top_n]
    
    log.info(f"Screen complete: {len(top_picks)} picks from {screened} screened ({alpaca_failures} Alpaca failures)")
    
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
    regime_name = "NEUTRAL"
    try:
        regime = classify_premarket()
        regime_name = regime.get("regime", "NEUTRAL")
        log.info(f"Regime: {regime_name} — {regime.get('reason', '')}")
    except Exception as e:
        log.warning(f"Regime classification failed: {e}")
        import traceback
        log.debug(f"Regime classification traceback: {traceback.format_exc()}")
        regime_name = "NEUTRAL"
    
    # Check market status
    now = datetime.now(ET)
    market_open = dt_time(9, 30)
    
    if now.time() >= market_open:
        log.warning("Market already open — this is a pre-market screener")
    
    # Run screen — FULL UNIVERSE (no limit) for paper trading
    picks = run_premarket_screen(max_stocks=None, top_n=10, regime=regime_name)
    
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
    
    try:
        with open(OUTPUT_FILE, "w") as f:
            json.dump(data, f, indent=2)
        log.info(f"Saved {len(picks)} picks to {OUTPUT_FILE}")
    except Exception as e:
        log.error(f"Failed to save picks to {OUTPUT_FILE}: {e}")
        import traceback
        log.debug(f"Save picks traceback: {traceback.format_exc()}")
        raise
    
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
    
    # Send picks to Telegram
    if picks and BOT_TOKEN:
        emoji_regime = {"TRENDING": "🚀", "NEUTRAL": "⚖️", "DEFENSIVE": "🛡️"}.get(regime_name, "📊")
        lines = [f"{emoji_regime} <b>US Pre-Market Picks</b>\n📅 {date.today().isoformat()} | Regime: {regime_name} | {len(picks)} stocks"]
        for i, p in enumerate(picks, 1):
            gap_emoji = "📈" if p.get('gap_pct', 0) > 0 else "📉"
            lines.append(f"{i}. <b>{p['symbol']}</b> ${p['price']:.2f} | Score: {p['score']:.1f} | Gap: {gap_emoji}{p['gap_pct']:.2f}%")
        tg_send("\n".join(lines))
        log.info(f"Sent {len(picks)} picks to Telegram")
    
    return picks


if __name__ == "__main__":
    main()
