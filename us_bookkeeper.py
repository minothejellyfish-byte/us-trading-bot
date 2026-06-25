#!/usr/bin/env python3
"""
US Bookkeeper — Source-of-Truth Sync Module
============================================

Syncs Alpaca API state with local JSON files:
- us_capital.json    → account balance, equity, buying power
- us_positions.json  → open positions
- us_trades.json     → reconciled trade history

Called:
- Every 5 minutes (cron)
- After every BUY/SELL (quick_refresh)
- Manual: python3 us_bookkeeper.py [sync|quick_refresh|reconcile|daily_pnl]

Key features:
- Atomic file writes (temp + rename)
- Graceful API error handling
- Reconciliation: adds missing Alpaca fills to local trades file
- P&L calculation from Alpaca fills
"""

import os
import sys
import json
import logging
import tempfile
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional

import pytz

# ── Paths ─────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CAPITAL_FILE = os.path.join(BASE_DIR, "us_capital.json")
POSITIONS_FILE = os.path.join(BASE_DIR, "us_positions.json")
TRADES_FILE = os.path.join(BASE_DIR, "us_trades.json")
ENV_FILE = os.path.join(BASE_DIR, ".env")

# ── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("us_bookkeeper")

# ── Timezone ────────────────────────────────────────────────────────────────
ET = pytz.timezone("America/New_York")
UTC = pytz.timezone("UTC")

# ── Import AlpacaTrader ─────────────────────────────────────────────────────
sys.path.insert(0, BASE_DIR)
from alpaca_api import AlpacaTrader

# ── Atomic File Write ───────────────────────────────────────────────────────

def _atomic_write(path: str, data: dict) -> None:
    """Write JSON atomically using temp file + rename."""
    dir_name = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, default=str)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _load_json(path: str, default: dict = None) -> dict:
    """Load JSON file safely."""
    if default is None:
        default = {}
    if not os.path.exists(path):
        return default
    try:
        with open(path) as f:
            return json.load(f)
    except json.JSONDecodeError:
        log.warning(f"JSON decode error in {path}, returning default")
        return default
    except Exception as e:
        log.warning(f"Error loading {path}: {e}")
        return default


# ── Trader Instance ─────────────────────────────────────────────────────────

def _get_trader() -> Optional[AlpacaTrader]:
    """Get AlpacaTrader instance or None on failure."""
    try:
        return AlpacaTrader()
    except Exception as e:
        log.warning(f"AlpacaTrader init failed: {e}")
        return None


# ── 1. sync_capital ─────────────────────────────────────────────────────────

def sync_capital() -> Dict:
    """Fetch account from Alpaca API, write us_capital.json. Return capital dict."""
    trader = _get_trader()
    if not trader:
        log.warning("sync_capital: no trader available")
        return _load_json(CAPITAL_FILE)
    
    try:
        acc = trader.get_account()
        capital = {
            "cash": float(acc["cash"]) if isinstance(acc.get("cash"), (int, float, str)) else 0.0,
            "equity": float(acc["equity"]) if isinstance(acc.get("equity"), (int, float, str)) else 0.0,
            "buying_power": float(acc["buying_power"]) if isinstance(acc.get("buying_power"), (int, float, str)) else 0.0,
            "portfolio_value": float(acc["portfolio_value"]) if isinstance(acc.get("portfolio_value"), (int, float, str)) else 0.0,
            "status": acc.get("status", "unknown"),
            "updated_at": datetime.now(ET).isoformat(),
            "source": "alpaca-api",
        }
        _atomic_write(CAPITAL_FILE, capital)
        log.info(f"sync_capital: cash=${capital['cash']:,.2f} equity=${capital['equity']:,.2f}")
        return capital
    except Exception as e:
        log.warning(f"sync_capital failed: {e}")
        return _load_json(CAPITAL_FILE)


# ── Helper: Load poller-compatible positions ─────────────────────────────────

