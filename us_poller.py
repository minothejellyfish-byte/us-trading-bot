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
from us_market_regime import get_current_regime, get_regime_params, classify_intraday, is_market_open
from us_trade_logger import log_trade, close_trade, save_daily_summary, format_daily_report

# ─── Config ──────────────────────────────────────────────────────────────────

BOT_TOKEN  = os.environ.get("US_BOT_TOKEN", "")
CHAT_ID    = int(os.environ.get("US_CHAT_ID", "5529987063"))
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
    if not BOT_TOKEN:
        log.warning("Telegram bot token not set, skipping message send")
        return
    
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    target = chat_id or CHAT_ID
    
    # Validate text
    if not text or not isinstance(text, str):
        log.warning("Invalid text for tg_send, skipping")
        return
    
    # Limit text length to avoid Telegram API errors
    if len(text) > 4000:
        text = text[:4000] + "... (truncated)"
    
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
        try:
            _trader = AlpacaTrader()
        except Exception as e:
            log.error(f"Failed to initialize AlpacaTrader: {e}")
            raise
    return _trader

# ─── Data / positions ────────────────────────────────────────────────────────

def load_picks() -> list:
    try:
        if not os.path.exists(PICKS_FILE):
            log.warning(f"Picks file {PICKS_FILE} not found")
            return []
        with open(PICKS_FILE) as f:
            data = json.load(f)
            picks = data.get("picks", [])
            if not isinstance(picks, list):
                log.warning(f"Invalid picks data format in {PICKS_FILE}")
                return []
            # Validate each pick has required fields
            validated_picks = []
            for pick in picks:
                if isinstance(pick, dict) and "symbol" in pick:
                    validated_picks.append(pick)
                else:
                    log.warning(f"Skipping invalid pick data: {pick}")
            return validated_picks
    except Exception as e:
        log.error(f"Failed to load picks from {PICKS_FILE}: {e}")
        return []


def load_positions() -> dict:
    if not os.path.exists(POSITIONS_FILE):
        return {}
    try:
        with open(POSITIONS_FILE) as f:
            data = json.load(f)
            positions = data.get("positions", {})
            if not isinstance(positions, dict):
                log.warning(f"Invalid positions data format in {POSITIONS_FILE}")
                return {}
            return positions
    except Exception as e:
        log.error(f"Failed to load positions from {POSITIONS_FILE}: {e}")
        return {}


def save_positions(positions: dict):
    if not isinstance(positions, dict):
        log.error("Invalid positions data type for save_positions")
        return
    
    try:
        with open(POSITIONS_FILE, "w") as f:
            json.dump({"positions": positions, "updated_at": datetime.now(ET).isoformat()}, f, indent=2)
    except Exception as e:
        log.error(f"Failed to save positions to {POSITIONS_FILE}: {e}")
        import traceback
        log.debug(f"save_positions traceback: {traceback.format_exc()}")


def load_capital() -> float:
    if not os.path.exists(CAPITAL_FILE):
        return 100000.0  # Default paper trading capital
    try:
        with open(CAPITAL_FILE) as f:
            data = json.load(f)
            capital = data.get("available_capital", 100000.0)
            if not isinstance(capital, (int, float)):
                log.warning(f"Invalid capital data format in {CAPITAL_FILE}, using default")
                return 100000.0
            return float(capital)
    except Exception as e:
        log.error(f"Failed to load capital from {CAPITAL_FILE}: {e}")
        return 100000.0


