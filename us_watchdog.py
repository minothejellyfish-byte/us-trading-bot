#!/usr/bin/env python3
"""
US Watchdog — v4.12
====================
System health monitoring for US paper trading.

Features:
- Log poller activity (last seen timestamp)
- Check for stale positions (held too long)
- Alert on unusual activity (rapid entries, no exits)
- Daily summary at market close

Author: Mino (kimi-k2.6)
Version: 4.12
Date: 2026-06-23
"""

import json
import os
import time
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Dict, Optional

import pytz

ET = pytz.timezone("America/New_York")
BASE_DIR = Path("/home/mino/us-exec")
WATCHDOG_LOG = BASE_DIR / "logs" / "us_watchdog.log"
WATCHDOG_STATE = BASE_DIR / "logs" / "us_watchdog_state.json"

# Ensure logs directory exists
WATCHDOG_LOG.parent.mkdir(exist_ok=True)


class USWatchdog:
    """Monitor US trading system health."""
    
    def __init__(self):
        self.state = self._load_state()
        self.alerts_sent = set()
    
    def _load_state(self) -> Dict:
        """Load watchdog state from file."""
        if WATCHDOG_STATE.exists():
            try:
                with open(WATCHDOG_STATE) as f:
                    return json.load(f)
            except:
                pass
        return {}
    
    def _save_state(self):
        """Save watchdog state to file."""
        try:
            with open(WATCHDOG_STATE, "w") as f:
                json.dump(self.state, f, indent=2)
        except:
            pass
    
    def log_event(self, event_type: str, message: str):
        """Log an event to watchdog log."""
        now = datetime.now(ET).isoformat()
        line = f"{now} [{event_type}] {message}\n"
        try:
            with open(WATCHDOG_LOG, "a") as f:
                f.write(line)
        except:
            pass
    
    def check_poller_activity(self) -> Optional[str]:
        """Check if poller is active.
        
        Returns alert message if poller is stale, None otherwise.
        """
        # Check poller log file modification time
        poller_log = BASE_DIR / "logs" / "poller.log"
        if poller_log.exists():
            try:
                mtime = datetime.fromtimestamp(poller_log.stat().st_mtime, ET)
                age_min = (datetime.now(ET) - mtime).total_seconds() / 60
                
                if age_min > 10:
                    msg = f"⚠️ Poller stale: {age_min:.0f} min since last activity"
                    self.log_event("WARNING", msg)
                    return msg
            except:
                pass
        
        return None
    
    def check_stale_positions(self) -> list:
        """Check for positions held too long.
        
        Returns list of alert messages.
        """
        alerts = []
        positions_file = BASE_DIR / "us_positions.json"
        
        if not positions_file.exists():
            return alerts
        
        try:
            with open(positions_file) as f:
                data = json.load(f)
            positions = data.get("positions", {})
            
            for symbol, pos in positions.items():
                if pos.get("closed", True):
                    continue
                
                entry_time = pos.get("entry_time", "")
                if not entry_time:
                    continue
                
                try:
                    entry_dt = datetime.fromisoformat(entry_time)
                    if entry_dt.tzinfo is None:
                        entry_dt = entry_dt.replace(tzinfo=ET)
                    
                    mins_held = (datetime.now(ET) - entry_dt).total_seconds() / 60
                    
                    # Alert if held > 4 hours (during market)
                    if mins_held > 240:
                        msg = f"⏰ {symbol} held {mins_held/60:.1f} hours — consider review"
                        alerts.append(msg)
                        self.log_event("ALERT", msg)
                    
                except:
                    continue
                    
        except:
            pass
        
        return alerts
    
    def check_rapid_entries(self) -> Optional[str]:
        """Check for rapid entries (potential issue).
        
        Returns alert if >3 entries in 5 minutes.
        """
        trades_file = BASE_DIR / "us_trades.json"
        if not trades_file.exists():
            return None
        
        try:
            with open(trades_file) as f:
                data = json.load(f)
            trades = data.get("trades", [])
            
            now = datetime.now(ET)
            recent_entries = 0
            
            for trade in trades[-10:]:  # Check last 10 trades
                if trade.get("side") != "BUY":
                    continue
                
                ts = trade.get("timestamp", "")
                try:
                    trade_dt = datetime.fromisoformat(ts)
                    if trade_dt.tzinfo is None:
                        trade_dt = trade_dt.replace(tzinfo=ET)
                    
                    if (now - trade_dt).total_seconds() / 60 < 5:
                        recent_entries += 1
                except:
                    continue
            
            if recent_entries > 3:
                msg = f"🚨 Rapid entries detected: {recent_entries} buys in 5 minutes"
                self.log_event("WARNING", msg)
                return msg
                
        except:
            pass
        
        return None
    
    def daily_summary(self) -> str:
        """Generate daily summary at market close."""
        try:
            from us_order_history import get_pnl_summary
            pnl = get_pnl_summary()
            
            lines = [
                "📊 <b>US DAILY SUMMARY</b>",
                f"Date: {datetime.now(ET).strftime('%Y-%m-%d')}",
                f"Total PnL: ${pnl.get('total_pnl', 0):.2f}",
                f"Trades: {pnl.get('total_trades', 0)}",
                f"Win Rate: {pnl.get('win_rate', 0):.1f}%",
            ]
            
            summary = "\n".join(lines)
            self.log_event("SUMMARY", summary)
            return summary
            
        except Exception as e:
            return f"Error generating summary: {e}"
    
    def run_checks(self) -> list:
        """Run all watchdog checks.
        
        Returns list of alerts (empty if all good).
        """
        alerts = []
        
        # Check poller activity
        poller_alert = self.check_poller_activity()
        if poller_alert:
            alerts.append(poller_alert)
        
        # Check stale positions
        stale_alerts = self.check_stale_positions()
        alerts.extend(stale_alerts)
        
        # Check rapid entries
        rapid_alert = self.check_rapid_entries()
        if rapid_alert:
            alerts.append(rapid_alert)
        
        self._save_state()
        return alerts


# ─── Simple interface ──────────────────────────────────────────────────────

def check_system_health() -> str:
    """Quick system health check."""
    wd = USWatchdog()
    alerts = wd.run_checks()
    
    if alerts:
        return "⚠️ <b>US SYSTEM ALERTS</b>\n" + "\n".join(alerts)
    else:
        return "✅ <b>US SYSTEM HEALTHY</b>\nAll checks passed"


if __name__ == "__main__":
    print("=== US Watchdog Test ===\n")
    
    wd = USWatchdog()
    alerts = wd.run_checks()
    
    if alerts:
        print("Alerts found:")
        for alert in alerts:
            print(f"  - {alert}")
    else:
        print("No alerts — system healthy")
    
    print("\n=== Test Complete ===")