def _load_poller_positions() -> Dict:
    """Load existing positions file, return positions dict or empty."""
    data = _load_json(POSITIONS_FILE, {"positions": {}})
    return data.get("positions", {})


# ── 2. sync_positions ───────────────────────────────────────────────────────

def sync_positions() -> Dict:
    """Fetch positions from Alpaca API, write us_positions.json in poller-compatible format.
    
    CRITICAL: The poller expects keys: entry_price, peak_price, closed, entry_time,
    signal, order_id, cycle, max_cycles. This function maps Alpaca format to poller
    format while preserving existing poller metadata.
    """
    trader = _get_trader()
    if not trader:
        log.warning("sync_positions: no trader available")
        return _load_json(POSITIONS_FILE)
    
    try:
        raw_positions = trader.get_positions()
        
        # Load existing poller data to preserve metadata (entry_time, peak_price, signal, etc.)
        existing = _load_poller_positions()
        
        positions = {}
        for p in raw_positions:
            sym = p.get("symbol", "")
            if not sym:
                continue
            
            # Get Alpaca data
            alpaca_qty = int(float(p.get("qty", 0))) if isinstance(p.get("qty"), (int, float, str)) else 0
            alpaca_avg_entry = float(p["avg_entry_price"]) if isinstance(p.get("avg_entry_price"), (int, float, str)) else 0.0
            alpaca_current = float(p["current_price"]) if isinstance(p.get("current_price"), (int, float, str)) else 0.0
            alpaca_mkt_val = float(p["market_value"]) if isinstance(p.get("market_value"), (int, float, str)) else 0.0
            alpaca_unreal = float(p["unrealized_pl"]) if isinstance(p.get("unrealized_pl"), (int, float, str)) else 0.0
            alpaca_unreal_pct = float(p["unrealized_plpc"]) if isinstance(p.get("unrealized_plpc"), (int, float, str)) else 0.0
            
            # Check if we have existing poller data for this symbol
            if sym in existing and not existing[sym].get("closed", True):
                # Preserve poller metadata, update price/qty from Alpaca
                mapped = existing[sym].copy()
                mapped["qty"] = alpaca_qty
                mapped["entry_price"] = alpaca_avg_entry or mapped.get("entry_price", 0)
                mapped["current_price"] = alpaca_current
                # Update peak_price if current is higher
                current_peak = mapped.get("peak_price", 0)
                if alpaca_current > current_peak:
                    mapped["peak_price"] = alpaca_current
                mapped["closed"] = False
            else:
                # New position — create minimal poller-compatible record
                mapped = {
                    "symbol": sym,
                    "entry_price": alpaca_avg_entry,
                    "qty": alpaca_qty,
                    "entry_time": datetime.now(ET).isoformat(),
                    "peak_price": alpaca_current,
                    "closed": False,
                    "signal": "alpaca-sync",
                    "order_id": "unknown",
                    "cycle": 1,
                    "max_cycles": 2,
                }
            
            # Always add Alpaca raw data under sub-key for reference
            mapped["alpaca_data"] = {
                "avg_entry_price": alpaca_avg_entry,
                "market_value": alpaca_mkt_val,
                "unrealized_pl": alpaca_unreal,
                "unrealized_plpc": alpaca_unreal_pct,
                "current_price": alpaca_current,
                "qty": alpaca_qty,
            }
            
            positions[sym] = mapped
        
        data = {
            "date": date.today().isoformat(),
            "time": datetime.now(ET).strftime("%H:%M:%S"),
            "positions": positions,
            "count": len(positions),
            "source": "alpaca-api",
        }
        _atomic_write(POSITIONS_FILE, data)
        log.info(f"sync_positions: {len(positions)} positions (poller-compatible format)")
        return data
    except Exception as e:
        log.warning(f"sync_positions failed: {e}")
        import traceback
        log.debug(f"sync_positions traceback: {traceback.format_exc()}")
        return _load_json(POSITIONS_FILE)


