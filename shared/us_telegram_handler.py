"""
US Telegram Handler — Shared Notification System
================================================

Shared between TASI and US systems.
Uses same bot but with prefixed commands.

Commands:
  /us_status      — US account status
  /us_positions   — US open positions
  /us_picks       — Latest US picks
  /us_buy SYM QTY — Manual buy
  /us_sell SYM QTY — Manual sell
  /us_stand_down  — Halt US trading
  /us_resume      — Resume US trading

Usage:
    from us_telegram_handler import USTelegramBot
    
    bot = USTelegramBot(token="YOUR_BOT_TOKEN")
    bot.send_message("📊 US market open — 5 picks ready")
"""

import os
import json
import logging
from datetime import datetime
from typing import Optional, Dict, List
import pytz

ET = pytz.timezone("America/New_York")

# Try to import python-telegram-bot
try:
    from telegram import Bot, Update
    from telegram.ext import Application, CommandHandler, ContextTypes
    HAS_TELEGRAM = True
except ImportError:
    HAS_TELEGRAM = False
    print("Warning: python-telegram-bot not installed")

# Load environment variables from .env file (check parent dir too)
_ENV_FILE = os.path.join(os.path.dirname(__file__), ".env")
_ENV_FILE_PARENT = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")

for env_path in [_ENV_FILE, _ENV_FILE_PARENT]:
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())

# ── Logging ─────────────────────────────────────────────────────────────────
log = logging.getLogger("us_telegram")
if not log.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    ))
    log.addHandler(handler)
    log.setLevel(logging.INFO)

# ── Constants ──────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
US_DATA_DIR = os.path.join(BASE_DIR, "us-exec")


class USTelegramBot:
    """Telegram bot handler for US trading system."""
    
    def __init__(self, token: Optional[str] = None, chat_id: Optional[str] = None):
        """
        Initialize bot.
        
        Args:
            token: Bot token (or from US_BOT_TOKEN env)
            chat_id: Chat ID (or from US_CHAT_ID env)
        """
        self.token = token or os.environ.get("US_BOT_TOKEN")
        self.chat_id = chat_id or os.environ.get("US_CHAT_ID")
        
        if not self.token:
            raise ValueError("US_BOT_TOKEN required")
        
        if HAS_TELEGRAM:
            self.bot = Bot(token=self.token)
        else:
            self.bot = None
            log.warning("Telegram not available — messages will be logged only")
    
    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """Send message to chat."""
        log.info(f"[TELEGRAM] {text[:100]}...")
        
        if not self.bot or not self.chat_id:
            return False
        
        try:
            import asyncio
            # Create a new event loop for this operation to avoid conflicts
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(self.bot.send_message(
                    chat_id=self.chat_id,
                    text=text,
                    parse_mode=parse_mode
                ))
                return True
            finally:
                loop.close()
        except Exception as e:
            log.error(f"Send failed: {e}")
            return False
    
    def send_picks(self, picks: List[Dict], mode: str = "premarket"):
        """Send picks as formatted message."""
        lines = [f"📊 <b>US {mode.upper()} PICKS</b> — {len(picks)} stocks"]
        lines.append("")
        lines.append("| # | Symbol | Price | Score | Gap | Sector |")
        lines.append("|---|---|---|---|---|---|")
        
        for i, p in enumerate(picks[:10], 1):
            sym = p['symbol']
            price = p['price']
            score = p['score']
            gap = p['gap_pct']
            sector = p.get('sector', '?')[:15]
            lines.append(f"| {i} | {sym} | ${price:.2f} | {score:.0f} | {gap:+.1f}% | {sector} |")
        
        msg = "\n".join(lines)
        self.send_message(msg)
    
    def send_trade_alert(self, symbol: str, side: str, qty: int,
                         price: float, reason: str = ""):
        """Send trade execution alert."""
        emoji = "🟢" if side == "buy" else "🔴"
        msg = (
            f"{emoji} <b>US TRADE — {side.upper()}</b>\n"
            f"Symbol: {symbol}\n"
            f"Qty: {qty}\n"
            f"Price: ${price:.2f}\n"
        )
        if reason:
            msg += f"Reason: {reason}\n"
        
        self.send_message(msg)
    
    def send_status(self, capital: Dict, positions: List[Dict]):
        """Send account status."""
        lines = ["📊 <b>US ACCOUNT STATUS</b>"]
        lines.append("")
        lines.append(f"Cash: ${capital.get('cash', 0):,.2f}")
        lines.append(f"Equity: ${capital.get('equity', 0):,.2f}")
        lines.append(f"Buying Power: ${capital.get('buying_power', 0):,.2f}")
        lines.append("")
        lines.append(f"Positions: {len(positions)}")
        
        for p in positions:
            pl = p.get('unrealized_pl', 0)
            pl_pct = p.get('unrealized_plpc', 0) * 100
            emoji = "🟢" if pl >= 0 else "🔴"
            lines.append(
                f"{emoji} {p['symbol']}: {p['qty']} @ ${p['avg_entry_price']:.2f} → "
                f"${p['current_price']:.2f} (P&L: {pl:+.2f}, {pl_pct:+.1f}%)"
            )
        
        self.send_message("\n".join(lines))
    
    def send_error(self, error: str):
        """Send error alert."""
        self.send_message(f"🚨 <b>US ERROR</b>\n{error}")


# ── Simple Notification Function ────────────────────────────────────────────

def notify(message: str, level: str = "info"):
    """Simple notification wrapper."""
    bot = USTelegramBot()
    
    if level == "error":
        bot.send_error(message)
    elif level == "trade":
        bot.send_message(message)
    else:
        bot.send_message(message)


# ── Test ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import os
    
    if not os.environ.get("US_BOT_TOKEN"):
        print("Set US_BOT_TOKEN environment variable")
        print("Or use the same bot token as TASI with US_CHAT_ID")
        exit(1)
    
    bot = USTelegramBot()
    
    # Test messages
    bot.send_message("🧪 <b>US Bot Test</b>\nIf you see this, US Telegram is working!")
    
    # Test picks
    test_picks = [
        {"symbol": "AAPL", "price": 175.5, "score": 75, "gap_pct": 2.5, "sector": "Technology"},
        {"symbol": "MSFT", "price": 330.0, "score": 70, "gap_pct": 1.8, "sector": "Technology"},
    ]
    bot.send_picks(test_picks)
    
    # Test status
    test_capital = {"cash": 10000, "equity": 15000, "buying_power": 20000}
    test_positions = [
        {"symbol": "AAPL", "qty": 10, "avg_entry_price": 170, "current_price": 175.5, "unrealized_pl": 55, "unrealized_plpc": 0.032},
    ]
    bot.send_status(test_capital, test_positions)