#!/usr/bin/env python3
"""
US Price Poller
Monitors screener picks for VWAP reclaim / breakout entry signals and open
positions for hard stop, trailing stop, and 15:45 hard-close alerts.
Runs every 5 minutes. Self-exits after 16:00 ET.
Start via cron at 09:30 Mon-Fri.
"""

import asyncio
import json
import logging
import os
import sys
import threading
import time as time_mod
from datetime import datetime, time
from pathlib import Path

import pytz
import requests
import yfinance as yf
import pandas as pd

# Alpaca API for orders and real-time data
from alpaca_api import AlpacaTrader
from us_market_regime import get_current_regime, get_regime_params, classify_intraday
from us_trade_logger import log_trade, close_trade, save_daily_summary, format_daily_report

# ─── Config ──────────────────────────────────────────────────────────────────

BOT_TOKEN  = os.environ.get("US_BOT_TOKEN", "")
CHAT_ID    = int(os.environ.get("US_CHAT_ID", "-5235925419"))
ET         = pytz.timezone("America/New_York")

BASE_DIR       = "/home/mino/us-exec"
PICKS_FILE     = f"{BASE_DIR}/us_picks.json"
POSITIONS_FILE = f"{BASE_DIR}/us_positions.json"
CAPITAL_FILE   = f"{BASE_DIR}/us_capital.json"
LOG_FILE       = f"{BASE_DIR}/us_poller.log"

# WebSocket price cache — populated by Alpaca WebSocket
_ws_price_cache: dict = {}
_ws_cache_lock = threading.Lock()
_ws_listener_thread: threading.Thread | None = None

FAST_INTERVAL   = 10           # seconds — position state watch (no network)
SLOW_INTERVAL   = 300          # seconds — price fetch + entry signals (yfinance/Alpaca)

# Base parameters (overridden by regime)
WIN_PCT         = 0.02         # 2% target
HARD_STOP_PCT   = 0.05         # 5% hard stop (tighter than TASI's 7%)
TRAIL_TRIGGER   = 0.02         # 2% trail trigger
TRAIL_STOP_PCT  = 0.03         # 3% trail stop
TIME_STOP_PCT   = 0.01         # 1% time stop
TIME_STOP_MINS  = 30           # 30 min time stop

# Entry parameters
MAX_POSITIONS   = 3
POSITION_PCT    = 0.40         # 40% of capital per position
ALT_POSITION_PCT = 0.25        # 25% for 3rd+ positions

HARD_CLOSE_TIME = time(15, 45)  # 15:45 ET hard close
ENTRY_CUTOFF    = time(14, 30)  # No new entries after 14:30
MARKET_OPEN     = time(9, 30)
MARKET_CLOSE    = time(16, 0)

# ─── Logging ─────────────────────────────────────────────────────────────────

for handler in logging.root.handlers[:]:
    logging.root.removeHandler(handler)
    handler.close()

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

# ─── Telegram ────────────────────────────────────────────────────────────────

def tg_send(text: str, chat_id: int = None, retries: int = 3):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    target = chat_id or CHAT_ID
    for attempt in range(retries):
        try:
            r = requests.post(
                url,
                json={"chat_id": target, "text": text, "parse_mode": "HTML"},
                timeout=10,
            )
            r.raise_for_status()
            return
        except Exception as e:
            log.error(f"tg_send failed (attempt {attempt+1}/{retries}): {e}")
            if attempt < retries - 1:
                time_mod.sleep(2)

# ─── Alpaca Trader ───────────────────────────────────────────────────────────

_trader: AlpacaTrader | None = None

def get_trader() -> AlpacaTrader:
    global _trader
    if _trader is None:
        _trader = AlpacaTrader()
    return _trader

# ─── Data / positions ────────────────────────────────────────────────────────

def load_picks() -> list:
    try:
        with open(PICKS_FILE) as f:
            data = json.load(f)
            return data.get("picks", [])
    except Exception:
        return []


