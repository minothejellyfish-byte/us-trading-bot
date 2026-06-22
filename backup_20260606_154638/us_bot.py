"""
US Trading Bot — Telegram Interface
====================================

Handles:
- /us_status — Account status
- /us_positions — Open positions
- /us_picks — Latest picks
- /us_buy SYM QTY — Manual buy
- /us_sell SYM QTY — Manual sell
- /us_stand_down — Halt trading
- /us_resume — Resume trading

Usage:
    python3 us_bot.py
    
    # Or with systemd:
    systemctl --user start us-bot
"""

import os
import sys
import json
import time
import logging
import signal
import threading
from datetime import datetime, date, time as dt_time, timedelta
from typing import Dict, List, Optional

import pytz

# Add shared directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "shared"))

from us_telegram_handler import USTelegramBot
from alpaca_api import AlpacaTrader

# ── Timezones ───────────────────────────────────────────────────────────────
ET = pytz.timezone("America/New_York")

# ── Logging ─────────────────────────────────────────────────────────────────
# Load environment variables from .env file
_ENV_FILE = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_ENV_FILE):
    with open(_ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "us_exec.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("us_bot")

# ── Constants ──────────────────────────────────────────────────────────────
STAND_DOWN_FILE = os.path.join(BASE_DIR, "us_stand_down")
CAPITAL_FILE = os.path.join(BASE_DIR, "us_capital.json")
POSITIONS_FILE = os.path.join(BASE_DIR, "us_positions.json")
PICKS_FILE = os.path.join(BASE_DIR, "us_picks.json")

MARKET_OPEN = dt_time(9, 30)   # ET
MARKET_CLOSE = dt_time(16, 0)  # ET
HARD_CLOSE = dt_time(15, 45)   # ET — no new buys

class USBot:
    """Main US trading bot."""
    
    def __init__(self):
        self.running = True
        self.trader = None
        self.telegram = None
        self._setup_signal_handlers()
    
    def _setup_signal_handlers(self):
        """Handle shutdown signals."""
        for sig in [signal.SIGTERM, signal.SIGINT]:
            signal.signal(sig, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        log.info("Shutdown signal received")
        self.running = False
    
    def init(self):
        """Initialize connections."""
        log.info("Initializing US Bot...")
        
        # Alpaca
        try:
            self.trader = AlpacaTrader()
            acc = self.trader.get_account()
            cash = float(acc['cash']) if isinstance(acc['cash'], str) else acc['cash']
            log.info(f"Alpaca connected: ${cash:,.2f} cash")
        except Exception as e:
            log.error(f"Alpaca connection failed: {e}")
            self.trader = None
        
        # Telegram
        try:
            self.telegram = USTelegramBot()
            log.info("Telegram bot ready")
        except Exception as e:
            log.error(f"Telegram init failed: {e}")
            self.telegram = None
        
        log.info("US Bot initialized")
    
    def is_market_open(self) -> bool:
        """Check if US market is open."""
        now = datetime.now(ET)
        return MARKET_OPEN <= now.time() <= MARKET_CLOSE and now.weekday() < 5
    
    def is_stand_down(self) -> bool:
        """Check if stand down is active."""
        return os.path.exists(STAND_DOWN_FILE)
    
    def save_capital(self):
        """Save capital to JSON."""
        if not self.trader:
            return
        
        try:
            acc = self.trader.get_account()
            capital = {
                "cash": acc["cash"],
                "equity": acc["equity"],
                "buying_power": acc["buying_power"],
                "portfolio_value": acc["portfolio_value"],
                "updated_at": datetime.now(ET).isoformat(),
                "source": "alpaca-api",
            }
            with open(CAPITAL_FILE, "w") as f:
                json.dump(capital, f, indent=2)
        except Exception as e:
            log.error(f"Save capital failed: {e}")
    
    def save_positions(self):
        """Save positions to JSON."""
        if not self.trader:
            return
        
        try:
            positions = self.trader.get_positions()
            data = {
                "date": date.today().isoformat(),
                "time": datetime.now(ET).strftime("%H:%M:%S"),
                "positions": {p["symbol"]: p for p in positions},
            }
            with open(POSITIONS_FILE, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            log.error(f"Save positions failed: {e}")
    
    def get_status(self) -> str:
        """Get formatted status message."""
        lines = ["📊 <b>US SYSTEM STATUS</b>"]
        lines.append("")
        
        # Market status
        now = datetime.now(ET)
        market_open = self.is_market_open()
        lines.append(f"Market: {'🟢 OPEN' if market_open else '🔴 CLOSED'}")
        lines.append(f"Time (ET): {now.strftime('%H:%M:%S')}")
        lines.append(f"Day: {now.strftime('%A')}")
        lines.append("")
        
        # Stand down
        if self.is_stand_down():
            lines.append("🛑 STAND DOWN: ACTIVE")
        else:
            lines.append("🟢 STAND DOWN: Inactive")
        lines.append("")
        
        # Capital
        if self.trader:
            try:
                acc = self.trader.get_account()
                cash = float(acc['cash']) if isinstance(acc['cash'], str) else acc['cash']
                equity = float(acc['equity']) if isinstance(acc['equity'], str) else acc['equity']
                bp = float(acc['buying_power']) if isinstance(acc['buying_power'], str) else acc['buying_power']
                lines.append(f"💰 Capital:")
                lines.append(f"   Cash: ${cash:,.2f}")
                lines.append(f"   Equity: ${equity:,.2f}")
                lines.append(f"   Buying Power: ${bp:,.2f}")
            except:
                lines.append("💰 Capital: Unable to fetch")
        else:
            lines.append("💰 Capital: Not connected")
        lines.append("")
        
        # Positions
        if self.trader:
            try:
                positions = self.trader.get_positions()
                lines.append(f"📈 Positions: {len(positions)}")
                for p in positions:
                    pl = float(p.get('unrealized_pl', 0)) if isinstance(p.get('unrealized_pl'), str) else p.get('unrealized_pl', 0)
                    avg = float(p['avg_entry_price']) if isinstance(p['avg_entry_price'], str) else p['avg_entry_price']
                    curr = float(p['current_price']) if isinstance(p['current_price'], str) else p['current_price']
                    emoji = "🟢" if pl >= 0 else "🔴"
                    lines.append(
                        f"   {emoji} {p['symbol']}: {p['qty']} @ ${avg:.2f} → "
                        f"${curr:.2f} (P&L: {pl:+.2f})"
                    )
            except:
                lines.append("📈 Positions: Unable to fetch")
        
        # Picks
        if os.path.exists(PICKS_FILE):
            with open(PICKS_FILE) as f:
                picks_data = json.load(f)
            picks = picks_data.get("picks", [])
            lines.append(f"\n📋 Picks: {len(picks)} (updated {picks_data.get('time', '?')})")
        
        lines.append("")
        lines.append("Commands: /us_status /us_positions /us_picks /us_stand_down /us_resume")
        
        return "\n".join(lines)
    
    def handle_command(self, text: str) -> str:
        """Handle Telegram command."""
        text = text.strip().lower()
        parts = text.split()
        cmd = parts[0] if parts else ""
        
        if cmd == "/us_status":
            return self.get_status()
        
        elif cmd == "/us_positions":
            if self.trader:
                positions = self.trader.get_positions()
                if not positions:
                    return "📈 No open positions"
                lines = ["📈 <b>US POSITIONS</b>"]
                for p in positions:
                    lines.append(f"{p['symbol']}: {p['qty']} @ ${p['avg_entry_price']:.2f}")
                return "\n".join(lines)
            return "❌ Not connected to broker"
        
        elif cmd == "/us_picks":
            if os.path.exists(PICKS_FILE):
                with open(PICKS_FILE) as f:
                    data = json.load(f)
                picks = data.get("picks", [])
                if not picks:
                    return "📋 No picks available"
                lines = [f"📋 <b>US PICKS</b> — {len(picks)} stocks"]
                for i, p in enumerate(picks[:5], 1):
                    lines.append(f"{i}. {p['symbol']} @ ${p['price']:.2f} (score: {p['score']})")
                return "\n".join(lines)
            return "📋 No picks file found"
        
        elif cmd == "/us_stand_down":
            with open(STAND_DOWN_FILE, "w") as f:
                f.write(f"STAND DOWN at {datetime.now(ET).isoformat()}\n")
            return "🛑 US STAND DOWN activated — no new buys"
        
        elif cmd == "/us_resume":
            if os.path.exists(STAND_DOWN_FILE):
                os.remove(STAND_DOWN_FILE)
            return "🟢 US trading resumed"
        
        elif cmd == "/us_buy":
            if len(parts) < 3:
                return "Usage: /us_buy SYMBOL QTY"
            symbol = parts[1].upper()
            try:
                qty = int(parts[2])
            except:
                return "Invalid quantity"
            if self.trader:
                try:
                    order = self.trader.buy(symbol, qty)
                    return f"🟢 Buy order submitted: {symbol} x{qty} → {order['status']}"
                except Exception as e:
                    return f"❌ Buy failed: {e}"
            return "❌ Not connected to broker"
        
        elif cmd == "/us_sell":
            if len(parts) < 3:
                return "Usage: /us_sell SYMBOL QTY"
            symbol = parts[1].upper()
            try:
                qty = int(parts[2])
            except:
                return "Invalid quantity"
            if self.trader:
                try:
                    order = self.trader.sell(symbol, qty)
                    return f"🔴 Sell order submitted: {symbol} x{qty} → {order['status']}"
                except Exception as e:
                    return f"❌ Sell failed: {e}"
            return "❌ Not connected to broker"
        
        elif cmd == "/us_help":
            return (
                "📖 <b>US Bot Commands</b>\n"
                "/us_status — Account status\n"
                "/us_positions — Open positions\n"
                "/us_picks — Latest picks\n"
                "/us_buy SYM QTY — Manual buy\n"
                "/us_sell SYM QTY — Manual sell\n"
                "/us_stand_down — Halt trading\n"
                "/us_resume — Resume trading"
            )
        
        return None  # Not a US command
    
    def run(self):
        """Main loop."""
        log.info("=" * 60)
        log.info("US TRADING BOT STARTED")
        log.info("=" * 60)
        
        self.init()
        
        if self.telegram:
            self.telegram.send_message("🚀 <b>US Bot Online</b>\nReady for Sharia-compliant US trading")
        
        loop_count = 0
        
        while self.running:
            try:
                now = datetime.now(ET)
                
                # Periodic tasks every 60 seconds
                if loop_count % 60 == 0:
                    # Save capital
                    self.save_capital()
                    
                    # Save positions
                    self.save_positions()
                    
                    # Hard close check
                    if now.time() >= HARD_CLOSE and not self.is_stand_down():
                        log.info("15:45 ET — auto STAND DOWN")
                        with open(STAND_DOWN_FILE, "w") as f:
                            f.write(f"Hard close at {now.isoformat()}\n")
                        if self.telegram:
                            self.telegram.send_message("⏰ <b>US Hard Close</b>\nAuto STAND DOWN at 15:45 ET")
                
                loop_count += 1
                time.sleep(1)
                
            except Exception as e:
                log.error(f"Main loop error: {e}")
                time.sleep(5)
        
        log.info("US Bot stopped")


def main():
    """Entry point."""
    bot = USBot()
    bot.run()


if __name__ == "__main__":
    main()
