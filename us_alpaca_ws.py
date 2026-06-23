#!/usr/bin/env python3
"""
US Alpaca WebSocket Logger v2 (alpaca-py)
========================================
Logs real-time trade data from Alpaca WebSocket using alpaca-py SDK.

Features:
- Real-time price updates
- Trade execution tracking
- Quote monitoring
- Bar (candle) data

Output:
- history/alpaca_ws_{date}.jsonl — Real-time tick data

Author: Mino (kimi-k2.6)
Version: 5.0
Date: 2026-06-23
"""

import json
import os
import asyncio
import threading
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional

import pytz

# ─── Config ─────────────────────────────────────────────────────────────────

ET = pytz.timezone("America/New_York")
BASE_DIR = Path("/home/mino/us-exec")
HISTORY_DIR = BASE_DIR / "history"
HISTORY_DIR.mkdir(exist_ok=True)

WS_LOG = HISTORY_DIR / f"alpaca_ws_{date.today().isoformat()}.jsonl"

# Load credentials from .env file
_ENV_FILE = BASE_DIR / ".env"
if _ENV_FILE.exists():
    with open(_ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ[key] = value

ALPACA_API_KEY = os.environ.get("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "")
ALPACA_PAPER = os.environ.get("ALPACA_PAPER", "true").lower() == "true"

# ─── Alpaca-py imports ──────────────────────────────────────────────────────

try:
    from alpaca.data.live import StockDataStream
    from alpaca.data.models import Trade, Quote, Bar
    ALPACA_AVAILABLE = True
except ImportError:
    ALPACA_AVAILABLE = False
    print("alpaca-py not installed")

# ─── WebSocket Handler ──────────────────────────────────────────────────────

class AlpacaWSLogger:
    """Alpaca WebSocket data logger using alpaca-py."""

    def __init__(self, api_key: str, secret_key: str, paper: bool = True):
        self.api_key = api_key
        self.secret_key = secret_key
        self.paper = paper
        self.stream: Optional[StockDataStream] = None
        self.running = False
        self.thread = None
        self.subscribed_symbols = set()

        # In-memory caches
        self._price_cache: Dict[str, float] = {}
        self._bar_cache: Dict[str, List[Dict]] = {}
        self._lock = threading.Lock()

    def _log_tick(self, tick: Dict):
        """Append tick to daily log file."""
        tick["logged_at"] = datetime.now(ET).isoformat()
        with open(WS_LOG, "a") as f:
            f.write(json.dumps(tick) + "\n")

    def _make_tick(self, data, tick_type: str) -> Dict:
        """Convert alpaca-py model to dict."""
        if isinstance(data, dict):
            d = dict(data)
        else:
            d = {
                "symbol": getattr(data, "symbol", ""),
                "timestamp": str(getattr(data, "timestamp", "")),
            }
            if tick_type == "trade":
                d["price"] = float(getattr(data, "price", 0))
                d["size"] = int(getattr(data, "size", 0))
            elif tick_type == "quote":
                d["bid"] = float(getattr(data, "bid_price", 0))
                d["ask"] = float(getattr(data, "ask_price", 0))
                d["bid_size"] = int(getattr(data, "bid_size", 0))
                d["ask_size"] = int(getattr(data, "ask_size", 0))
            elif tick_type == "bar":
                d["open"] = float(getattr(data, "open", 0))
                d["high"] = float(getattr(data, "high", 0))
                d["low"] = float(getattr(data, "low", 0))
                d["close"] = float(getattr(data, "close", 0))
                d["volume"] = int(getattr(data, "volume", 0))
        d["type"] = tick_type
        return d

    async def handle_trade(self, data):
        """Handle trade updates."""
        tick = self._make_tick(data, "trade")
        sym = tick.get("symbol", "").upper()
        if sym:
            with self._lock:
                self._price_cache[sym] = tick.get("price", 0)
        self._log_tick(tick)
        print(f"💰 Trade: {tick.get('symbol')} @ {tick.get('price')} x{tick.get('size', 0)}")

    async def handle_quote(self, data):
        """Handle quote updates."""
        tick = self._make_tick(data, "quote")
        self._log_tick(tick)

    async def handle_bar(self, data):
        """Handle bar (candle) updates."""
        tick = self._make_tick(data, "bar")
        sym = tick.get("symbol", "").upper()
        if sym:
            with self._lock:
                if sym not in self._bar_cache:
                    self._bar_cache[sym] = []
                self._bar_cache[sym].append(tick)
                if len(self._bar_cache[sym]) > 390:
                    self._bar_cache[sym] = self._bar_cache[sym][-390:]
        self._log_tick(tick)
        print(f"📊 Bar: {tick.get('symbol')} O:{tick.get('open')} H:{tick.get('high')} L:{tick.get('low')} C:{tick.get('close')} V:{tick.get('volume')}")

    def start(self, symbols: List[str]):
        """Start the WebSocket connection."""
        if not ALPACA_AVAILABLE:
            print("❌ Alpaca SDK not available")
            return

        self.running = True

        # Create stream
        from alpaca.data.enums import DataFeed
        feed_enum = DataFeed.IEX if "iex" in str(self.paper).lower() or True else DataFeed.SIP
        self.stream = StockDataStream(
            self.api_key,
            self.secret_key,
            feed=feed_enum,
        )

        # Subscribe
        for sym in symbols:
            self.subscribed_symbols.add(sym.upper())

        self.stream.subscribe_trades(self.handle_trade, *symbols)
        self.stream.subscribe_quotes(self.handle_quote, *symbols)
        self.stream.subscribe_bars(self.handle_bar, *symbols)

        print(f"📡 Subscribed to: {', '.join(self.subscribed_symbols)}")

        # Run in a separate thread
        def run_stream():
            try:
                self.stream.run()
            except Exception as e:
                print(f"Stream error: {e}")
                self.running = False

        self.thread = threading.Thread(target=run_stream, daemon=True)
        self.thread.start()
        print("✅ Alpaca WebSocket started")

    def stop(self):
        """Stop the WebSocket connection."""
        self.running = False
        if self.stream:
            try:
                self.stream.stop()
            except:
                pass
        print("🛑 Alpaca WebSocket stopped")

    def is_running(self) -> bool:
        """Check if WebSocket is running."""
        return self.running and (self.thread is not None and self.thread.is_alive())


# ─── Simple Usage ───────────────────────────────────────────────────────────

def start_alpaca_ws(symbols: List[str] = None):
    """Start Alpaca WebSocket logger."""
    global _global_logger

    if symbols is None:
        symbols = ["AAPL", "MSFT", "AMD", "AVGO"]

    api_key = ALPACA_API_KEY
    secret_key = ALPACA_SECRET_KEY

    if not api_key or not secret_key:
        print("❌ Alpaca credentials not found. Check .env file:")
        print(f"  {_ENV_FILE}")
        return None

    logger = AlpacaWSLogger(api_key, secret_key, ALPACA_PAPER)
    logger.start(symbols)

    _global_logger = logger
    return logger


# ─── Global logger instance for fast access ─────────────────────────────────

_global_logger: Optional[AlpacaWSLogger] = None

def get_global_logger() -> Optional[AlpacaWSLogger]:
    """Get the global WebSocket logger instance."""
    return _global_logger


def get_ws_price_fast(symbol: str) -> float:
    """Get latest price from in-memory cache (fastest)."""
    global _global_logger
    if _global_logger and _global_logger.is_running():
        with _global_logger._lock:
            return _global_logger._price_cache.get(symbol.upper(), 0.0)
    return 0.0


def get_ws_bars(symbol: str, limit: int = 100) -> List[Dict]:
    """Get cached bars from WebSocket for VWAP calculation."""
    global _global_logger
    if _global_logger and _global_logger.is_running():
        with _global_logger._lock:
            bars = _global_logger._bar_cache.get(symbol.upper(), [])
            return bars[-limit:] if len(bars) > limit else bars
    return []


def get_ws_metrics(symbol: str) -> Dict:
    """Get WebSocket metrics for a symbol."""
    if not WS_LOG.exists():
        return {}

    metrics = {
        "last_price": 0,
        "bid": 0,
        "ask": 0,
        "volume": 0,
        "trades_5min": 0,
    }

    cutoff = datetime.now(ET).timestamp() - 300

    try:
        with open(WS_LOG) as f:
            for line in f:
                try:
                    tick = json.loads(line.strip())
                    if tick.get("symbol") == symbol:
                        ts = tick.get("timestamp", "")
                        try:
                            tick_ts = datetime.fromisoformat(ts).timestamp()
                        except:
                            continue

                        if tick.get("type") == "trade":
                            metrics["last_price"] = tick.get("price", 0)
                            if tick_ts > cutoff:
                                metrics["trades_5min"] += 1
                        elif tick.get("type") == "quote":
                            metrics["bid"] = tick.get("bid", 0)
                            metrics["ask"] = tick.get("ask", 0)
                        elif tick.get("type") == "bar":
                            metrics["volume"] = tick.get("volume", 0)
                except:
                    continue
    except:
        pass

    return metrics


# ─── Daemon Mode ────────────────────────────────────────────────────────────

def load_picks_simple():
    """Load picks without importing us_poller (avoids yfinance/websockets conflict)."""
    import json as _json
    picks_file = BASE_DIR / "us_picks.json"
    if picks_file.exists():
        try:
            with open(picks_file) as f:
                data = _json.load(f)
                return data.get("picks", [])
        except:
            pass
    return []

if __name__ == "__main__":
    import sys, time

    print("=== Alpaca WebSocket Logger (Daemon) ===")

    if not ALPACA_AVAILABLE:
        print("❌ alpaca-py not installed")
        print("Install with: pip install alpaca-py")
        sys.exit(1)

    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        print("❌ Alpaca credentials not found in .env")
        sys.exit(1)

    # Load symbols from picks file directly
    picks = load_picks_simple()
    symbols = [p["symbol"] for p in picks] if picks else []

    if not symbols:
        print("⚠️ No picks found. Starting with empty watchlist.")
        symbols = []
    else:
        print(f"🎯 Watching {len(symbols)} symbols: {symbols}")

    ws = start_alpaca_ws(symbols)

    if ws is None:
        print("❌ Failed to start WebSocket")
        sys.exit(1)

    print("✅ WebSocket started. Running...")

    try:
        while True:
            time.sleep(60)

            # Check if we need to reload symbols
            new_picks = load_picks_simple()
            new_symbols = [p["symbol"] for p in new_picks] if new_picks else []
            if set(new_symbols) != set(symbols):
                symbols = new_symbols
                print(f"🔄 Reloading watchlist: {symbols}")
                ws.stop()
                ws = start_alpaca_ws(symbols)
    except KeyboardInterrupt:
        print("\n🛑 Stopping...")
    finally:
        if ws is not None:
            ws.stop()
        print("👋 Done.")
