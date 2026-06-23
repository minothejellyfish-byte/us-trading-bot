#!/usr/bin/env python3
"""
US After-Market Screener — Sharia-Compliant
============================================

Runs AFTER market close to find momentum setups for the NEXT trading day.
Uses today's full trading session data to identify:
- Strong momentum candidates (high daily gain + volume)
- Breakout patterns (closed near high, volume spike)
- Continuation setups (strong trend with increasing volume)

Saves to us_picks.json for tomorrow's session.

Usage:
    python3 us_aftermarket_screener.py
"""

import json
import os
import time
import logging
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional
import pytz

import yfinance as yf
import requests
import pandas as pd
import numpy as np

from us_sharia_universe import get_sharia_universe
from us_market_regime import classify_premarket

# ── Logging ─────────────────────────────────────────────────────────────────
log = logging.getLogger("us_aftermarket")
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

# Load credentials
_ENV_FILE = os.path.join(os.path.dirname(__file__), ".env")
ALPACA_API_KEY = ""
ALPACA_SECRET_KEY = ""
if os.path.exists(_ENV_FILE):
    with open(_ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                k, v = key.strip(), value.strip()
                if k == "ALPACA_API_KEY":
                    ALPACA_API_KEY = v
                elif k == "ALPACA_SECRET_KEY":
                    ALPACA_SECRET_KEY = v

# EXTREME filters for paper trading
MIN_PRICE = 0.01
MAX_PRICE = 5000.0
MIN_GAP_PCT = -5.0      # Accept gap-down to -5%
MAX_GAP_PCT = 50.0      # Accept gaps up to 50%
MIN_MKT_CAP = 10_000_000

# After-market scoring: focus on day's performance
# gap_pct = daily change from open to close
# We want stocks that made strong moves today with volume


def get_yfinance_daily(ticker: str) -> Optional[Dict]:
    """Fetch today's trading data via yfinance (1m or 5m)."""
    try:
        t = yf.Ticker(ticker)
        # Get 5-day 5m data to cover today
        df = t.history(period="5d", interval="5m", prepost=True)
        if df.empty or len(df) < 5:
            # Try 1d interval as fallback
            df = t.history(period="5d", interval="1d")
            if df.empty or len(df) < 2:
                return None
            
            # Use daily data
            today = df.iloc[-1]
            prev = df.iloc[-2]
            
            daily_change = (float(today['Close']) - float(prev['Close'])) / float(prev['Close'])
            volume = int(today['Volume']) if 'Volume' in today else 0
            
            return {
                "symbol": ticker,
                "close_prev": float(prev['Close']),
                "open_today": float(today['Open']),
                "high_today": float(today['High']),
                "low_today": float(today['Low']),
                "close_today": float(today['Close']),
                "volume_today": volume,
                "gap_pct": (float(today['Open']) - float(prev['Close'])) / float(prev['Close']),
                "daily_change_pct": daily_change,
                "price_now": float(today['Close']),
                "market_cap": 0,
                "sector": "Unknown",
                "source": "yfinance_daily"
            }
        
        df.index = df.index.tz_convert(ET)
        
        # Get today's date in ET
        now = datetime.now(ET)
        today_date = now.date()
        
        # Filter today's regular hours (9:30-16:00 ET)
        today_data = df[
            (df.index.date == today_date) &
            (df.index.time >= datetime.strptime("09:30", "%H:%M").time()) &
            (df.index.time <= datetime.strptime("16:00", "%H:%M").time())
        ]
        
        if today_data.empty:
            # Try yesterday's data (for Friday after close, might be Thursday data)
            yesterday = today_date - timedelta(days=1)
            today_data = df[
                (df.index.date == yesterday) &
                (df.index.time >= datetime.strptime("09:30", "%H:%M").time()) &
                (df.index.time <= datetime.strptime("16:00", "%H:%M").time())
            ]
            if not today_data.empty:
                today_date = yesterday  # Update today_date to the actual data date
            if today_data.empty:
                # Try any trading day in the last 5 days
                for days_back in range(1, 6):
                    check_date = today_date - timedelta(days=days_back)
                    check_data = df[
                        (df.index.date == check_date) &
                        (df.index.time >= datetime.strptime("09:30", "%H:%M").time()) &
                        (df.index.time <= datetime.strptime("16:00", "%H:%M").time())
                    ]
                    if not check_data.empty:
                        today_data = check_data
                        today_date = check_date
                        break
            
            if today_data.empty:
                return None
        
        # Get previous close
        prev_date = today_date - timedelta(days=1)
        prev_data = df[
            (df.index.date == prev_date) &
            (df.index.time >= datetime.strptime("09:30", "%H:%M").time()) &
            (df.index.time <= datetime.strptime("16:00", "%H:%M").time())
        ]
        
        if prev_data.empty:
            # Find last trading day
            all_dates = sorted(set(df.index.date))
            trading_dates = [d for d in all_dates 
                if df[df.index.date == d].index.time.min() <= datetime.strptime("16:00", "%H:%M").time()]
            if len(trading_dates) >= 2:
                prev_date = trading_dates[-2]
                prev_data = df[df.index.date == prev_date]
        
        close_prev = float(prev_data['Close'].iloc[-1]) if not prev_data.empty else float(today_data['Open'].iloc[0])
        
        open_today = float(today_data['Open'].iloc[0])
        high_today = float(today_data['High'].max())
        low_today = float(today_data['Low'].min())
        close_today = float(today_data['Close'].iloc[-1])
        volume_today = int(today_data['Volume'].sum()) if 'Volume' in today_data.columns else 0
        
        gap_pct = (open_today - close_prev) / close_prev if close_prev > 0 else 0
        daily_change_pct = (close_today - close_prev) / close_prev if close_prev > 0 else 0
        intraday_range_pct = (high_today - low_today) / open_today if open_today > 0 else 0
        close_to_high_pct = (close_today - high_today) / high_today if high_today > 0 else 0
        
        # Get market cap from info
        try:
            info = t.info
            mkt_cap = info.get("marketCap", 0)
            sector = info.get("sector", "Unknown")
        except:
            mkt_cap = 0
            sector = "Unknown"
        
        return {
            "symbol": ticker,
            "close_prev": close_prev,
            "open_today": open_today,
            "high_today": high_today,
            "low_today": low_today,
            "close_today": close_today,
            "volume_today": volume_today,
            "gap_pct": gap_pct,
            "daily_change_pct": daily_change_pct,
            "intraday_range_pct": intraday_range_pct,
            "close_to_high_pct": close_to_high_pct,
            "price_now": close_today,
            "market_cap": mkt_cap,
            "sector": sector,
            "source": "yfinance_intraday",
            "date": today_date.isoformat()
        }
        
    except Exception as e:
        log.debug(f"  ❌ {ticker}: yfinance error: {e}")
        return None


def get_alpaca_daily(ticker: str) -> Optional[Dict]:
    """Fetch today's trading data via Alpaca (daily bars)."""
    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        return None
    
    try:
        now = datetime.now(ET)
        today = now.date()
        yesterday = today - timedelta(days=1)
        
        headers = {
            "APCA-API-KEY-ID": ALPACA_API_KEY,
            "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY
        }
        
        # Get daily bars for last 5 days
        url = f"https://data.alpaca.markets/v2/stocks/{ticker}/bars"
        params = {
            "timeframe": "1Day",
            "start": (today - timedelta(days=7)).isoformat(),
            "end": today.isoformat(),
            "limit": 10,
            "feed": "sip"
        }
        
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        if resp.status_code != 200:
            return None
        
        data = resp.json()
        bars = data.get("bars", [])
        if not bars or len(bars) < 2:
            return None
        
        # Use last two bars
        today_bar = bars[-1]
        prev_bar = bars[-2]
        
        open_today = today_bar["o"]
        close_prev = prev_bar["c"]
        close_today = today_bar["c"]
        high_today = today_bar["h"]
        low_today = today_bar["l"]
        volume_today = today_bar["v"]
        
        gap_pct = (open_today - close_prev) / close_prev if close_prev > 0 else 0
        daily_change_pct = (close_today - close_prev) / close_prev if close_prev > 0 else 0
        intraday_range_pct = (high_today - low_today) / open_today if open_today > 0 else 0
        close_to_high_pct = (close_today - high_today) / high_today if high_today > 0 else 0
        
        return {
            "symbol": ticker,
            "close_prev": close_prev,
            "open_today": open_today,
            "high_today": high_today,
            "low_today": low_today,
            "close_today": close_today,
            "volume_today": volume_today,
            "gap_pct": gap_pct,
            "daily_change_pct": daily_change_pct,
            "intraday_range_pct": intraday_range_pct,
            "close_to_high_pct": close_to_high_pct,
            "price_now": close_today,
            "market_cap": 0,
            "sector": "Unknown",
            "source": "alpaca_daily",
            "date": today_bar["t"][:10]
        }
        
    except Exception as e:
        log.debug(f"  ❌ {ticker}: Alpaca error: {e}")
        return None


def get_stock_data(ticker: str) -> Optional[Dict]:
    """Get stock data — try yfinance first, then Alpaca."""
    # Try yfinance
    data = get_yfinance_daily(ticker)
    if data:
        return data
    
    # Fallback to Alpaca
    data = get_alpaca_daily(ticker)
    if data:
        return data
    
    return None


def calculate_aftermarket_score(data: Dict, regime: str = "NEUTRAL") -> float:
    """Calculate momentum score for after-market screening.
    
    After-market scoring focuses on:
    1. Daily change (strong momentum)
    2. Volume (confirming the move)
    3. Close-to-high ratio (strength into close)
    4. Intraday range (volatility/expansion)
    """
    
    daily_change = data.get("daily_change_pct", 0)
    volume = data.get("volume_today", 0)
    price = data.get("price_now", 0)
    mkt_cap = data.get("market_cap", 0)
    close_to_high = data.get("close_to_high_pct", -0.05)
    intraday_range = data.get("intraday_range_pct", 0.02)
    
    # Regime-based weight adjustment
    if regime == "TRENDING":
        w_change = 0.40
        w_volume = 0.15
        w_strength = 0.25  # close to high
        w_range = 0.20
    elif regime == "DEFENSIVE":
        w_change = 0.25
        w_volume = 0.30
        w_strength = 0.30
        w_range = 0.15
    elif regime == "VOLATILE":
        w_change = 0.35
        w_volume = 0.25
        w_strength = 0.20
        w_range = 0.20
    else:  # NEUTRAL
        w_change = 0.35
        w_volume = 0.20
        w_strength = 0.25
        w_range = 0.20
    
    # Daily change score: reward strong moves, penalize extreme >20%
    # -20% to +20% → map to 0-100
    change_score = max(0, min(100, (daily_change + 0.20) / 0.40 * 100))
    
    # Volume score (log scale)
    vol_score = min(np.log10(max(volume, 1)) / 7 * 100, 100)
    
    # Strength score: closed near high = good for continuation
    # close_to_high is negative (close < high), so -5% to 0% → map to 0-100
    # 0% = closed at high = 100 score, -10% = closed 10% below high = 0 score
    strength_score = max(0, min(100, (close_to_high + 0.10) / 0.10 * 100))
    
    # Range score: reward moderate range (1%-15%)
    # Too little = no momentum, too much = blow-off
    if intraday_range < 0.01:
        range_score = intraday_range / 0.01 * 50  # 0-50
    elif intraday_range < 0.15:
        range_score = 50 + (intraday_range - 0.01) / 0.14 * 50  # 50-100
    else:
        range_score = max(0, 100 - (intraday_range - 0.15) / 0.15 * 50)
    
    # Market cap score ($10M-$500B optimal)
    cap_b = mkt_cap / 1e9
    if cap_b == 0:
        cap_score = 50  # Unknown = neutral
    else:
        cap_score = min(cap_b / 500 * 100, 100)
    
    # Price score: avoid sub-$1 and >$500
    if price < 1:
        price_score = price * 50  # 0-50
    elif price < 500:
        price_score = 50 + (price - 1) / 499 * 50  # 50-100
    else:
        price_score = max(0, 100 - (price - 500) / 500 * 50)
    
    # Combined score
    score = (
        w_change * change_score +
        w_volume * vol_score +
        w_strength * strength_score +
        w_range * range_score
    ) * 0.90 + 0.10 * (cap_score * 0.5 + price_score * 0.5)
    
    return score


def screen_stock(data: Dict, regime: str = "NEUTRAL", score_threshold: float = 25) -> Optional[Dict]:
    """Apply after-market filters."""
    price = data["price_now"]
    daily_change = data["daily_change_pct"]
    vol = data["volume_today"]
    cap = data["market_cap"]
    
    # Price filter
    if price < MIN_PRICE or price > MAX_PRICE:
        return None
    
    # Gap filter: accept -5% to +50%
    gap = data["gap_pct"]
    if gap < (MIN_GAP_PCT / 100) or gap > (MAX_GAP_PCT / 100):
        log.debug(f"  ❌ {data['symbol']}: gap={gap*100:.2f}% outside range")
        return None
    
    # Volume filter: require at least 1,000 shares
    if vol < 1000:
        log.debug(f"  ❌ {data['symbol']}: volume={vol} below 1000")
        return None
    
    # Market cap filter (allow unknown)
    if cap > 0 and cap < MIN_MKT_CAP:
        log.debug(f"  ❌ {data['symbol']}: cap=${cap/1e9:.2f}B below min")
        return None
    
    # Calculate score
    score = calculate_aftermarket_score(data, regime)
    
    # EXTREME: Lower threshold for paper trading
    threshold = score_threshold
    if regime == "DEFENSIVE":
        threshold = max(15, score_threshold - 5)
    
    if score < threshold:
        log.debug(f"  ❌ {data['symbol']}: score={score:.1f} below {threshold}")
        return None
    
    log.info(f"  ✅ {data['symbol']}: score={score:.1f}, change={daily_change*100:.2f}%, vol={vol:,}, price=${price:.2f}")
    
    # Entry zone for tomorrow (Monday): based on today's close
    # Tighter zone for continuation plays
    entry_low = data["close_today"] * 0.99  # 1% below close
    entry_high = data["close_today"] * 1.02  # 2% above close (for breakout)
    
    return {
        "symbol": data["symbol"],
        "score": round(score, 1),
        "price": round(price, 2),
        "entry_low": round(entry_low, 2),
        "entry_high": round(entry_high, 2),
        "gap_pct": round(gap * 100, 2),
        "daily_change_pct": round(daily_change * 100, 2),
        "volume_today": vol,
        "market_cap": cap,
        "sector": data["sector"],
        "source": data.get("source", "unknown"),
        "screen_date": data.get("date", date.today().isoformat()),
        "metrics": {
            "close_prev": round(data["close_prev"], 2),
            "open_today": round(data["open_today"], 2),
            "high_today": round(data["high_today"], 2),
            "low_today": round(data["low_today"], 2),
            "close_today": round(data["close_today"], 2),
            "intraday_range_pct": round(data["intraday_range_pct"] * 100, 2),
            "close_to_high_pct": round(data["close_to_high_pct"] * 100, 2)
        }
    }


def run_aftermarket_screen(top_n: int = 10, regime: str = "NEUTRAL", score_threshold: float = 25) -> List[Dict]:
    """Run full after-market screening."""
    now = datetime.now(ET)
    log.info(f"Starting AFTER-MARKET screen at {now.strftime('%H:%M')} ET with regime: {regime}")
    
    # Get Sharia universe
    universe = get_sharia_universe()
    log.info(f"Universe: {len(universe)} Sharia-compliant stocks")
    
    picks = []
    screened = 0
    failures = 0
    
    for ticker in universe:
        data = get_stock_data(ticker)
        screened += 1
        
        if data:
            pick = screen_stock(data, regime, score_threshold)
            if pick:
                picks.append(pick)
        else:
            failures += 1
        
        if screened % 20 == 0:
            log.info(f"  Progress: {screened}/{len(universe)} screened, {len(picks)} picks, {failures} failures")
    
    # Sort by score
    picks.sort(key=lambda x: x["score"], reverse=True)
    top_picks = picks[:top_n]
    
    log.info(f"Screen complete: {len(top_picks)} picks from {screened} screened ({failures} failures)")
    
    return top_picks


def save_picks(picks: List[Dict], filepath: str = OUTPUT_FILE):
    """Save picks to JSON file."""
    now = datetime.now(ET)
    tomorrow = now.date() + timedelta(days=1)
    # Skip weekend if needed
    if tomorrow.weekday() >= 5:  # Saturday=5, Sunday=6
        days_to_monday = 7 - tomorrow.weekday()
        tomorrow = tomorrow + timedelta(days=days_to_monday)
    
    data = {
        "generated_at": now.isoformat(),
        "for_date": tomorrow.isoformat(),
        "timezone": "America/New_York",
        "mode": "aftermarket",
        "universe_size": len(get_sharia_universe()),
        "pick_count": len(picks),
        "picks": picks,
    }
    
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)
    
    log.info(f"Saved {len(picks)} picks to {filepath} (for {tomorrow.isoformat()})")


