#!/usr/bin/env python3
"""
US Alpaca WebSocket Logger
=========================
Logs real-time trade data from Alpaca WebSocket.

Features:
- Real-time price updates
- Trade execution tracking
- Quote monitoring
- Bar (candle) data

Output:
- history/alpaca_ws_{date}.jsonl — Real-time tick data

Author: Mino (kimi-k2.6)
Version: 4.12
Date: 2026-06-23
"""

import json
import os
import asyncio
import threading
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List

import pytz

# Alpaca imports
try:
    from alpaca_trade_api import Stream
    from alpaca_trade_api.entity import Trade, Quote, Bar
    ALPACA_AVAILABLE = True
except ImportError:
    ALPACA_AVAILABLE = False
    print("alpaca_trade_api not installed")

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

# Get credentials
ALPACA_API_KEY = os.environ.get("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "")
ALPACA_PAPER = os.environ.get("ALPACA_PAPER", "true").lower() == "true"

# ─── WebSocket Handler ───────────────────────────────────────────────────────

class AlpacaWSLogger:
    """Alpaca WebSocket data logger."""
    
    def __init__(self, api_key: str, secret_key: str, paper: bool = True):
        self.api_key = api_key
        self.secret_key = secret_key
        self.paper = paper
        self.stream = None
        self.running = False
        self._lock = threading.Lock()
        
        # Track subscribed symbols
        self.subscribed_symbols = set()
        
    def _get_ws_url(self) -> str:
        """Get WebSocket URL."""
        if self.paper:
            return "wss://stream.data.sandbox.alpaca.markets/v2/iex"
        return "wss://stream.data.alpaca.markets/v2/iex"
    
    def _log_tick(self, data: Dict):
        """Log a tick to JSONL file."""
        with self._lock:
            with open(WS_LOG, 'a') as f:
                json.dump(data, f)
                f.write('\n')
    
    async def handle_trade(self, trade):
        """Handle trade updates."""
        tick = {
            "type": "trade",
            "timestamp": datetime.now(ET).isoformat(),
            "symbol": trade.symbol if hasattr(trade, 'symbol') else str(trade),
            "price": float(trade.price) if hasattr(trade, 'price') else 0,
            "size": int(trade.size) if hasattr(trade, 'size') else 0,
            "exchange": trade.exchange if hasattr(trade, 'exchange') else "",
        }
        self._log_tick(tick)
        print(f"💰 Trade: {tick['symbol']} @ ${tick['price']:.2f} x{tick['size']}")
    
    async def handle_quote(self, quote):
        """Handle quote updates."""
        tick = {
            "type": "quote",
            "timestamp": datetime.now(ET).isoformat(),
            "symbol": quote.symbol if hasattr(quote, 'symbol') else str(quote),
            "bid": float(quote.bid_price) if hasattr(quote, 'bid_price') else 0,
            "ask": float(quote.ask_price) if hasattr(quote, 'ask_price') else 0,
            "bid_size": int(quote.bid_size) if hasattr(quote, 'bid_size') else 0,
            "ask_size": int(quote.ask_size) if hasattr(quote, 'ask_size') else 0,
        }
        self._log_tick(tick)
    
    async def handle_bar(self, bar):
        """Handle bar (candle) updates."""
        tick = {
            "type": "bar",
            "timestamp": datetime.now(ET).isoformat(),
            "symbol": bar.symbol if hasattr(bar, 'symbol') else str(bar),
            "open": float(bar.open) if hasattr(bar, 'open') else 0,
            "high": float(bar.high) if hasattr(bar, 'high') else 0,
            "low": float(bar.low) if hasattr(bar, 'low') else 0,
            "close": float(bar.close) if hasattr(bar, 'close') else 0,
            "volume": int(bar.volume) if hasattr(bar, 'volume') else 0,
        }
        self._log_tick(tick)
        print(f"📊 Bar: {tick['symbol']} O:{tick['open']:.2f} H:{tick['high']:.2f} L:{tick['low']:.2f} C:{tick['close']:.2f} V:{tick['volume']}")
    
    def subscribe(self, symbols: List[str]):
        """Subscribe to symbols."""
        if not self.stream:
            print("Stream not initialized")
            return
        
        for sym in symbols:
            self.subscribed_symbols.add(sym.upper())
        
        # Subscribe to trade updates
        self.stream.subscribe_trades(self.handle_trade, *self.subscribed_symbols)
        
        # Subscribe to quote updates
        self.stream.subscribe_quotes(self.handle_quote, *self.subscribed_symbols)
        
        # Subscribe to minute bars
        self.stream.subscribe_bars(self.handle_bar, *self.subscribed_symbols)
        
        print(f"📡 Subscribed to: {', '.join(self.subscribed_symbols)}")
    
    def start(self, symbols: List[str]):
        """Start the WebSocket connection."""
        if not ALPACA_AVAILABLE:
            print("❌ Alpaca SDK not available")
            return
        
        self.running = True
        
        # Create stream
        self.stream = Stream(
            self.api_key,
            self.secret_key,
            base_url="https://paper-api.alpaca.markets" if self.paper else "https://api.alpaca.markets",
            data_feed="iex",
        )
        
        # Subscribe
        self.subscribe(symbols)
        
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
            # Note: Alpaca Stream doesn't have a clean stop method
            # It will stop when the thread is killed
            pass
        print("🛑 Alpaca WebSocket stopped")
    
    def is_running(self) -> bool:
        """Check if WebSocket is running."""
        return self.running and self.thread.is_alive()


# ─── Simple Usage ─────────────────────────────────────────────────────────────

def start_alpaca_ws(symbols: List[str] = None):
    """Start Alpaca WebSocket logger."""
    if symbols is None:
        symbols = ["AAPL", "MSFT", "AMD", "AVGO"]
    
    # Use credentials from environment (loaded from .env)
    api_key = ALPACA_API_KEY
    secret_key = ALPACA_SECRET_KEY
    paper = ALPACA_PAPER
    
    if not api_key or not secret_key:
        print("❌ Alpaca credentials not found. Check .env file:")
        print(f"  {_ENV_FILE}")
        return None
    
    logger = AlpacaWSLogger(api_key, secret_key, paper)
    logger.start(symbols)
    
    return logger


# ─── Integration with Poller ─────────────────────────────────────────────────

def get_ws_price(symbol: str) -> float:
    """Get latest price from WebSocket data."""
    if not WS_LOG.exists():
        return 0.0
    
    latest_price = 0.0
    latest_ts = ""
    
    try:
        with open(WS_LOG) as f:
            for line in f:
                try:
                    tick = json.loads(line.strip())
                    if tick.get("symbol") == symbol and tick.get("type") in ["trade", "bar"]:
                        ts = tick.get("timestamp", "")
                        if ts > latest_ts:
                            latest_ts = ts
                            latest_price = tick.get("price", tick.get("close", 0))
                except:
                    continue
    except:
        pass
    
    return float(latest_price)


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
    
    cutoff = datetime.now(ET).timestamp() - 300  # 5 minutes ago
    
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


# ─── Test ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== Alpaca WebSocket Logger ===")
    
    if not ALPACA_AVAILABLE:
        print("❌ alpaca_trade_api not installed")
        print("Install with: pip install alpaca-trade-api")
        exit(1)
    
    # Test with demo data
    print("✅ Alpaca SDK available")
    print(f"Stream class: {Stream}")
    
    # Check config
    config_file = BASE_DIR / "alpaca_config.json"
    if config_file.exists():
        print(f"✅ Config found: {config_file}")
    else:
        print(f"⚠️ Config not found: {config_file}")
        print("Create it with:")
        print(json.dumps({
            "api_key": "YOUR_API_KEY",
            "secret_key": "YOUR_SECRET_KEY",
            "paper": True
        }, indent=2))
    
    print("\nTo start WebSocket logging:")
    print("  from us_alpaca_ws import start_alpaca_ws")
    print("  ws = start_alpaca_ws(['AAPL', 'MSFT', 'AMD'])")
    print("  # Let it run...")
    print("  ws.stop()")
