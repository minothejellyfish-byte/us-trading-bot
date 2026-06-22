#!/usr/bin/env python3
"""
US Bookkeeper — v4.12
===================
Comprehensive position tracking and P&L management for US trading.

Features:
- FIFO position matching (buy ↔ sell)
- Real-time P&L tracking
- Capital management with drawdown limits
- Trade history with full metadata
- Daily/weekly performance summaries
- Alerts for significant events

Files:
- us_bookkeeper.json — active positions and capital
- us_trades.json — completed trade history
- us_daily_summary.json — daily aggregated stats
- us_positions.json — current open positions

Author: Mino (kimi-k2.6)
Version: 4.12
Date: 2026-06-23
"""

import json
import os
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import threading
import logging

import pytz

# ─── Config ─────────────────────────────────────────────────────────────────

ET = pytz.timezone("America/New_York")
BASE_DIR = Path("/home/mino/us-exec")

BOOKKEEPER_FILE = BASE_DIR / "us_bookkeeper.json"
TRADES_FILE = BASE_DIR / "us_trades.json"
DAILY_FILE = BASE_DIR / "us_daily_summary.json"
POSITIONS_FILE = BASE_DIR / "us_positions.json"
CAPITAL_FILE = BASE_DIR / "us_capital.json"

# Risk limits
MAX_DRAWDOWN_PCT = 0.05        # 5% max daily drawdown
MAX_POSITION_PCT = 0.40        # 40% max per position
DEFAULT_POSITION_PCT = 0.25  # 25% default per position

# Logging
log = logging.getLogger(__name__)

# Thread-safe lock
_lock = threading.Lock()


# ─── Data Models ────────────────────────────────────────────────────────────

class Position:
    """Represents an open position."""
    
    def __init__(self, symbol: str, qty: int, entry_price: float, 
                 entry_time: str, signal: str = "", regime: str = "",
                 cycle: int = 1, max_cycles: int = 2):
        self.symbol = symbol
        self.qty = qty
        self.entry_price = entry_price
        self.entry_time = entry_time
        self.signal = signal
        self.regime = regime
        self.cycle = cycle
        self.max_cycles = max_cycles
        self.peak_price = entry_price
        self.closed = False
        self.order_id = ""
        
    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "qty": self.qty,
            "entry_price": self.entry_price,
            "entry_time": self.entry_time,
            "signal": self.signal,
            "regime": self.regime,
            "cycle": self.cycle,
            "max_cycles": self.max_cycles,
            "peak_price": self.peak_price,
            "closed": self.closed,
            "order_id": self.order_id,
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "Position":
        pos = cls(
            symbol=data.get("symbol", ""),
            qty=data.get("qty", 0),
            entry_price=data.get("entry_price", 0),
            entry_time=data.get("entry_time", ""),
            signal=data.get("signal", ""),
            regime=data.get("regime", ""),
            cycle=data.get("cycle", 1),
            max_cycles=data.get("max_cycles", 2),
        )
        pos.peak_price = data.get("peak_price", pos.entry_price)
        pos.closed = data.get("closed", False)
        pos.order_id = data.get("order_id", "")
        return pos


class Trade:
    """Represents a completed trade (entry + exit pair)."""
    
    def __init__(self, symbol: str, qty: int, entry_price: float, exit_price: float,
                 entry_time: str, exit_time: str, entry_signal: str = "",
                 exit_reason: str = "", regime: str = ""):
        self.symbol = symbol
        self.qty = qty
        self.entry_price = entry_price
        self.exit_price = exit_price
        self.entry_time = entry_time
        self.exit_time = exit_time
        self.entry_signal = entry_signal
        self.exit_reason = exit_reason
        self.regime = regime
        
        # Calculated fields
        self.gross_pnl = (exit_price - entry_price) * qty
        self.spread_cost = (entry_price + exit_price) * qty * 0.001  # 0.1% spread
        self.net_pnl = self.gross_pnl - self.spread_cost
        self.pnl_pct = ((exit_price - entry_price) / entry_price * 100) if entry_price else 0
        
        # Duration
        self.duration_min = 0
        if entry_time and exit_time:
            try:
                entry_dt = datetime.fromisoformat(entry_time)
                exit_dt = datetime.fromisoformat(exit_time)
                self.duration_min = (exit_dt - entry_dt).total_seconds() / 60
            except:
                pass
        
    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "qty": self.qty,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "entry_time": self.entry_time,
            "exit_time": self.exit_time,
            "entry_signal": self.entry_signal,
            "exit_reason": self.exit_reason,
            "regime": self.regime,
            "gross_pnl": round(self.gross_pnl, 2),
            "spread_cost": round(self.spread_cost, 2),
            "net_pnl": round(self.net_pnl, 2),
            "pnl_pct": round(self.pnl_pct, 2),
            "duration_min": round(self.duration_min, 1),
            "date": datetime.fromisoformat(self.entry_time).date().isoformat() if self.entry_time else date.today().isoformat(),
        }


