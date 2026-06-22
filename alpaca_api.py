"""
Alpaca Markets API Wrapper — Sharia-Compliant US Trading
===========================================================

Provides:
- Paper trading (default) or live trading
- Sharia-compliant order validation
- Real-time position tracking
- P&L calculation with Islamic finance considerations

Environment:
    ALPACA_API_KEY      — API key
    ALPACA_SECRET_KEY   — Secret key
    ALPACA_PAPER        — "true" for paper, "false" for live

Usage:
    from alpaca_api import AlpacaTrader
    
    trader = AlpacaTrader()  # Auto-detects paper/live
    trader.buy("AAPL", qty=10)  # Market order
    trader.sell("AAPL", qty=10)  # Market order
    positions = trader.get_positions()
"""

import os
import json
import time
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

# Try to import alpaca_trade_api, fallback to requests
import requests

try:
    import alpaca_trade_api as tradeapi
    HAS_ALPACA_SDK = True
except ImportError:
    HAS_ALPACA_SDK = False
    print("Warning: alpaca-trade-api not installed. Using requests fallback.")

from us_sharia_universe import is_sharia_compliant, get_sharia_universe

# ── Logging ─────────────────────────────────────────────────────────────────
log = logging.getLogger("alpaca_api")
if not log.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    ))
    log.addHandler(handler)
    log.setLevel(logging.INFO)

# Load environment variables from .env file
_ENV_FILE = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_ENV_FILE):
    with open(_ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())

# ── Constants ──────────────────────────────────────────────────────────────
PAPER_BASE_URL = "https://paper-api.alpaca.markets"
LIVE_BASE_URL = "https://api.alpaca.markets"
DATA_URL = "https://data.alpaca.markets"

SIDE_BUY = "buy"
SIDE_SELL = "sell"

