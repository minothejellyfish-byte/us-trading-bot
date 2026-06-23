# US Trading System — v1.0

## Status: Production Ready
## Date: 2026-06-23

---

## Overview
US paper trading system with TASI-level sophistication.

## Features Implemented

### Core Infrastructure
- ✅ Alpaca API integration
- ✅ WebSocket real-time data (PRIMARY source)
- ✅ File locking (fcntl advisory locks)
- ✅ Order deduplication

### Trading Strategy
- ✅ Market regime classification (SPY/VIX/sectors)
- ✅ Evaluator (two-gate: validation + scoring)
- ✅ VWAP direction filter
- ✅ Dynamic time stops (regime-aware)
- ✅ Tiered exits (trailing stop, VWAP breakdown, recovery score)
- ✅ Cycle management (4/3/2 cycles, blocked symbols)
- ✅ Position upgrade logic

### Risk Management
- ✅ Bookkeeper (FIFO matching, PnL tracking)
- ✅ Order history CSV
- ✅ Capital management
- ✅ Drawdown monitoring

### Bot Commands
- ✅ /us_status
- ✅ /us_positions
- ✅ /us_picks
- ✅ /us_history
- ✅ /us_pnl
- ✅ /us_closeall
- ✅ /us_stand_down
- ✅ /us_resume

### Monitoring
- ✅ Watchdog (poller activity, stale positions, rapid entries)
- ✅ Daily summary

## File Inventory
| File | Purpose |
|------|---------|
| us_poller.py | Main trading logic |
| us_screener.py | Pre-market screening |
| us_midscreen.py | Intraday screening |
| us_evaluator.py | Two-gate evaluation |
| us_market_regime.py | Regime classification |
| us_bookkeeper.py | Position/PnL tracking |
| us_order_history.py | CSV history |
| us_alpaca_ws.py | WebSocket data |
| us_exit_triggers.py | Exit logic |
| us_tier_exits.py | Tiered exits |
| us_vwap_filter.py | VWAP direction |
| us_time_stops.py | Dynamic time stops |
| us_cycle_manager.py | Cycle management |
| us_watchdog.py | System health |
| us_bot.py | Telegram interface |

## Cycle Limits
| Regime | Cycles | Cooldown |
|--------|--------|----------|
| TRENDING | 4 | 30 min |
| NEUTRAL | 3 | 45 min |
| DEFENSIVE | 2 | 60 min |

## Entry Triggers
1. Gap-up / in-zone entry
2. VWAP reclaim (with direction filter)
3. Breakout

## Exit Triggers
1. Hard stop (regime-based %)
2. Target hit (regime-based %)
3. Trailing stop (peak-based)
4. Time stop (dynamic)
5. VWAP breakdown
6. Recovery score (weak)
7. Tiered exits (partial)
8. Hard close (15:45 ET)

## Data Sources (Priority)
1. Alpaca WebSocket (primary)
2. Alpaca REST (fallback)
3. yfinance (last resort)

## Version History
| Version | Date | Changes |
|---------|------|---------|
| v1.0 | 2026-06-23 | Initial release |