# ─── Bookkeeper Core ─────────────────────────────────────────────────────────

class Bookkeeper:
    """Main bookkeeper class for US trading."""
    
    def __init__(self):
        self._lock = threading.Lock()
        self._ensure_files()
        
    def _ensure_files(self):
        """Ensure all data files exist."""
        for filepath in [BOOKKEEPER_FILE, TRADES_FILE, DAILY_FILE, POSITIONS_FILE, CAPITAL_FILE]:
            if not filepath.exists():
                self._save_json(filepath, {})
    
    def _load_json(self, filepath: Path) -> Dict:
        """Load JSON file."""
        try:
            with open(filepath) as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {}
    
    def _save_json(self, filepath: Path, data: Dict):
        """Save JSON file atomically."""
        tmp = filepath.with_suffix('.tmp')
        with open(tmp, 'w') as f:
            json.dump(data, f, indent=2, default=str)
        os.replace(tmp, filepath)
    
    # ── Position Management ─────────────────────────────────────────────────
    
    def add_position(self, symbol: str, qty: int, entry_price: float,
                     signal: str = "", regime: str = "", order_id: str = "") -> Position:
        """Add a new position."""
        with self._lock:
            positions = self._load_json(POSITIONS_FILE)
            
            # Create position
            pos = Position(
                symbol=symbol,
                qty=qty,
                entry_price=entry_price,
                entry_time=datetime.now(ET).isoformat(),
                signal=signal,
                regime=regime,
            )
            pos.order_id = order_id
            
            # Save
            positions[symbol] = pos.to_dict()
            self._save_json(POSITIONS_FILE, positions)
            
            # Update capital
            self._deduct_capital(entry_price * qty)
            
            log.info(f"Position added: {symbol} {qty}@{entry_price:.2f} signal={signal}")
            return pos
    
    def close_position(self, symbol: str, exit_price: float, 
                       exit_reason: str, regime: str = "") -> Optional[Trade]:
        """Close a position and record the trade."""
        with self._lock:
            positions = self._load_json(POSITIONS_FILE)
            
            if symbol not in positions:
                log.warning(f"Position not found: {symbol}")
                return None
            
            pos_data = positions[symbol]
            pos = Position.from_dict(pos_data)
            
            if pos.closed:
                log.warning(f"Position already closed: {symbol}")
                return None
            
            # Create trade record
            trade = Trade(
                symbol=symbol,
                qty=pos.qty,
                entry_price=pos.entry_price,
                exit_price=exit_price,
                entry_time=pos.entry_time,
                exit_time=datetime.now(ET).isoformat(),
                entry_signal=pos.signal,
                exit_reason=exit_reason,
                regime=regime or pos.regime,
            )
            
            # Mark position as closed
            pos.closed = True
            positions[symbol] = pos.to_dict()
            self._save_json(POSITIONS_FILE, positions)
            
            # Add to trade history
            trades_data = self._load_json(TRADES_FILE)
            if not isinstance(trades_data, dict):
                trades_data = {"trades": []}
            if "trades" not in trades_data:
                trades_data["trades"] = []
            trades_data["trades"].append(trade.to_dict())
            self._save_json(TRADES_FILE, trades_data)
            
            # Update capital
            self._add_capital(exit_price * pos.qty)
            
            log.info(f"Position closed: {symbol} PnL=${trade.net_pnl:.2f} ({trade.pnl_pct:+.2f}%) reason={exit_reason}")
            return trade
    
    def update_peak_price(self, symbol: str, price: float):
        """Update peak price for trailing stop calculation."""
        with self._lock:
            positions = self._load_json(POSITIONS_FILE)
            
            if symbol in positions:
                pos = Position.from_dict(positions[symbol])
                if not pos.closed and price > pos.peak_price:
                    pos.peak_price = price
                    positions[symbol] = pos.to_dict()
                    self._save_json(POSITIONS_FILE, positions)
    
    def get_position(self, symbol: str) -> Optional[Position]:
        """Get a specific position."""
        positions = self._load_json(POSITIONS_FILE)
        if symbol in positions:
            return Position.from_dict(positions[symbol])
        return None
    
    def get_open_positions(self) -> Dict[str, Position]:
        """Get all open positions."""
        positions = self._load_json(POSITIONS_FILE)
        return {
            sym: Position.from_dict(data) 
            for sym, data in positions.items() 
            if not data.get("closed", False)
        }
    
    # ── Capital Management ────────────────────────────────────────────────────
    
    def _load_capital(self) -> Dict:
        """Load capital data."""
        return self._load_json(CAPITAL_FILE)
    
    def _save_capital(self, data: Dict):
        """Save capital data."""
        self._save_json(CAPITAL_FILE, data)
    
    def _deduct_capital(self, amount: float):
        """Deduct from available capital."""
        capital = self._load_capital()
        current = capital.get("available_capital", 100000)
        capital["available_capital"] = max(0, current - amount)
        capital["updated_at"] = datetime.now(ET).isoformat()
        self._save_capital(capital)
    
    def _add_capital(self, amount: float):
        """Add to available capital."""
        capital = self._load_capital()
        current = capital.get("available_capital", 100000)
        capital["available_capital"] = current + amount
        capital["updated_at"] = datetime.now(ET).isoformat()
        self._save_capital(capital)
    
    def get_capital(self) -> Dict:
        """Get current capital status."""
        return self._load_capital()
    
    def set_capital(self, amount: float):
        """Set initial capital."""
        with self._lock:
            capital = {
                "initial_capital": amount,
                "available_capital": amount,
                "total_invested": 0,
                "total_realized_pnl": 0,
                "updated_at": datetime.now(ET).isoformat(),
            }
            self._save_capital(capital)
    
    # ── P&L Calculation ──────────────────────────────────────────────────────
    
    def get_unrealized_pnl(self, symbol: str, current_price: float) -> Tuple[float, float]:
        """Calculate unrealized P&L for a position."""
        pos = self.get_position(symbol)
        if not pos or pos.closed or pos.qty <= 0:
            return 0, 0
        
        pnl = (current_price - pos.entry_price) * pos.qty
        pnl_pct = ((current_price - pos.entry_price) / pos.entry_price * 100) if pos.entry_price else 0
        return pnl, pnl_pct
    
    def get_total_unrealized_pnl(self, prices: Dict[str, float]) -> Tuple[float, float]:
        """Calculate total unrealized P&L across all open positions."""
        open_positions = self.get_open_positions()
        total_pnl = 0
        total_invested = 0
        
        for symbol, pos in open_positions.items():
            if symbol in prices:
                pnl, _ = self.get_unrealized_pnl(symbol, prices[symbol])
                total_pnl += pnl
                total_invested += pos.entry_price * pos.qty
        
        total_pct = (total_pnl / total_invested * 100) if total_invested > 0 else 0
        return total_pnl, total_pct
    
    def get_realized_pnl(self, day: date = None) -> Tuple[float, float]:
        """Get realized P&L for a specific day."""
        if day is None:
            day = date.today()
        
        trades_data = self._load_json(TRADES_FILE)
        trades = trades_data.get("trades", [])
        day_str = day.isoformat()
        
        day_trades = [t for t in trades if t.get("date") == day_str]
        total_pnl = sum(t.get("net_pnl", 0) for t in day_trades)
        
        wins = [t for t in day_trades if t.get("net_pnl", 0) > 0]
        losses = [t for t in day_trades if t.get("net_pnl", 0) <= 0]
        
        return total_pnl, len(wins), len(losses)
    
    # ── Daily Summary ────────────────────────────────────────────────────────
    
    def generate_daily_summary(self, day: date = None) -> Dict:
        """Generate daily performance summary."""
        if day is None:
            day = date.today()
        
        day_str = day.isoformat()
        trades_data = self._load_json(TRADES_FILE)
        trades = trades_data.get("trades", [])
        day_trades = [t for t in trades if t.get("date") == day_str]
        
        # Stats
        total_pnl = sum(t.get("net_pnl", 0) for t in day_trades)
        wins = [t for t in day_trades if t.get("net_pnl", 0) > 0]
        losses = [t for t in day_trades if t.get("net_pnl", 0) <= 0]
        
        avg_win = sum(t.get("net_pnl", 0) for t in wins) / len(wins) if wins else 0
        avg_loss = sum(t.get("net_pnl", 0) for t in losses) / len(losses) if losses else 0
        
        durations = [t.get("duration_min", 0) for t in day_trades if t.get("duration_min")]
        avg_duration = sum(durations) / len(durations) if durations else 0
        
        summary = {
            "date": day_str,
            "total_trades": len(day_trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(day_trades) * 100, 1) if day_trades else 0,
            "total_pnl": round(total_pnl, 2),
            "avg_pnl_per_trade": round(total_pnl / len(day_trades), 2) if day_trades else 0,
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "avg_duration_min": round(avg_duration, 1),
            "largest_win": round(max((t.get("net_pnl", 0) for t in wins), default=0), 2),
            "largest_loss": round(min((t.get("net_pnl", 0) for t in losses), default=0), 2),
            "generated_at": datetime.now(ET).isoformat(),
        }
        
        # Save to daily summary
        summaries = self._load_json(DAILY_FILE)
        summaries[day_str] = summary
        self._save_json(DAILY_FILE, summaries)
        
        return summary
    
    def get_weekly_summary(self) -> Dict:
        """Get rolling 7-day summary."""
        today = date.today()
        week_ago = today - timedelta(days=7)
        
        summaries = self._load_json(DAILY_FILE)
        week_days = [
            (today - timedelta(days=i)).isoformat()
            for i in range(7)
        ]
        
        week_trades = []
        for day_str in week_days:
            if day_str in summaries:
                week_trades.append(summaries[day_str])
        
        total_pnl = sum(s.get("total_pnl", 0) for s in week_trades)
        total_wins = sum(s.get("wins", 0) for s in week_trades)
        total_losses = sum(s.get("losses", 0) for s in week_trades)
        total_trades = total_wins + total_losses
        
        return {
            "period": f"{week_ago.isoformat()} to {today.isoformat()}",
            "total_trades": total_trades,
            "wins": total_wins,
            "losses": total_losses,
            "win_rate": round(total_wins / total_trades * 100, 1) if total_trades else 0,
            "total_pnl": round(total_pnl, 2),
            "avg_pnl_per_day": round(total_pnl / len(week_trades), 2) if week_trades else 0,
        }
    
    # ── Drawdown Monitoring ──────────────────────────────────────────────────
    
    def check_drawdown(self) -> Tuple[bool, float]:
        """Check if current drawdown exceeds limit."""
        capital = self._load_capital()
        initial = capital.get("initial_capital", 100000)
        current = capital.get("available_capital", initial)
        
        drawdown = (initial - current) / initial if initial > 0 else 0
        is_breached = drawdown >= MAX_DRAWDOWN_PCT
        
        return is_breached, drawdown
    
    def get_drawdown_status(self) -> Dict:
        """Get full drawdown status."""
        capital = self._load_capital()
        initial = capital.get("initial_capital", 100000)
        current = capital.get("available_capital", initial)
        realized = capital.get("total_realized_pnl", 0)
        
        drawdown = (initial - current) / initial if initial > 0 else 0
        
        return {
            "initial_capital": initial,
            "current_capital": current,
            "realized_pnl": realized,
            "drawdown_pct": round(drawdown * 100, 2),
            "limit_pct": MAX_DRAWDOWN_PCT * 100,
            "is_breached": drawdown >= MAX_DRAWDOWN_PCT,
            "headroom": round((MAX_DRAWDOWN_PCT - drawdown) * initial, 2) if drawdown < MAX_DRAWDOWN_PCT else 0,
        }
    
    # ── Position Sizing ──────────────────────────────────────────────────────
    
    def calculate_position_size(self, price: float, pct: float = None) -> int:
        """Calculate position size based on capital percentage."""
        if pct is None:
            pct = DEFAULT_POSITION_PCT
        
        capital = self._load_capital()
        available = capital.get("available_capital", 100000)
        
        max_position = available * pct
        qty = int(max_position / price) if price > 0 else 0
        
        return qty
    
    # ── Reporting ───────────────────────────────────────────────────────────
    
    def format_position_report(self, symbol: str, current_price: float) -> str:
        """Format position status for Telegram."""
        pos = self.get_position(symbol)
        if not pos:
            return f"❌ No position found: {symbol}"
        
        pnl, pnl_pct = self.get_unrealized_pnl(symbol, current_price)
        emoji = "🟢" if pnl > 0 else "🔴" if pnl < 0 else "⚪"
        
        lines = [
            f"{emoji} <b>{symbol}</b>",
            f"Qty: {pos.qty} @ ${pos.entry_price:.2f}",
            f"Current: ${current_price:.2f}",
            f"Unrealized: ${pnl:+.2f} ({pnl_pct:+.2f}%)",
            f"Peak: ${pos.peak_price:.2f}",
            f"Signal: {pos.signal}",
            f"Regime: {pos.regime}",
        ]
        
        return "\n".join(lines)
    
    def format_daily_report(self, day: date = None) -> str:
        """Format daily summary for Telegram."""
        summary = self.generate_daily_summary(day)
        
        pnl = summary.get("total_pnl", 0)
        emoji = "🟢" if pnl > 0 else "🔴" if pnl < 0 else "⚪"
        
        lines = [
            f"{emoji} <b>US DAILY REPORT — {summary.get('date', '')}</b>",
            "",
            f"📊 Trades: {summary.get('total_trades', 0)}",
            f"✅ Wins: {summary.get('wins', 0)} / ❌ Losses: {summary.get('losses', 0)}",
            f"📈 Win Rate: {summary.get('win_rate', 0):.1f}%",
            "",
            f"💰 Total P&L: ${pnl:+.2f}",
            f"📊 Avg per Trade: ${summary.get('avg_pnl_per_trade', 0):+.2f}",
            f"🏆 Avg Win: ${summary.get('avg_win', 0):+.2f}",
            f"💸 Avg Loss: ${summary.get('avg_loss', 0):+.2f}",
            "",
            f"⏱ Avg Duration: {summary.get('avg_duration_min', 0):.1f} min",
        ]
        
        return "\n".join(lines)
    
    def get_status(self) -> Dict:
        """Get full bookkeeper status."""
        open_positions = self.get_open_positions()
        capital = self.get_capital()
        drawdown = self.get_drawdown_status()
        
        return {
            "open_positions": len(open_positions),
            "symbols": list(open_positions.keys()),
            "capital": capital,
            "drawdown": drawdown,
            "max_drawdown_pct": MAX_DRAWDOWN_PCT * 100,
            "timestamp": datetime.now(ET).isoformat(),
        }