class AlpacaTrader:
    """Alpaca API wrapper with Sharia compliance checks."""
    
    def __init__(self, api_key: Optional[str] = None,
                 secret_key: Optional[str] = None,
                 paper: Optional[bool] = None):
        """
        Initialize Alpaca trader.
        
        Args:
            api_key: Alpaca API key (or from ALPACA_API_KEY env)
            secret_key: Alpaca secret key (or from ALPACA_SECRET_KEY env)
            paper: True for paper trading, False for live
        """
        self.api_key = api_key or os.environ.get("ALPACA_API_KEY")
        self.secret_key = secret_key or os.environ.get("ALPACA_SECRET_KEY")
        
        if paper is None:
            paper = os.environ.get("ALPACA_PAPER", "true").lower() == "true"
        self.paper = paper
        
        if not self.api_key or not self.secret_key:
            raise ValueError("Alpaca API key and secret key required")
        
        self.base_url = PAPER_BASE_URL if paper else LIVE_BASE_URL
        
        # Initialize SDK or requests
        if HAS_ALPACA_SDK:
            self.api = tradeapi.REST(
                self.api_key, self.secret_key,
                self.base_url, api_version="v2"
            )
        else:
            self.api = None
            self.session = requests.Session()
            self.session.headers.update({
                "APCA-API-KEY-ID": self.api_key,
                "APCA-API-SECRET-KEY": self.secret_key,
            })
        
        log.info(f"AlpacaTrader initialized ({'PAPER' if paper else 'LIVE'})")
    
    def _request(self, method: str, path: str, **kwargs) -> dict:
        """Make API request (requests fallback)."""
        url = f"{self.base_url}/v2{path}"
        resp = self.session.request(method, url, **kwargs)
        resp.raise_for_status()
        return resp.json()
    
    def _is_tradable(self, symbol: str) -> Tuple[bool, str]:
        """Check if symbol is Sharia-compliant and tradable."""
        symbol = symbol.upper().strip()
        
        # Sharia check
        if not is_sharia_compliant(symbol):
            return False, f"{symbol} is not Sharia-compliant"
        
        # Market hours check (if API available)
        try:
            clock = self.get_clock()
            if not clock.get("is_open", True):
                return False, "Market is closed"
        except:
            pass  # Skip if can't check
        
        return True, "OK"
    
    def get_account(self) -> Dict:
        """Get account info (balance, buying power)."""
        if self.api:
            acc = self.api.get_account()
            return {
                "id": acc.id,
                "cash": float(acc.cash),
                "portfolio_value": float(acc.portfolio_value),
                "buying_power": float(acc.buying_power),
                "equity": float(acc.equity),
                "status": acc.status,
            }
        else:
            return self._request("GET", "/account")
    
    def get_positions(self) -> List[Dict]:
        """Get open positions."""
        if self.api:
            positions = self.api.list_positions()
            return [{
                "symbol": p.symbol,
                "qty": int(float(p.qty)),
                "avg_entry_price": float(p.avg_entry_price),
                "market_value": float(p.market_value),
                "unrealized_pl": float(p.unrealized_pl),
                "unrealized_plpc": float(p.unrealized_plpc),
                "current_price": float(p.current_price),
            } for p in positions]
        else:
            return self._request("GET", "/positions")
    
    def get_position(self, symbol: str) -> Optional[Dict]:
        """Get single position."""
        try:
            if self.api:
                p = self.api.get_position(symbol)
                return {
                    "symbol": p.symbol,
                    "qty": int(float(p.qty)),
                    "avg_entry_price": float(p.avg_entry_price),
                    "market_value": float(p.market_value),
                    "unrealized_pl": float(p.unrealized_pl),
                    "current_price": float(p.current_price),
                }
            else:
                return self._request("GET", f"/positions/{symbol}")
        except Exception:
            return None
    
    def submit_order(self, symbol: str, qty: int, side: str,
                     order_type: str = "market",
                     time_in_force: str = "day",
                     limit_price: Optional[float] = None) -> Dict:
        """
        Submit order with Sharia compliance check.
        
        Args:
            symbol: Stock ticker
            qty: Number of shares
            side: "buy" or "sell"
            order_type: "market", "limit", "stop", "stop_limit"
            time_in_force: "day", "gtc", "opg", "cls", "ioc", "fok"
            limit_price: Required for limit orders
        
        Returns:
            Order dict with id, status, etc.
        """
        symbol = symbol.upper().strip()
        
        # Sharia check for buys only
        if side == SIDE_BUY:
            is_ok, reason = self._is_tradable(symbol)
            if not is_ok:
                log.error(f"Order rejected: {reason}")
                raise ValueError(f"Sharia compliance: {reason}")
        
        # Build order
        order_data = {
            "symbol": symbol,
            "qty": str(qty),
            "side": side,
            "type": order_type,
            "time_in_force": time_in_force,
        }
        if limit_price:
            order_data["limit_price"] = str(limit_price)
        
        # Submit
        if self.api:
            order = self.api.submit_order(**order_data)
            result = {
                "id": order.id,
                "symbol": order.symbol,
                "side": order.side,
                "qty": order.qty,
                "type": order.type,
                "status": order.status,
                "created_at": order.created_at,
            }
        else:
            result = self._request("POST", "/orders", json=order_data)
        
        log.info(f"Order submitted: {side} {qty} {symbol} @ {order_type} → {result['status']}")
        return result
    
    def buy(self, symbol: str, qty: int, order_type: str = "market",
            limit_price: Optional[float] = None) -> Dict:
        """Sharia-compliant buy order."""
        return self.submit_order(symbol, qty, SIDE_BUY, order_type,
                                limit_price=limit_price)
    
    def sell(self, symbol: str, qty: int, order_type: str = "market",
             limit_price: Optional[float] = None) -> Dict:
        """Sell order (no Sharia check needed for exits)."""
        return self.submit_order(symbol, qty, SIDE_SELL, order_type,
                                limit_price=limit_price)
    
    def get_orders(self, status: str = "open") -> List[Dict]:
        """Get orders by status."""
        if self.api:
            orders = self.api.list_orders(status=status)
            return [{
                "id": o.id,
                "symbol": o.symbol,
                "side": o.side,
                "qty": o.qty,
                "type": o.type,
                "status": o.status,
                "filled_qty": o.filled_qty,
                "filled_avg_price": o.filled_avg_price,
                "created_at": o.created_at.isoformat() if o.created_at else None,
            } for o in orders]
        else:
            return self._request("GET", "/orders", params={"status": status})
    
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an order."""
        try:
            if self.api:
                self.api.cancel_order(order_id)
            else:
                self._request("DELETE", f"/orders/{order_id}")
            log.info(f"Order {order_id} cancelled")
            return True
        except Exception as e:
            log.error(f"Cancel failed: {e}")
            return False
    
    def get_clock(self) -> Dict:
        """Get market clock (open/close status)."""
        if self.api:
            clock = self.api.get_clock()
            return {
                "timestamp": clock.timestamp.isoformat(),
                "is_open": clock.is_open,
                "next_open": clock.next_open.isoformat(),
                "next_close": clock.next_close.isoformat(),
            }
        else:
            return self._request("GET", "/clock")
    
    def get_bars(self, symbol: str, timeframe: str = "1Min",
                 limit: int = 100) -> List[Dict]:
        """
        Get historical bars.
        
        Args:
            symbol: Stock ticker
            timeframe: "1Min", "5Min", "15Min", "1Hour", "1Day"
            limit: Number of bars
        """
        if self.api:
            bars = self.api.get_bars(symbol, timeframe, limit=limit)
            return [{
                "t": b.t.isoformat(),
                "o": b.o,
                "h": b.h,
                "l": b.l,
                "c": b.c,
                "v": b.v,
            } for b in bars]
        else:
            url = f"{DATA_URL}/v2/stocks/{symbol}/bars"
            resp = self.session.get(url, params={
                "timeframe": timeframe,
                "limit": limit,
                "feed": "iex",
            })
            resp.raise_for_status()
            data = resp.json()
            return data.get("bars", [])
    
    def get_last_trade(self, symbol: str) -> Dict:
        """Get last trade price."""
        if self.api:
            trade = self.api.get_latest_trade(symbol)
            return {
                "price": float(trade.price),
                "size": trade.size,
                "timestamp": trade.timestamp.isoformat(),
            }
        else:
            url = f"{DATA_URL}/v2/stocks/{symbol}/trades/latest"
            resp = self.session.get(url, params={"feed": "iex"})
            resp.raise_for_status()
            data = resp.json()
            trade = data.get("trade", {})
            return {
                "price": float(trade.get("p", 0)),
                "size": trade.get("s", 0),
                "timestamp": trade.get("t", ""),
            }
    
    def get_assets(self, status: str = "active") -> List[Dict]:
        """Get list of tradable assets."""
        if self.api:
            assets = self.api.list_assets(status=status)
            return [{
                "symbol": a.symbol,
                "name": a.name,
                "exchange": a.exchange,
                "tradable": a.tradable,
                "fractionable": getattr(a, "fractionable", False),
            } for a in assets]
        else:
            return self._request("GET", "/assets", params={"status": status})


# ── Helper Functions ─────────────────────────────────────────────────────────

def calculate_position_size(capital: float, price: float,
                            pct: float = 0.35) -> int:
    """Calculate position size (35% default)."""
    max_invest = capital * pct
    qty = int(max_invest / price)
    return max(qty, 0)


def format_usd(amount: float) -> str:
    """Format USD amount."""
    return f"${amount:,.2f}"


# ── Test ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # This requires Alpaca API keys
    import os
    
    if not os.environ.get("ALPACA_API_KEY"):
        print("Set ALPACA_API_KEY and ALPACA_SECRET_KEY environment variables")
        print("Get keys from: https://app.alpaca.markets/paper")
        exit(1)
    
    trader = AlpacaTrader()
    
    # Account info
    acc = trader.get_account()
    cash = float(acc['cash']) if isinstance(acc['cash'], str) else acc['cash']
    bp = float(acc['buying_power']) if isinstance(acc['buying_power'], str) else acc['buying_power']
    print(f"Account: {format_usd(cash)} cash, {format_usd(bp)} buying power")
    
    # Positions
    positions = trader.get_positions()
    print(f"Positions: {len(positions)}")
    for p in positions:
        avg = float(p['avg_entry_price']) if isinstance(p['avg_entry_price'], str) else p['avg_entry_price']
        curr = float(p['current_price']) if isinstance(p['current_price'], str) else p['current_price']
        pl = float(p['unrealized_pl']) if isinstance(p['unrealized_pl'], str) else p['unrealized_pl']
        print(f"  {p['symbol']}: {p['qty']} @ {avg:.2f} → {curr:.2f} (P&L: {pl:+.2f})")
    
    # Clock
    clock = trader.get_clock()
    print(f"Market: {'OPEN' if clock['is_open'] else 'CLOSED'}")
    
    # Last trade
    trade = trader.get_last_trade("AAPL")
    print(f"AAPL last: ${trade['price']:.2f}")
    
    # Sharia check
    print(f"\nSharia check:")
    for sym in ["AAPL", "JPM", "NVDA", "BAC"]:
        status = "✅" if is_sharia_compliant(sym) else "❌"
        print(f"  {status} {sym}")