# ── 2b. get_positions / get_position (poller-compatible) ────────────────────

def get_positions() -> Dict:
    """Return current positions dict (symbol -> position data).
    
    Called by us_poller.py for bookkeeper confirmation.
    Returns empty dict if file doesn't exist.
    """
    data = _load_json(POSITIONS_FILE, {"positions": {}})
    return data.get("positions", {})


def get_position(symbol: str) -> Optional[Dict]:
    """Return position data for a specific symbol.
    
    Called by us_poller.py for single-position lookup.
    Returns None if symbol not found.
    """
    positions = get_positions()
    return positions.get(symbol)


# ── 3. quick_refresh ────────────────────────────────────────────────────────

def quick_refresh() -> Dict:
    """Call sync_capital() + sync_positions(). Called by bot after every BUY/SELL."""
    log.info("quick_refresh: syncing capital + positions")
    capital = sync_capital()
    positions = sync_positions()
    return {
        "capital": capital,
        "positions": positions,
        "timestamp": datetime.now(ET).isoformat(),
    }


# ── 4. get_alpaca_trades ────────────────────────────────────────────────────

def _parse_iso(dt_str: str) -> datetime:
    """Parse ISO datetime string, handling various formats."""
    if dt_str is None:
        return datetime.now(UTC)
    try:
        if dt_str.endswith("Z"):
            dt_str = dt_str[:-1] + "+00:00"
        return datetime.fromisoformat(dt_str)
    except Exception:
        return datetime.now(UTC)


def get_alpaca_trades(date_str: Optional[str] = None) -> List[Dict]:
    """Fetch filled orders from Alpaca API for the date. Return list of trade dicts."""
    trader = _get_trader()
    if not trader:
        log.warning("get_alpaca_trades: no trader available")
        return []
    
    target_date = date.fromisoformat(date_str) if date_str else date.today()
    
    # Build after/until in UTC
    start_dt = datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0, tzinfo=ET)
    end_dt = datetime(target_date.year, target_date.month, target_date.day, 23, 59, 59, tzinfo=ET)
    
    # Convert to UTC for API
    start_utc = start_dt.astimezone(UTC)
    end_utc = end_dt.astimezone(UTC)
    
    after = start_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    until = end_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    
    log.info(f"get_alpaca_trades: querying {target_date.isoformat()} ({after} to {until})")
    
    try:
        # Use requests fallback or SDK to get closed orders with date filter
        if trader.api and hasattr(trader.api, "list_orders"):
            orders = trader.api.list_orders(
                status="closed",
                after=after,
                until=until,
                limit=500,
            )
            raw_orders = []
            for o in orders:
                raw_orders.append({
                    "id": o.id,
                    "symbol": o.symbol,
                    "side": o.side,
                    "qty": o.qty,
                    "filled_qty": o.filled_qty,
                    "filled_avg_price": o.filled_avg_price,
                    "type": o.type,
                    "status": o.status,
                    "created_at": o.created_at.isoformat() if o.created_at else None,
                    "submitted_at": o.submitted_at.isoformat() if o.submitted_at else None,
                    "filled_at": o.filled_at.isoformat() if o.filled_at else None,
                })
        else:
            # requests fallback
            url = f"{trader.base_url}/v2/orders"
            params = {
                "status": "closed",
                "after": after,
                "until": until,
                "limit": 500,
            }
            resp = trader.session.get(url, params=params)
            resp.raise_for_status()
            raw_orders = resp.json()
        
        trades = []
        for o in raw_orders:
            filled_qty = o.get("filled_qty")
            if filled_qty is None:
                continue
            try:
                filled_qty = int(float(filled_qty))
            except (ValueError, TypeError):
                continue
            if filled_qty <= 0:
                continue
            
            filled_price = o.get("filled_avg_price")
            try:
                filled_price = float(filled_price) if filled_price is not None else 0.0
            except (ValueError, TypeError):
                filled_price = 0.0
            
            filled_at = o.get("filled_at") or o.get("created_at")
            dt = _parse_iso(filled_at)
            
            trades.append({
                "id": o.get("id", ""),
                "symbol": o.get("symbol", "").upper(),
                "side": o.get("side", "").upper(),
                "qty": filled_qty,
                "price": round(filled_price, 2),
                "filled_at": dt.isoformat() if dt else None,
                "date": dt.astimezone(ET).date().isoformat() if dt else target_date.isoformat(),
                "type": o.get("type", "market"),
                "status": o.get("status", ""),
            })
        
        log.info(f"get_alpaca_trades: found {len(trades)} filled orders")
        return trades
    except Exception as e:
        log.warning(f"get_alpaca_trades failed: {e}")
        return []