def load_positions() -> dict:
    if not os.path.exists(POSITIONS_FILE):
        return {}
    with open(POSITIONS_FILE) as f:
        data = json.load(f)
        return data.get("positions", {})


def save_positions(positions: dict):
    with open(POSITIONS_FILE, "w") as f:
        json.dump({"positions": positions, "updated_at": datetime.now(ET).isoformat()}, f, indent=2)


def load_capital() -> float:
    if not os.path.exists(CAPITAL_FILE):
        return 100000.0  # Default paper trading capital
    with open(CAPITAL_FILE) as f:
        data = json.load(f)
        return data.get("available_capital", 100000.0)


def save_capital(data: dict):
    with open(CAPITAL_FILE, "w") as f:
        json.dump(data, f, indent=2)


# ─── Price fetch ─────────────────────────────────────────────────────────────

def fetch_data(symbol: str) -> tuple[float | None, pd.DataFrame | None]:
    """Fetch price and recent data for a symbol."""
    base = symbol.replace(".SR", "").replace("-", ".")
    
    # 1. Try Alpaca real-time first
    try:
        trader = get_trader()
        quote = trader.get_last_quote(base)
        if quote:
            price = (quote.get("bid_price", 0) + quote.get("ask_price", 0)) / 2
            if price > 0:
                # Get recent bars for VWAP calc
                df = yf.download(base, period="1d", interval="1m", progress=False)
                if not df.empty:
                    close_val = df["Close"].iloc[-1]
                    # Handle yfinance returning Series instead of scalar
                    price = float(close_val.iloc[0]) if hasattr(close_val, 'iloc') else float(close_val)
                    return price, df
    except Exception as e:
        log.debug(f"Alpaca fetch failed for {base}: {e}")
    
    # 2. Fallback to yfinance
    try:
        df = yf.download(base, period="1d", interval="1m", progress=False)
        if not df.empty:
            close_val = df["Close"].iloc[-1]
            # Handle yfinance returning Series instead of scalar
            price = float(close_val.iloc[0]) if hasattr(close_val, 'iloc') else float(close_val)
            return price, df
    except Exception as e:
        log.warning(f"yfinance fetch failed for {base}: {e}")
    
    return None, None


def calc_vwap(df: pd.DataFrame) -> float | None:
    try:
        df = df.copy()
        df["tp"] = (df["High"] + df["Low"] + df["Close"]) / 3
        cum_vol = df["Volume"].cumsum()
        if cum_vol.iloc[-1] == 0:
            return None
        return float((df["tp"] * df["Volume"]).cumsum().iloc[-1] / cum_vol.iloc[-1])
    except Exception:
        return None


def check_vwap_reclaim(df: pd.DataFrame, vwap: float) -> bool:
    if len(df) < 2:
        return False
    prev_close = float(df["Close"].iloc[-2])
    curr_close = float(df["Close"].iloc[-1])
    avg_vol = float(df["Volume"].mean())
    curr_vol = float(df["Volume"].iloc[-1])
    volume_ok = curr_vol > avg_vol * 0.5
    return prev_close < vwap < curr_close and volume_ok


def check_breakout(df: pd.DataFrame) -> bool:
    try:
        if len(df) < 6:
            return False
        prior_high = float(df["High"].iloc[:-1].max())
        curr_close = float(df["Close"].iloc[-1])
        avg_vol = float(df["Volume"].mean())
        curr_vol = float(df["Volume"].iloc[-1])
        return curr_close > prior_high and curr_vol > avg_vol * 1.5
    except Exception:
        return False


# ─── Order execution ─────────────────────────────────────────────────────────