def main():
    """Main entry point."""
    # Classify regime
    regime_name = "NEUTRAL"
    try:
        regime = classify_premarket()
        regime_name = regime.get("regime", "NEUTRAL")
        log.info(f"Regime: {regime_name} — {regime.get('reason', '')}")
    except Exception as e:
        log.warning(f"Regime classification failed: {e}")
        regime_name = "NEUTRAL"
    
    # Run screen
    picks = run_aftermarket_screen(top_n=10, regime=regime_name, score_threshold=25)
    
    # Save
    save_picks(picks)
    
    # Print summary
    now = datetime.now(ET)
    print(f"\n{'='*70}")
    print(f"AFTER-MARKET SCREEN RESULTS")
    print(f"Regime: {regime_name}")
    print(f"{'='*70}")
    print(f"Time: {now.strftime('%H:%M')} ET")
    print(f"Picks: {len(picks)} for tomorrow")
    print(f"\n{'Rank':<5} {'Symbol':<8} {'Score':<8} {'Price':<10} {'Day Change':<12} {'Volume':<15} {'Sector'}")
    print("-" * 70)
    for i, p in enumerate(picks, 1):
        vol_str = f"{p['volume_today']:,}"
        print(f"{i:<5} {p['symbol']:<8} {p['score']:<8.1f} ${p['price']:<9.2f} {p['daily_change_pct']:>+6.2f}%{'':<5} {vol_str:<15} {p['sector']}")
    print(f"{'='*70}")
    
    return picks


if __name__ == "__main__":
    main()