# ── 5. reconcile_trades ─────────────────────────────────────────────────────

def reconcile_trades(date_str: Optional[str] = None) -> Dict:
    """Compare us_trades.json with Alpaca orders. Detect missing trades. Write corrections."""
    target_date = date_str or date.today().isoformat()
    
    # Load local trades
    local_data = _load_json(TRADES_FILE, {"trades": []})
    local_trades = local_data.get("trades", [])
    
    # Get Alpaca trades for the date
    alpaca_trades = get_alpaca_trades(target_date)
    
    # Build lookup of local trades by (symbol, side, qty, price, date)
    local_keys = set()
    for t in local_trades:
        if t.get("date") == target_date:
            key = (
                t.get("symbol", "").upper(),
                "SELL" if t.get("exit_price") is not None else "BUY",
                t.get("qty", 0),
                round(float(t.get("entry_price", t.get("price", 0)) or 0), 2),
            )
            local_keys.add(key)
    
    # Also match by order id if present
    local_ids = {t.get("id", "") for t in local_trades}
    
    missing = []
    for at in alpaca_trades:
        if at["id"] in local_ids:
            continue
        
        # Check if it matches by symbol/qty/price
        key = (at["symbol"].upper(), at["side"].upper(), at["qty"], round(at["price"], 2))
        if key in local_keys:
            continue
        
        missing.append(at)
    
    corrections_made = 0
    if missing:
        log.warning(f"reconcile_trades: {len(missing)} Alpaca fills missing from local file")
        for m in missing:
            trade_entry = {
                "id": m["id"],
                "symbol": m["symbol"],
                "side": m["side"],
                "qty": m["qty"],
                "entry_price": m["price"] if m["side"] == "BUY" else None,
                "exit_price": m["price"] if m["side"] == "SELL" else None,
                "price": m["price"],
                "entry_time": m["filled_at"] if m["side"] == "BUY" else None,
                "exit_time": m["filled_at"] if m["side"] == "SELL" else None,
                "filled_at": m["filled_at"],
                "date": m["date"],
                "source": "alpaca-reconciliation",
                "signal": "",
                "regime": "",
                "notes": "Added by bookkeeper reconciliation",
            }
            local_trades.append(trade_entry)
            corrections_made += 1
            log.info(f"  Added missing trade: {m['side']} {m['qty']} {m['symbol']} @ ${m['price']:.2f}")
        
        # Save updated trades
        _atomic_write(TRADES_FILE, {"trades": local_trades})
        log.info(f"reconcile_trades: wrote {len(local_trades)} trades to {TRADES_FILE}")
    else:
        log.info("reconcile_trades: local file in sync with Alpaca")
    
    return {
        "date": target_date,
        "alpaca_count": len(alpaca_trades),
        "local_count": len([t for t in local_trades if t.get("date") == target_date]),
        "missing_found": len(missing),
        "corrections_made": corrections_made,
        "in_sync": len(missing) == 0,
    }


# ── 6. get_daily_pnl ────────────────────────────────────────────────────────