def auto_buy(symbol: str, qty: int, price: float, cycle_n: int = 1, max_cyc: int = 2):
    """Execute buy order via Alpaca."""
    base = symbol.replace(".SR", "").replace("-", ".")
    
    try:
        trader = get_trader()
        
        # Check Sharia compliance
        from us_sharia_universe import is_sharia_compliant
        if not is_sharia_compliant(base):
            tg_send(f"⛔ {base} failed Sharia check — blocking buy")
            log.warning(f"Blocked non-Sharia buy: {base}")
            return False
        
        # Submit order
        result = trader.buy(base, qty=qty)
        
        if result.get("success"):
            # Save position
            positions = load_positions()
            positions[base] = {
                "symbol": base,
                "entry_price": price,
                "qty": qty,
                "entry_time": datetime.now(ET).isoformat(),
                "peak_price": price,
                "closed": False,
                "signal": "auto",
                "order_id": result.get("order_id", "?"),
                "cycle": cycle_n,
                "max_cycles": max_cyc,
            }
            save_positions(positions)
            
            # Update capital
            capital = load_capital()
            trade_value = price * qty
            capital_data = {
                "available_capital": max(0, capital - trade_value),
                "updated_at": datetime.now(ET).isoformat(),
            }
            save_capital(capital_data)
            
            tg_send(f"✅ <b>BUY {base}</b> {qty} shares @ {price:.2f}\nCycle {cycle_n}/{max_cyc}")
            log.info(f"Bought {base}: {qty}@{price:.2f} cycle={cycle_n}/{max_cyc}")
            return True
        else:
            tg_send(f"❌ <b>BUY FAILED {base}</b>\n{result.get('message', 'Unknown error')}")
            log.error(f"Buy failed: {base} — {result}")
            return False
            
    except Exception as e:
        log.error(f"auto_buy error: {e}")
        tg_send(f"❌ <b>BUY ERROR {base}</b>\n{e}")
        return False


def auto_sell(symbol: str, qty: int, reason: str):
    """Execute sell order via Alpaca."""
    base = symbol.replace(".SR", "").replace("-", ".")
    
    try:
        trader = get_trader()
        result = trader.sell(base, qty=qty)
        
        if result.get("success"):
            # Update position
            positions = load_positions()
            if base in positions:
                positions[base]["closed"] = True
                positions[base]["close_price"] = result.get("price", 0)
                positions[base]["close_time"] = datetime.now(ET).isoformat()
                positions[base]["close_reason"] = reason
                save_positions(positions)
                
                # Update capital
                capital = load_capital()
                returned = result.get("price", 0) * qty
                capital_data = {
                    "available_capital": capital + returned,
                    "updated_at": datetime.now(ET).isoformat(),
                }
                save_capital(capital_data)
            
            tg_send(f"💰 <b>SELL {base}</b> {qty} shares\n{reason}")
            log.info(f"Sold {base}: {qty} — {reason}")
            return True
        else:
            tg_send(f"❌ <b>SELL FAILED {base}</b>\n{result.get('message', 'Unknown error')}")
            return False
            
    except Exception as e:
        log.error(f"auto_sell error: {e}")
        tg_send(f"❌ <b>SELL ERROR {base}</b>\n{e}")
        return False


# ─── Core polling ────────────────────────────────────────────────────────────

_alerted: set = set()
cycles_today: dict = {}
consec_scratches: dict = {}
_prev_positions: dict = {}


def _reset_symbol_alerts(symbol: str):
    for suffix in ("_hard_stop", "_trail", "_time_stop", "_vwap_exit", "_target",
                   "_vwap_entry", "_breakout", "_gap_entry", "_zone_hold"):
        _alerted.discard(symbol + suffix)