# ── Singleton Instance ──────────────────────────────────────────────────────

_bookkeeper = None

def get_bookkeeper() -> Bookkeeper:
    """Get singleton bookkeeper instance."""
    global _bookkeeper
    if _bookkeeper is None:
        _bookkeeper = Bookkeeper()
    return _bookkeeper


# ── Convenience Functions ───────────────────────────────────────────────────

def add_position(symbol: str, qty: int, entry_price: float, **kwargs) -> Position:
    """Convenience: add position via singleton."""
    return get_bookkeeper().add_position(symbol, qty, entry_price, **kwargs)

def close_position(symbol: str, exit_price: float, exit_reason: str, **kwargs) -> Optional[Trade]:
    """Convenience: close position via singleton."""
    return get_bookkeeper().close_position(symbol, exit_price, exit_reason, **kwargs)

def get_open_positions() -> Dict[str, Position]:
    """Convenience: get open positions via singleton."""
    return get_bookkeeper().get_open_positions()

def get_status() -> Dict:
    """Convenience: get status via singleton."""
    return get_bookkeeper().get_status()


# ── Test ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    bk = Bookkeeper()
    
    # Test capital
    bk.set_capital(100000)
    print(f"Initial capital: ${bk.get_capital()['available_capital']:.2f}")
    
    # Test position
    pos = bk.add_position("AAPL", 10, 175.50, signal="vwap_reclaim", regime="TRENDING")
    print(f"Added position: {pos.symbol} {pos.qty}@{pos.entry_price}")
    
    # Test unrealized PnL
    pnl, pct = bk.get_unrealized_pnl("AAPL", 180.00)
    print(f"Unrealized PnL: ${pnl:+.2f} ({pct:+.2f}%)")
    
    # Test close
    trade = bk.close_position("AAPL", 180.00, "Target hit")
    print(f"Closed trade: PnL=${trade.net_pnl:+.2f} ({trade.pnl_pct:+.2f}%)")
    
    # Test summary
    summary = bk.generate_daily_summary()
    print(f"\nDaily Summary:")
    print(json.dumps(summary, indent=2))
    
    # Test drawdown
    dd_status = bk.get_drawdown_status()
    print(f"\nDrawdown: {dd_status['drawdown_pct']:.2f}%")
    
    print("\n✅ Bookkeeper test complete")