def get_daily_pnl(date_str: Optional[str] = None) -> Dict:
    """Calculate realized P&L from Alpaca fills for the day. Return dict with stats."""
    target_date = date_str or date.today().isoformat()
    
    # Get Alpaca fills for the day
    alpaca_trades = get_alpaca_trades(target_date)
    
    # Separate buys and sells
    buys = {}
    sells = []
    
    for t in alpaca_trades:
        sym = t["symbol"].upper()
        if t["side"] == "BUY":
            if sym not in buys:
                buys[sym] = []
            buys[sym].append(t)
        elif t["side"] == "SELL":
            sells.append(t)
    
    # Match sells to buys (FIFO) to calculate P&L
    realized_pnl = 0.0
    wins = 0
    losses = 0
    trades = []
    
    for sell in sells:
        sym = sell["symbol"].upper()
        sell_qty = sell["qty"]
        sell_price = sell["price"]
        
        if sym not in buys or not buys[sym]:
            # Sell without matching buy (could be from prior day)
            continue
        
        remaining_qty = sell_qty
        while remaining_qty > 0 and buys[sym]:
            buy = buys[sym][0]
            buy_qty = buy["qty"]
            buy_price = buy["price"]
            
            match_qty = min(remaining_qty, buy_qty)
            pnl = (sell_price - buy_price) * match_qty
            realized_pnl += pnl
            
            if pnl > 0:
                wins += 1
            else:
                losses += 1
            
            trades.append({
                "symbol": sym,
                "qty": match_qty,
                "entry_price": buy_price,
                "exit_price": sell_price,
                "pnl": round(pnl, 2),
                "date": target_date,
            })
            
            remaining_qty -= match_qty
            buy["qty"] -= match_qty
            if buy["qty"] <= 0:
                buys[sym].pop(0)
    
    total_trades = wins + losses
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0
    avg_pnl = (realized_pnl / total_trades) if total_trades > 0 else 0.0
    
    # Find best and worst trade
    if trades:
        sorted_trades = sorted(trades, key=lambda x: x["pnl"], reverse=True)
        best_trade = sorted_trades[0]
        worst_trade = sorted_trades[-1]
    else:
        best_trade = None
        worst_trade = None
    
    result = {
        "date": target_date,
        "total_pnl": round(realized_pnl, 2),
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "win_rate": round(win_rate, 1),
        "avg_pnl_per_trade": round(avg_pnl, 2),
        "best_trade": best_trade,
        "worst_trade": worst_trade,
        "trades": trades,
        "source": "alpaca-api",
    }
    
    log.info(f"get_daily_pnl: {target_date} — P&L=${realized_pnl:+.2f} ({wins}W/{losses}L, {win_rate:.1f}% WR)")
    return result


# ── 7. main (CLI) ───────────────────────────────────────────────────────────

def main():
    """CLI entry point: python3 us_bookkeeper.py [sync|quick_refresh|reconcile|daily_pnl]"""
    cmd = sys.argv[1] if len(sys.argv) > 1 else "sync"
    
    if cmd == "sync":
        log.info("CLI: sync")
        capital = sync_capital()
        positions = sync_positions()
        print(json.dumps({"capital": capital, "positions": positions}, indent=2, default=str))
    
    elif cmd == "quick_refresh":
        log.info("CLI: quick_refresh")
        result = quick_refresh()
        print(json.dumps(result, indent=2, default=str))
    
    elif cmd == "reconcile":
        date_str = sys.argv[2] if len(sys.argv) > 2 else None
        log.info(f"CLI: reconcile date={date_str}")
        result = reconcile_trades(date_str)
        print(json.dumps(result, indent=2, default=str))
    
    elif cmd == "daily_pnl":
        date_str = sys.argv[2] if len(sys.argv) > 2 else None
        log.info(f"CLI: daily_pnl date={date_str}")
        result = get_daily_pnl(date_str)
        print(json.dumps(result, indent=2, default=str))
    
    else:
        print(f"Usage: python3 {os.path.basename(__file__)} [sync|quick_refresh|reconcile|daily_pnl]")
        sys.exit(1)


if __name__ == "__main__":
    main()