def fast_poll():
    """
    Runs every 10 seconds — pure file I/O, no network.
    Detects position closes and fires cycle re-entry alerts.
    """
    global _prev_positions
    
    now = datetime.now(ET)
    now_time = now.time()
    
    # 15:45 hard close
    if now_time >= HARD_CLOSE_TIME and "hard_close" not in _alerted:
        positions = load_positions()
        open_syms = [s for s, p in positions.items() if isinstance(p, dict) and not p.get("closed")]
        if open_syms:
            tg_send(f"⏰ 15:45 HARD CLOSE — selling {', '.join(open_syms)}")
            for s in open_syms:
                result = auto_sell(s, positions[s].get("qty", 1), "⏰ 15:45 hard close")
                if result:
                    close_trade(s, positions[s].get("entry_price", 0), "Hard close 15:45")
        else:
            log.info("15:45 — no open positions")
        _alerted.add("hard_close")
        return
    
    positions = load_positions()
    
    for symbol, pos in positions.items():
        prev = _prev_positions.get(symbol, {})
        was_closed = prev.get("closed", True)
        is_closed = pos.get("closed", False)
        
        # Sell detected
        if not was_closed and is_closed:
            entry = pos.get("entry_price", 0)
            close_p = pos.get("close_price", 0)
            qty = pos.get("qty", "?")
            pct = (close_p - entry) / entry * 100 if entry else 0
            done = cycles_today.get(symbol, 0) + 1
            cycles_today[symbol] = done
            
            if pct >= WIN_PCT * 0.75:
                consec_scratches[symbol] = 0
                log.info(f"Sell detected (win): {symbol} exit={close_p:.2f} pct={pct:+.1f}% cycle={done}")
                if now_time < time(14, 30):
                    tg_send(f"✅ {symbol}: Win +{pct:.1f}% — cycle {done} done")
            else:
                consec_scratches[symbol] = consec_scratches.get(symbol, 0) + 1
                log.info(f"Sell detected (scratch): {symbol} pct={pct:+.1f}%")
                if consec_scratches[symbol] >= 2:
                    tg_send(f"⛔ {symbol}: 2 scratches — stopped for today")
                    cycles_today[symbol] = 999
        
        # Buy detected
        elif was_closed and not is_closed:
            _reset_symbol_alerts(symbol)
            log.info(f"Buy detected: {symbol}")
    
    _prev_positions = {k: dict(v) if isinstance(v, dict) else {} for k, v in positions.items()}