def save_capital(data: dict):
    if not isinstance(data, dict):
        log.error("Invalid data type for save_capital")
        return
    
    try:
        with open(CAPITAL_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        log.error(f"Failed to save capital to {CAPITAL_FILE}: {e}")
        import traceback
        log.debug(f"save_capital traceback: {traceback.format_exc()}")


# ─── Price fetch ─────────────────────────────────────────────────────────────

def _extract_scalar(val):
    """Extract scalar float from yfinance value (Series or scalar)."""
    if val is None:
        return None
    if hasattr(val, 'iloc'):
        return float(val.iloc[0])
    if hasattr(val, 'item'):
        return float(val.item())
    return float(val)


def fetch_data(symbol: str) -> tuple[float | None, pd.DataFrame | None]:
    """Fetch price and recent data for a symbol.
    
    Priority (v4.12):
    1. Alpaca WebSocket (real-time, ~20ms latency) — PRIMARY
    2. Alpaca REST API (polling, ~200ms latency) — FALLBACK
    3. yfinance (fallback, ~15min delay) — LAST RESORT
    """
    base = symbol.replace(".SR", "").replace("-", ".")
    
    # 1. Try WebSocket FIRST (primary source)
    try:
        from us_alpaca_ws import get_ws_price_fast, get_ws_df
        ws_price = get_ws_price_fast(base)
        ws_df = get_ws_df(base)
        
        if ws_price > 0 and ws_df is not None and not ws_df.empty:
            log.debug(f"WS primary: {base} @ ${ws_price:.2f} ({len(ws_df)} bars)")
            return ws_price, ws_df
    except Exception as e:
        log.debug(f"WS primary failed for {base}: {e}")
    
    # 2. Try Alpaca REST API (fallback)
    try:
        trader = get_trader()
        trade = trader.get_last_trade(base)
        if trade:
            price = _extract_scalar(trade.get("price", 0))
            if price > 0:
                # Get recent bars for VWAP calc from REST
                bars = trader.get_bars(base, timeframe="1Min", limit=100)
                if bars:
                    df = pd.DataFrame(bars)
                    if not df.empty:
                        df = df.rename(columns={"o": "Open", "h": "High", "l": "Low", "c": "Close", "v": "Volume"})
                        log.debug(f"REST fallback: {base} @ ${price:.2f}")
                        return price, df
    except Exception as e:
        log.debug(f"REST fallback failed for {base}: {e}")
    
    # 3. yfinance (last resort)
    try:
        df = yf.download(base, period="1d", interval="1m", progress=False)
        if isinstance(df, pd.DataFrame) and not df.empty:
            close_val = df["Close"].iloc[-1]
            price = _extract_scalar(close_val)
            if price > 0:
                log.debug(f"yfinance last resort: {base} @ ${price:.2f}")
                return price, df
    except Exception as e:
        log.warning(f"yfinance fetch failed for {base}: {e}")
    
    log.warning(f"All price sources failed for {base}")
    return None, None


def calc_vwap(df: pd.DataFrame) -> float | None:
    try:
        if not isinstance(df, pd.DataFrame) or df.empty:
            return None
        
        # Handle multi-column yfinance format
        if isinstance(df.columns, pd.MultiIndex):
            # Extract columns with the ticker symbol
            df_flat = pd.DataFrame()
            for col in ["High", "Low", "Close", "Volume"]:
                if col in df.columns.get_level_values(0):
                    # Get the first sub-column (actual data)
                    df_flat[col] = df[col].iloc[:, 0] if isinstance(df[col], pd.DataFrame) else df[col]
            df = df_flat
        
        # Validate required columns exist
        required_cols = ["High", "Low", "Close", "Volume"]
        if not all(col in df.columns for col in required_cols):
            log.warning("Missing required columns for VWAP calculation")
            return None
        
        # Ensure all values are scalar floats
        for col in required_cols:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # Drop rows with NaN values
        df = df.dropna(subset=required_cols)
        if df.empty:
            return None
        
        tp = (df["High"] + df["Low"] + df["Close"]) / 3
        cum_vol = df["Volume"].cumsum()
        if cum_vol.iloc[-1] == 0:
            return None
        
        vwap = (tp * df["Volume"]).cumsum().iloc[-1] / cum_vol.iloc[-1]
        return float(vwap)
    except Exception as e:
        log.warning(f"VWAP calculation failed: {e}")
        return None


def check_vwap_reclaim(df: pd.DataFrame, vwap: float) -> bool:
    try:
        if len(df) < 2 or vwap is None or not isinstance(vwap, (int, float)):
            return False
        
        # Validate required columns exist
        required_cols = ["Close", "Volume"]
        if not all(col in df.columns for col in required_cols):
            log.warning("Missing required columns for VWAP reclaim check")
            return False
        
        # Extract scalars properly
        prev_close = _extract_scalar(df["Close"].iloc[-2])
        curr_close = _extract_scalar(df["Close"].iloc[-1])
        avg_vol = float(df["Volume"].mean()) if hasattr(df["Volume"].mean(), 'item') else float(df["Volume"].mean())
        curr_vol = _extract_scalar(df["Volume"].iloc[-1])
        volume_ok = curr_vol > avg_vol * 0.5 if avg_vol > 0 else False
        return prev_close < vwap < curr_close and volume_ok
    except Exception as e:
        log.warning(f"VWAP reclaim check failed: {e}")
        return False


def check_breakout(df: pd.DataFrame) -> bool:
    try:
        if len(df) < 6:
            return False
        
        # Validate required columns exist
        required_cols = ["High", "Close", "Volume"]
        if not all(col in df.columns for col in required_cols):
            log.warning("Missing required columns for breakout check")
            return False
        
        # Extract scalars properly
        prior_high = float(df["High"].iloc[:-1].max())
        curr_close = _extract_scalar(df["Close"].iloc[-1])
        avg_vol = float(df["Volume"].mean()) if hasattr(df["Volume"].mean(), 'item') else float(df["Volume"].mean())
        curr_vol = _extract_scalar(df["Volume"].iloc[-1])
        volume_condition = curr_vol > avg_vol * 1.5 if avg_vol > 0 else False
        return curr_close > prior_high and volume_condition
    except Exception as e:
        log.warning(f"Breakout check failed: {e}")
        return False


# ─── Order execution ─────────────────────────────────────────────────────────

def auto_buy(symbol: str, qty: int, price: float, cycle_n: int = 1, max_cyc: int = 2):
    """Execute buy order via Alpaca."""
    base = symbol.replace(".SR", "").replace("-", ".")
    
    try:
        # Validate inputs
        if qty <= 0 or price <= 0:
            log.error(f"Invalid buy parameters for {base}: qty={qty}, price={price}")
            return False
        
        trader = get_trader()
        
        # Check Sharia compliance
        from us_sharia_universe import is_sharia_compliant
        if not is_sharia_compliant(base):
            tg_send(f"⛔ {base} failed Sharia check — blocking buy")
            log.warning(f"Blocked non-Sharia buy: {base}")
            return False
        
        # Submit order
        result = trader.buy(base, qty=qty)
        
        if result.get("status") in ("pending_new", "accepted", "filled", "partially_filled"):
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
            error_msg = result.get('message', 'Unknown error')
            tg_send(f"❌ <b>BUY FAILED {base}</b>\n{error_msg}")
            log.error(f"Buy failed: {base} — {result}")
            return False
            
    except Exception as e:
        log.error(f"auto_buy error for {base}: {e}")
        import traceback
        log.debug(f"auto_buy traceback for {base}: {traceback.format_exc()}")
        tg_send(f"❌ <b>BUY ERROR {base}</b>\n{e}")
        return False


def auto_sell(symbol: str, qty: int, reason: str):
    """Execute sell order via Alpaca."""
    base = symbol.replace(".SR", "").replace("-", ".")
    
    try:
        # Validate inputs
        if qty <= 0:
            log.error(f"Invalid sell quantity for {base}: qty={qty}")
            return False
        
        trader = get_trader()
        result = trader.sell(base, qty=qty)
        
        if result.get("status") in ("pending_new", "accepted", "filled", "partially_filled"):
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
            error_msg = result.get('message', 'Unknown error')
            tg_send(f"❌ <b>SELL FAILED {base}</b>\n{error_msg}")
            return False
            
    except Exception as e:
        log.error(f"auto_sell error for {base}: {e}")
        import traceback
        log.debug(f"auto_sell traceback for {base}: {traceback.format_exc()}")
        tg_send(f"❌ <b>SELL ERROR {base}</b>\n{e}")
        return False


# ─── Core polling ────────────────────────────────────────────────────────────

_alerted: set = set()
_alerted_lock = threading.Lock()  # Thread-safe lock for _alerted set
cycles_today: dict = {}
consec_scratches: dict = {}
_prev_positions: dict = {}


def _reset_symbol_alerts(symbol: str):
    if not isinstance(symbol, str) or not symbol:
        log.warning("Invalid symbol for _reset_symbol_alerts")
        return
    
    with _alerted_lock:  # Thread-safe modification of _alerted set
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
    with _alerted_lock:  # Thread-safe check and modification
        hard_close_key = "hard_close"
        if now_time >= HARD_CLOSE_TIME and hard_close_key not in _alerted:
            positions = load_positions()
            if not isinstance(positions, dict):
                log.error("Invalid positions data in fast_poll")
                return
            
            open_syms = [s for s, p in positions.items() if isinstance(p, dict) and not p.get("closed")]
            if open_syms:
                tg_send(f"⏰ 15:45 HARD CLOSE — selling {', '.join(open_syms)}")
                for s in open_syms:
                    qty = positions[s].get("qty", 1)
                    if qty > 0:
                        result = auto_sell(s, qty, "⏰ 15:45 hard close")
                        if result:
                            entry_price = positions[s].get("entry_price", 0)
                            close_trade(s, entry_price, "Hard close 15:45")
            else:
                log.info("15:45 — no open positions")
            _alerted.add(hard_close_key)
            return
    
    positions = load_positions()
    if not isinstance(positions, dict):
        log.error("Invalid positions data in fast_poll")
        return
    
    for symbol, pos in positions.items():
        prev = _prev_positions.get(symbol, {})
        was_closed = prev.get("closed", True)
        is_closed = pos.get("closed", False)
        
        # Sell detected
        if not was_closed and is_closed:
            entry = pos.get("entry_price", 0)
            close_p = pos.get("close_price", 0)
            qty = pos.get("qty", 1)
            pct = (close_p - entry) / entry * 100 if entry and entry > 0 else 0
            done = cycles_today.get(symbol, 0) + 1
            if not isinstance(done, int) or done < 0:
                done = 1
            cycles_today[symbol] = done
            
            if pct >= WIN_PCT * 0.75:
                consec_scratches[symbol] = 0
                log.info(f"Sell detected (win): {symbol} exit={close_p:.2f} pct={pct:+.1f}% cycle={done}")
                if now_time < time(14, 30):
                    tg_send(f"✅ {symbol}: Win +{pct:.1f}% — cycle {done} done")
            else:
                consec_scratches[symbol] = consec_scratches.get(symbol, 0) + 1
                scratch_count = consec_scratches.get(symbol, 0)
                if not isinstance(scratch_count, int) or scratch_count < 0:
                    scratch_count = 1
                consec_scratches[symbol] = scratch_count
                log.info(f"Sell detected (scratch): {symbol} pct={pct:+.1f}%")
                if scratch_count >= 2:
                    tg_send(f"⛔ {symbol}: 2 scratches — stopped for today")
                    cycles_today[symbol] = 999
        
        # Buy detected
        elif was_closed and not is_closed:
            _reset_symbol_alerts(symbol)
            
            # Confirm with bookkeeper before logging (v4.12)
            try:
                from us_bookkeeper import get_positions, get_position
                bk_positions = get_positions()
                bk_pos = bk_positions.get(symbol, {})
                
                # Only log if bookkeeper confirms the position
                if bk_pos and not bk_pos.get("closed", True):
                    qty = bk_pos.get("qty", 0)
                    entry = bk_pos.get("entry_price", 0)
                    entry_time = bk_pos.get("entry_time", "")
                    
                    # Deduplicate with _alerted set
                    key_bought = f"{symbol}_bookkeeper_confirmed"
                    with _alerted_lock:
                        already_alerted = key_bought in _alerted
                    
                    if not already_alerted:
                        log.info(f"Buy detected: {symbol} (bookkeeper confirmed: {qty} @ ${entry:.2f})")
                        tg_send(f"📈 <b>ENTRY CONFIRMED</b>\n{symbol}: {qty} @ ${entry:.2f}\nBookkeeper: ✅")
                        with _alerted_lock:
                            _alerted.add(key_bought)
                else:
                    log.debug(f"Buy detected: {symbol} — bookkeeper not confirmed yet, skipping alert")
            except Exception as e:
                log.warning(f"Bookkeeper confirmation failed for {symbol}: {e}")
                # Fallback: just log without bookkeeper confirmation
                log.info(f"Buy detected: {symbol} (no bookkeeper confirmation)")
    
    # Update _prev_positions with full position state for next comparison
    try:
        _prev_positions = {
            k: {
                "closed": v.get("closed", False) if isinstance(v, dict) else False,
                "entry_price": v.get("entry_price", 0) if isinstance(v, dict) else 0,
                "qty": v.get("qty", 0) if isinstance(v, dict) else 0,
                "entry_time": v.get("entry_time", "") if isinstance(v, dict) else "",
            }
            for k, v in positions.items()
        }
    except Exception as e:
        log.warning(f"Failed to update _prev_positions: {e}")
        _prev_positions = {}


def slow_poll():
    """
    Runs every 5 minutes — fetches prices, monitors positions, scans for entries.
    Uses regime-based dynamic parameters.
    """
    now = datetime.now(ET)
    now_time = now.time()
    
    # Get current regime parameters
    try:
        regime = get_current_regime()
        r_params = regime.get("params", {})
        regime_name = regime.get("regime", "NEUTRAL")
    except Exception as e:
        log.warning(f"Regime init failed: {e} — using NEUTRAL")
        regime_name = "NEUTRAL"
        r_params = {}
    
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
    
    # Validate parameters
    if not all(isinstance(x, (int, float)) for x in [win_pct, hard_stop_pct, trail_trigger, trail_stop_pct, time_stop_pct, time_stop_mins, max_positions, position_pct, alt_position_pct]):
        log.error("Invalid regime parameters, using defaults")
        win_pct = 0.02
        hard_stop_pct = 0.05
        trail_trigger = 0.02
        trail_stop_pct = 0.03
        time_stop_pct = 0.01
        time_stop_mins = 30
        max_positions = 3
        position_pct = 0.40
        alt_position_pct = 0.25
    
    log.info(f"Slow poll | Regime: {regime_name} | max_pos: {max_positions} | target: {win_pct*100:.1f}% | hard_stop: {hard_stop_pct*100:.1f}%")
    
    positions = load_positions()
    if not isinstance(positions, dict):
        log.error("Invalid positions data in slow_poll")
        return
    
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
            log.warning(f"Failed to fetch price for {symbol}, skipping position monitoring")
            continue
        
        entry = pos.get("entry_price", 0)
        if entry == 0:
            log.warning(f"Position {symbol} has invalid entry price, skipping")
            continue
        
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
            except Exception as e:
                log.warning(f"Failed to parse entry time for {symbol}: {e}")
        
        key_stop = f"{symbol}_hard_stop"
        key_trail = f"{symbol}_trail"
        key_time = f"{symbol}_time_stop"
        key_target = f"{symbol}_target"
        
        qty = pos.get("qty", 1)
        if qty <= 0:
            log.warning(f"Position {symbol} has invalid quantity {qty}, skipping")
            continue
        
        # Hard stop
        with _alerted_lock:
            hard_stop_allowed = key_stop not in _alerted
        
        if gain_pct <= -hard_stop_pct and hard_stop_allowed:
            result = auto_sell(symbol, qty, f"🛑 Hard stop {int(-hard_stop_pct*100)}% | Entry: {entry:.2f} | Now: {price:.2f}")
            if result:
                close_trade(symbol, price, f"Hard stop {int(-hard_stop_pct*100)}%", regime=regime_name)
            with _alerted_lock:
                _alerted.add(key_stop)
            cycles_today[symbol] = 999
        
        # Target
        with _alerted_lock:
            target_allowed = key_target not in _alerted
        
        if gain_pct >= win_pct and target_allowed:
            result = auto_sell(symbol, qty, f"🎯 Target +{int(win_pct*100)}% | Entry: {entry:.2f} | Now: {price:.2f}")
            if result:
                close_trade(symbol, price, f"Target +{int(win_pct*100)}%", regime=regime_name)
            with _alerted_lock:
                _alerted.add(key_target)
        
        # Trailing stop
        with _alerted_lock:
            trail_allowed = key_trail not in _alerted
        
        if peak_pct >= trail_trigger and drop_from_peak >= trail_stop_pct and trail_allowed:
            result = auto_sell(symbol, qty, f"📉 Trail stop | Peak: {peak:.2f} | Now: {price:.2f}")
            if result:
                close_trade(symbol, price, f"Trail stop | Peak: {peak:.2f}", regime=regime_name)
            with _alerted_lock:
                _alerted.add(key_trail)
        
        # Tiered exits (NEW v4.12) — softer than TASI for paper trading
        try:
            from us_tier_exits import check_tier_exit, reset_tier_tracking
            
            # Only check tier exits if we haven't hit hard stop or target
            tier_keys = [key_stop, key_target]
            with _alerted_lock:
                tier_exit_blocked = any(k in _alerted for k in tier_keys)
            
            if not tier_exit_blocked:
                qty_to_sell, tier_reason = check_tier_exit(
                    symbol, entry, price, regime_name, qty
                )
                
                if qty_to_sell and qty_to_sell > 0:
                    # Check if we've already done this tier
                    tier_key = f"{symbol}_tier_exit"
                    with _alerted_lock:
                        tier_already_done = tier_key in _alerted
                    
                    if not tier_already_done:
                        result = auto_sell(symbol, qty_to_sell, tier_reason)
                        if result:
                            log.info(f"Tier exit executed: {tier_reason}")
                            tg_send(f"📊 <b>Tier Exit</b>\n{tier_reason}")
                            
                            # If full exit, mark as complete
                            if qty_to_sell >= qty:
                                close_trade(symbol, price, tier_reason, regime=regime_name)
                                with _alerted_lock:
                                    _alerted.add(tier_key)
                            else:
                                # Partial exit — update position qty
                                pos["qty"] = qty - qty_to_sell
                                updated = True
        except Exception as e:
            log.debug(f"Tier exit check failed for {symbol}: {e}")
        
        # Time stop
        with _alerted_lock:
            time_stop_allowed = key_time not in _alerted
        
        if mins_held >= time_stop_mins and gain_pct <= -time_stop_pct and time_stop_allowed:
            result = auto_sell(symbol, qty, f"⏱ Time stop | Held {int(mins_held)} min | Entry: {entry:.2f} | Now: {price:.2f}")
            if result:
                close_trade(symbol, price, f"Time stop {int(mins_held)}min", regime=regime_name)
            with _alerted_lock:
                _alerted.add(key_time)
        
        # VWAP breakdown exit (NEW in v4.12)
        key_vwap_exit = f"{symbol}_vwap_exit"
        with _alerted_lock:
            vwap_exit_allowed = key_vwap_exit not in _alerted
        
        if df is not None and vwap_exit_allowed:
            try:
                from us_exit_triggers import check_vwap_breakdown
                vwap = calc_vwap(df)
                if vwap:
                    should_exit, reason = check_vwap_breakdown(df, vwap, bars_required=3)
                    if should_exit:
                        result = auto_sell(symbol, qty, f"📉 VWAP breakdown | {reason}")
                        if result:
                            close_trade(symbol, price, f"VWAP breakdown: {reason}", regime=regime_name)
                        with _alerted_lock:
                            _alerted.add(key_vwap_exit)
            except Exception as e:
                log.debug(f"VWAP exit check failed for {symbol}: {e}")
        
        # Recovery score exit (NEW in v4.12)
        key_recovery = f"{symbol}_recovery"
        with _alerted_lock:
            recovery_exit_allowed = key_recovery not in _alerted
        
        if df is not None and recovery_exit_allowed:
            try:
                from us_exit_triggers import calc_recovery_score
                score, desc = calc_recovery_score(df)
                if score < 20:  # Very weak recovery
                    result = auto_sell(symbol, qty, f"📉 Weak recovery | Score: {score:.0f}/100 — {desc}")
                    if result:
                        close_trade(symbol, price, f"Weak recovery: {desc}", regime=regime_name)
                    with _alerted_lock:
                        _alerted.add(key_recovery)
            except Exception as e:
                log.debug(f"Recovery score check failed for {symbol}: {e}")
    
    if updated:
        save_positions(positions)
    
    # Entry signals
    picks = load_picks()
    if not isinstance(picks, list):
        log.error("Invalid picks data in slow_poll")
        return
    
    open_count = sum(1 for p in positions.values() if not p.get("closed"))
    
    if now_time >= HARD_CLOSE_TIME:
        log.info("Hard close active — no new entries")
        return
    
    if now_time >= ENTRY_CUTOFF:
        log.info("Entry cutoff passed — no new entries")
        return
    
    position_idx = 0
    
    for pick in picks[:5]:
        if not isinstance(pick, dict):
            continue
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
        with _alerted_lock:
            gap_entry_allowed = key_gap not in _alerted
        
        if e_lo <= price <= e_hi * 1.02 and gap_entry_allowed:
            if now_time <= time(10, 30):
                # Handle yfinance Series vs scalar logic
                try:
                    day_open_val = df["Open"].iloc[0] if not df.empty else price
                    day_open = float(day_open_val.iloc[0]) if hasattr(day_open_val, 'iloc') else float(day_open_val)
                except Exception as e:
                    log.warning(f"Failed to get day open price for {base}: {e}")
                    day_open = price
                
                if price >= day_open * 0.998:
                    capital = load_capital()
                    qty = int((capital * use_pct) / price) if price > 0 else 0
                    if qty > 0 and capital > 0 and use_pct > 0:
                        # Reset tier tracking on new entry
                        try:
                            from us_tier_exits import reset_tier_tracking
                            reset_tier_tracking(base)
                        except Exception:
                            pass
                        
                        tg_send(f"📈 <b>ENTRY {base}</b>\nPrice: {price:.2f} | Zone: {e_lo}-{e_hi}\nSize: {int(use_pct*100)}% | Regime: {regime_name}")
                        with _alerted_lock:
                            _alerted.add(key_gap)
                        result = auto_buy(symbol, qty, price, 1, max_positions)
                        if result:
                            log_trade(symbol, "BUY", qty, price, signal="gap_up", regime=regime_name)
                        open_count += 1
        
        # VWAP reclaim
        vwap = calc_vwap(df)
        key_vwap = f"{base}_vwap_entry"
        with _alerted_lock:
            vwap_entry_allowed = key_vwap not in _alerted
        
        if vwap and check_vwap_reclaim(df, vwap) and vwap_entry_allowed:
            if open_count >= max_positions:
                continue
            capital = load_capital()
            qty = int((capital * use_pct) / price) if price > 0 else 0
            if qty > 0 and capital > 0 and use_pct > 0:
                tg_send(f"📈 <b>VWAP ENTRY {base}</b>\nVWAP: {vwap:.2f} | Price: {price:.2f} | Regime: {regime_name}")
                with _alerted_lock:
                    _alerted.add(key_vwap)
                result = auto_buy(symbol, qty, price, 1, max_positions)
                if result:
                    log_trade(symbol, "BUY", qty, price, signal="vwap_reclaim", regime=regime_name)
                open_count += 1
        
        # Breakout
        key_break = f"{base}_breakout"
        with _alerted_lock:
            breakout_allowed = key_break not in _alerted
        
        if check_breakout(df) and breakout_allowed:
            if open_count >= max_positions:
                continue
            capital = load_capital()
            qty = int((capital * use_pct) / price) if price > 0 else 0
            if qty > 0 and capital > 0 and use_pct > 0:
                tg_send(f"🚀 <b>BREAKOUT {base}</b>\nPrice: {price:.2f} | Regime: {regime_name}")
                with _alerted_lock:
                    _alerted.add(key_break)
                result = auto_buy(symbol, qty, price, 1, max_positions)
                if result:
                    log_trade(symbol, "BUY", qty, price, signal="breakout", regime=regime_name)
                open_count += 1


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    now = datetime.now(ET)
    now_time = now.time()
    
    # Use proper market open/close detection instead of hardcoded hours
    try:
        market_is_open = is_market_open()
        if not market_is_open:
            log.info(f"Market is closed ({now_time}) — exiting.")
            sys.exit(0)
    except Exception as e:
        log.warning(f"Failed to check market status, using fallback: {e}")
        # Fallback to hardcoded hours if market detection fails
        if not (MARKET_OPEN <= now_time <= MARKET_CLOSE):
            log.info(f"Outside market hours ({now_time}) — exiting.")
            sys.exit(0)
    
    # Initialize regime
    try:
        regime = get_current_regime()
        if not isinstance(regime, dict):
            raise ValueError("Invalid regime data type")
        r_params = regime.get("params", {})
        if not isinstance(r_params, dict):
            raise ValueError("Invalid regime params data type")
        regime_name = regime.get("regime", "NEUTRAL")
        if not isinstance(regime_name, str):
            raise ValueError("Invalid regime name data type")
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
    
    # Validate regime parameters
    if not isinstance(r_params, dict):
        log.warning("Invalid regime parameters data type")
        r_params = {}
    
    last_slow = 0.0
    last_regime_chk = 0.0
    daily_summary_saved = False
    
    while True:
        now = datetime.now(ET)
        now_time = now.time()
        
        # Use proper market open/close detection
        try:
            market_is_open = is_market_open()
            if not market_is_open:
                log.info("Market closed — poller exiting.")
                tg_send("🔕 US Poller stopped (market closed).")
                break
        except Exception as e:
            log.warning(f"Failed to check market status in loop: {e}")
            # Fallback to hardcoded hours if market detection fails
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
            import traceback
            log.debug(f"fast_poll traceback: {traceback.format_exc()}")
        
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
                if summary:
                    report = format_daily_report(summary)
                    if report:
                        tg_send(report)
                    else:
                        log.warning("Daily report formatting returned no data")
                else:
                    log.warning("Daily summary returned no data")
                daily_summary_saved = True
            except Exception as e:
                log.error(f"Daily summary failed: {e}")
                import traceback
                log.debug(f"Daily summary traceback: {traceback.format_exc()}")
        
        time_mod.sleep(FAST_INTERVAL)


# ─── Daemon mode ────────────────────────────────────────────────────────────

PID_FILE = os.path.join(BASE_DIR, "us_poller.pid")

def write_pid():
    """Write current PID to file."""
    try:
        with open(PID_FILE, "w") as f:
            f.write(str(os.getpid()))
        log.info(f"PID written to {PID_FILE}")
    except Exception as e:
        log.error(f"Failed to write PID file {PID_FILE}: {e}")
        raise

def remove_pid():
    """Remove PID file on exit."""
    try:
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
            log.info(f"PID file removed: {PID_FILE}")
    except Exception as e:
        log.warning(f"Failed to remove PID file {PID_FILE}: {e}")

def check_pid():
    """Check if another poller instance is running."""
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE) as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)  # Check if process exists
            log.warning(f"Poller already running (PID {pid}) — exiting")
            sys.exit(0)
        except (ProcessLookupError, ValueError, OSError):
            # Stale PID file
            try:
                os.remove(PID_FILE)
                log.info("Removed stale PID file")
            except Exception:
                pass
    return True

if __name__ == "__main__":
    import signal
    
    # Handle daemon flag
    daemon_mode = "--daemon" in sys.argv
    
    if daemon_mode:
        # Check market hours before daemonizing
        now = datetime.now(ET)
        now_time = now.time()
        if not (MARKET_OPEN <= now_time <= MARKET_CLOSE):
            log.info(f"Outside market hours ({now_time}) — not starting daemon.")
            sys.exit(0)
        
        check_pid()
        write_pid()
        
        # Register cleanup on signals
        def signal_handler(signum, frame):
            log.info(f"Received signal {signum} — shutting down")
            remove_pid()
            sys.exit(0)
        
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
        
        log.info("Poller starting in daemon mode")
    
    try:
        main()
    finally:
        if daemon_mode:
            remove_pid()