def slow_poll():
    """
    Runs every 5 minutes — fetches prices, monitors positions, scans for entries.
    Uses regime-based dynamic parameters.
    """
    now = datetime.now(ET)
    now_time = now.time()
    
    # Get current regime parameters
    regime = get_current_regime()
    r_params = regime.get("params", {})
    regime_name = regime.get("regime", "NEUTRAL")
    
    # Dynamic parameters from regime
    win_pct = r_params.get("target_pct", 0.02)
    hard_stop_pct = r_params.get("hard_stop", 0.05)
    trail_trigger = r_params.get("trail_trigger", 0.02)
    trail_stop_pct = r_params.get("trail_stop", 0.03)
    time_stop_pct = r_params.get("time_stop_pct", 0.01)
    time_stop_mins = r_params.get("time_stop_mins", 30)
    max_positions = r_params.get("max_positions", 3)
    position_pct = r_params.get("position_pct", 0.40)
    alt_position_pct = r_params.get("alt_position_pct", 0.25)
    
    log.info(f"Slow poll | Regime: {regime_name} | max_pos: {max_positions} | target: {win_pct*100:.1f}% | hard_stop: {hard_stop_pct*100:.1f}%")
    
    positions = load_positions()
    updated = False
    
    # Monitor open positions
    for symbol, pos in positions.items():
        # Skip non-dict entries (legacy/invalid data)
        if not isinstance(pos, dict):
            log.warning(f"Invalid position data for {symbol}: {type(pos).__name__}, skipping")
            continue
        if pos.get("closed"):
            continue
        
        price, df = fetch_data(symbol)
        if price is None:
            continue
        
        entry = pos.get("entry_price", 0)
        peak = pos.get("peak_price", entry)
        
        if price > peak:
            pos["peak_price"] = price
            peak = price
            updated = True
        
        gain_pct = (price - entry) / entry if entry else 0
        peak_pct = (peak - entry) / entry if entry else 0
        drop_from_peak = (peak - price) / peak if peak else 0
        
        mins_held = 0
        entry_time = pos.get("entry_time")
        if entry_time:
            try:
                et = datetime.fromisoformat(entry_time)
                if et.tzinfo is None:
                    et = et.replace(tzinfo=ET)
                mins_held = (now - et).total_seconds() / 60
            except Exception:
                pass
        
        key_stop = f"{symbol}_hard_stop"
        key_trail = f"{symbol}_trail"
        key_time = f"{symbol}_time_stop"
        key_target = f"{symbol}_target"
        
        qty = pos.get("qty", 1)
        
        # Hard stop
        if gain_pct <= -hard_stop_pct and key_stop not in _alerted:
            result = auto_sell(symbol, qty, f"🛑 Hard stop {int(-hard_stop_pct*100)}% | Entry: {entry:.2f} | Now: {price:.2f}")
            if result:
                close_trade(symbol, price, f"Hard stop {int(-hard_stop_pct*100)}%", regime=regime_name)
            _alerted.add(key_stop)
            cycles_today[symbol] = 999
        
        # Target
        elif gain_pct >= win_pct and key_target not in _alerted:
            result = auto_sell(symbol, qty, f"🎯 Target +{int(win_pct*100)}% | Entry: {entry:.2f} | Now: {price:.2f}")
            if result:
                close_trade(symbol, price, f"Target +{int(win_pct*100)}%", regime=regime_name)
            _alerted.add(key_target)
        
        # Trailing stop
        elif peak_pct >= trail_trigger and drop_from_peak >= trail_stop_pct and key_trail not in _alerted:
            result = auto_sell(symbol, qty, f"📉 Trail stop | Peak: {peak:.2f} | Now: {price:.2f}")
            if result:
                close_trade(symbol, price, f"Trail stop | Peak: {peak:.2f}", regime=regime_name)
            _alerted.add(key_trail)
        
        # Time stop
        elif mins_held >= time_stop_mins and gain_pct <= -time_stop_pct and key_time not in _alerted:
            result = auto_sell(symbol, qty, f"⏱ Time stop | Held {int(mins_held)} min | Entry: {entry:.2f} | Now: {price:.2f}")
            if result:
                close_trade(symbol, price, f"Time stop {int(mins_held)}min", regime=regime_name)
            _alerted.add(key_time)
    
    if updated:
        save_positions(positions)
    
    # Entry signals
    picks = load_picks()
    open_count = sum(1 for p in positions.values() if not p.get("closed"))
    
    if now_time >= HARD_CLOSE_TIME:
        log.info("Hard close active — no new entries")
        return
    
    if now_time >= ENTRY_CUTOFF:
        log.info("Entry cutoff passed — no new entries")
        return
    
    position_idx = 0
    
    for pick in picks[:5]:
        symbol = pick.get("symbol", "")
        if not symbol:
            continue
        base = symbol.replace(".SR", "").replace("-", ".")
        
        if base in positions and not positions[base].get("closed"):
            continue
        
        if open_count >= max_positions:
            break
        
        price, df = fetch_data(symbol)
        if price is None or df is None:
            continue
        
        e_hi = pick.get("entry_high", 0)
        e_lo = pick.get("entry_low", 0)
        if e_hi == 0 or e_lo == 0:
            e_hi = round(price * 1.01, 2)
            e_lo = round(price * 0.99, 2)
        
        position_idx += 1
        use_pct = position_pct if position_idx <= 2 else alt_position_pct
        
        # Gap-up / in-zone entry
        key_gap = f"{base}_gap_entry"
        if e_lo <= price <= e_hi * 1.02 and key_gap not in _alerted:
            if now_time <= time(10, 30):
                day_open = df["Open"].iloc[0] if not df.empty else price
                if price >= day_open * 0.998:
                    capital = load_capital()
                    qty = int((capital * use_pct) / price)
                    if qty > 0:
                        tg_send(f"📈 <b>ENTRY {base}</b>\nPrice: {price:.2f} | Zone: {e_lo}-{e_hi}\nSize: {int(use_pct*100)}% | Regime: {regime_name}")
                        _alerted.add(key_gap)
                        result = auto_buy(symbol, qty, price, 1, max_positions)
                        if result:
                            log_trade(symbol, "BUY", qty, price, signal="gap_up", regime=regime_name)
                        open_count += 1
        
        # VWAP reclaim
        vwap = calc_vwap(df)
        key_vwap = f"{base}_vwap_entry"
        if vwap and check_vwap_reclaim(df, vwap) and key_vwap not in _alerted:
            if open_count >= max_positions:
                continue
            position_idx += 1
            use_pct = position_pct if position_idx <= 2 else alt_position_pct
            capital = load_capital()
            qty = int((capital * use_pct) / price)
            if qty > 0:
                tg_send(f"📈 <b>VWAP ENTRY {base}</b>\nVWAP: {vwap:.2f} | Price: {price:.2f} | Regime: {regime_name}")
                _alerted.add(key_vwap)
                result = auto_buy(symbol, qty, price, 1, max_positions)
                if result:
                    log_trade(symbol, "BUY", qty, price, signal="vwap_reclaim", regime=regime_name)
                open_count += 1
        
        # Breakout
        key_break = f"{base}_breakout"
        if check_breakout(df) and key_break not in _alerted:
            if open_count >= max_positions:
                continue
            position_idx += 1
            use_pct = position_pct if position_idx <= 2 else alt_position_pct
            capital = load_capital()
            qty = int((capital * use_pct) / price)
            if qty > 0:
                tg_send(f"🚀 <b>BREAKOUT {base}</b>\nPrice: {price:.2f} | Regime: {regime_name}")
                _alerted.add(key_break)
                result = auto_buy(symbol, qty, price, 1, max_positions)
                if result:
                    log_trade(symbol, "BUY", qty, price, signal="breakout", regime=regime_name)
                open_count += 1


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    now_time = datetime.now(ET).time()
    if not (MARKET_OPEN <= now_time <= MARKET_CLOSE):
        log.info(f"Outside market hours ({now_time}) — exiting.")
        sys.exit(0)
    
    # Initialize regime
    try:
        regime = get_current_regime()
        r_params = regime.get("params", {})
        regime_name = regime.get("regime", "NEUTRAL")
    except Exception as e:
        log.warning(f"Regime init failed: {e} — using NEUTRAL")
        regime_name = "NEUTRAL"
        r_params = {}
    
    log.info("US Price poller started.")
    tg_send(
        f"🇺🇸 <b>US Poller Live</b>\n"
        f"Fast watch: {FAST_INTERVAL}s | Price scan: {SLOW_INTERVAL//60}min\n"
        f"Regime: {regime_name} | Target: {r_params.get('target_pct', 0.02)*100:.0f}% | Hard stop: {r_params.get('hard_stop', 0.05)*100:.0f}% | Trail: {r_params.get('trail_stop', 0.03)*100:.0f}%"
    )
    
    last_slow = 0.0
    last_regime_chk = 0.0
    daily_summary_saved = False
    
    while True:
        now_time = datetime.now(ET).time()
        
        if now_time > MARKET_CLOSE:
            log.info("Market closed — poller exiting.")
            tg_send("🔕 US Poller stopped (market closed).")
            break
        
        now_epoch = time_mod.time()
        
        # Fast poll
        try:
            fast_poll()
        except Exception as e:
            log.error(f"fast_poll error: {e}")
        
        # Slow poll
        if now_epoch - last_slow >= SLOW_INTERVAL:
            try:
                slow_poll()
                last_slow = now_epoch
                log.info("Slow poll done.")
            except Exception as e:
                import traceback
                log.error(f"slow_poll error: {e}\n{traceback.format_exc()}")
        
        # Regime re-check every 30 minutes
        if now_epoch - last_regime_chk >= 1800:
            try:
                classify_intraday()
                last_regime_chk = now_epoch
            except Exception as e:
                log.warning(f"Regime re-check failed: {e}")
        
        # Save daily summary at market close
        if now_time >= time(15, 55) and not daily_summary_saved:
            try:
                summary = save_daily_summary()
                tg_send(format_daily_report(summary))
                daily_summary_saved = True
            except Exception as e:
                log.error(f"Daily summary failed: {e}")
        
        time_mod.sleep(FAST_INTERVAL)


if __name__ == "__main__":
    main()
