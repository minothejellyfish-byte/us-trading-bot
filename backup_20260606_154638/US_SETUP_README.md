# US Trading System — Setup Guide

## Strategy Summary

**The US trading system is a regime-based, Sharia-compliant intraday momentum strategy running on Alpaca Markets.**

**🟡 CURRENT PHASE: Paper Trading (10-Day Challenge)**
- **Started:** June 4, 2026
- **Ends:** June 18, 2026 (10 trading days)
- **Capital:** $100,000 (paper)
- **Goal:** Validate strategy before going live
- **Tracking:** Daily P&L, win rate, best/worst trades

| Component | Description |
|-----------|-------------|
| **Regime Engine** | Classifies market into `TRENDING` / `NEUTRAL` / `DEFENSIVE` based on SPY+VIX |
| **Screeners** | Pre-market gap scanner + 3 mid-session screens (09:20, 10:00, 11:30, 13:30 ET) |
| **Entry Signals** | Gap-up hold, VWAP reclaim, breakout — regime-adaptive position sizing |
| **Exits** | 5% hard stop, 2% trail trigger → 3% trail stop, 30-min time stop, 15:45 ET hard close |
| **Trade Logger** | Every trade logged with entry price, signal, P&L, regime, win rate |
| **Sharia Filter** | Every buy validated against 211-stock universe before execution |
| **Daily Report** | Auto-sent to Telegram at 23:10 GMT+3 |
| **Paper Phase** | 10 days paper trading → decision to go live |

---

---

## Regime Parameters (Dynamic)

| Regime | Target | Hard Stop | Trail Trigger | Trail Stop | Position Size | Max Pos |
|--------|--------|-----------|---------------|------------|---------------|---------|
| **TRENDING** | 3.0% | 4.0% | 2.5% | 3.5% | 50% / 30% | 5 |
| **NEUTRAL** | 2.0% | 5.0% | 2.0% | 3.0% | 40% / 25% | 3 |
| **DEFENSIVE** | 1.5% | 3.0% | 1.5% | 2.5% | 30% / 20% | 2 |

---

## Trade Logging

Every trade is logged with:
- **Timestamp** (ET), symbol, action (BUY/SELL), qty, price
- **Signal type**: gap_up, vwap_reclaim, breakout, hard_stop, target, trail_stop, time_stop
- **P&L calculation**: Dollar P&L, percentage, spread cost
- **Regime**: Which regime was active when trade was taken
- **Daily/weekly summaries**: Win rate, avg P&L, avg duration, best/worst trades

Log files:
- `us_trades_YYYY-MM-DD.json` — Daily trade journals
- `us_daily_summary_YYYY-MM-DD.json` — Daily performance summaries
- `US_SETUP_README.md` — This document

---

## Files Created

| File | Purpose | Status |
|------|---------|--------|
| `us_sharia_universe.py` | Sharia-compliant stock list (211 stocks) | ✅ Ready |
| `alpaca_api.py` | Broker API wrapper with Sharia validation | ✅ Ready |
| `us_market_regime.py` | SPY+VIX regime classifier | ✅ Ready |
| `us_trade_logger.py` | Trade journal + P&L + daily summary | ✅ Ready |
| `us_screener.py` | Pre-market gap scanner | ✅ Ready |
| `us_midscreen.py` | Mid-session screener (3 runs/day) | ✅ Ready |
| `us_poller.py` | Entry/exit signal poller (regime-adaptive) | ✅ Ready |
| `us_bot.py` | Telegram bot (`/us_*` commands) | ✅ Ready |
| `us_capital.json` | Capital tracking | ✅ Ready |
| `us_positions.json` | Position tracking | ✅ Ready |
| `start_us_system.sh` | Startup script | ✅ Ready |
| `stop_us_system.sh` | Stop script | ✅ Ready |
| `crontab.txt` | Cron schedule | ✅ Ready |
| `MIGRATION_PLAN_US_MARKET.md` | Architecture spec | ✅ Ready |

---

## What You Need

### 1. Alpaca Account (Free)
1. Go to https://app.alpaca.markets/signup
2. Sign up (no deposit needed for paper trading)
3. Go to **Paper Trading** dashboard
4. Generate API keys:
   - Paper API Key ID
   - Paper Secret Key

### 2. Environment Variables

Already configured in `/home/mino/us-exec/.env`:

```bash
ALPACA_API_KEY=PKZ7LS...
ALPACA_SECRET_KEY=9bmcJA...
ALPACA_PAPER=true
US_BOT_TOKEN=772598...
US_CHAT_ID=-5235925419
```

---

## Quick Test

```bash
cd /home/mino/us-exec

# Test Sharia universe
python3 us_sharia_universe.py
# Expected: "Sharia-compliant universe: 211 stocks"

# Test Alpaca connection (requires API keys)
python3 alpaca_api.py
# Expected: Account info, positions, market clock

# Test screener (runs at 09:20 ET)
python3 us_screener.py
# Expected: Top 10 picks with scores

# Test bot (keeps running)
python3 us_bot.py
# Expected: "US Bot Online" in Telegram
```

---

## Directory Structure

```
/home/mino/
├── tasi-exec/           # Saudi system (RUNNING)
│   ├── bot.py
│   ├── poller.py
│   └── ...
│
└── us-exec/             # US system (NEW — ready to test)
    ├── us_sharia_universe.py    # 211 Sharia stocks
    ├── alpaca_api.py            # Broker wrapper
    ├── us_screener.py           # Pre-market scanner
    ├── us_poller.py             # Entry/exit poller
    ├── us_bot.py                # Telegram bot
    ├── us_capital.json          # Capital tracking
    ├── us_positions.json        # Position tracking
    ├── start_us_system.sh       # Startup script
    ├── stop_us_system.sh        # Stop script
    ├── crontab.txt              # Cron schedule
    ├── .env                     # API keys (real)
    └── US_SETUP_README.md       # This file
```

---

## Status Update — 2026-06-03 18:00 GMT+3

✅ **Alpaca Connected Successfully!**

| Field | Value |
|-------|-------|
| Account ID | 877890df-8e9c-4248-b02f-91f27acafbf3 |
| Status | ACTIVE |
| Cash | $100,000.00 |
| Equity | $100,000.00 |
| Buying Power | $200,000.00 |
| Portfolio Value | $100,000.00 |
| Positions | 0 |
| Market | OPEN |

✅ **Sharia Compliance Check Working**
- AAPL: ✅ Compliant
- MSFT: ✅ Compliant
- JPM: ❌ Bank (excluded)
- LMT: ❌ Defense (excluded)

✅ **System files in place**
- `us_screener.py` — Ready
- `us_poller.py` — Ready (NEW)
- `us_bot.py` — Ready
- `.env` — Configured with real keys
- `us_capital.json` — Ready
- `us_positions.json` — Ready
- `US_PAPER_TRADING_10DAY.md` — Tracking log created
- `us_daily_report.py` — Auto Telegram reports
- Systemd services created
- Cron schedule defined
- Daily P&L reports enabled

---

## 📊 10-Day Paper Trading Challenge

### Schedule
| Day | Date | Status |
|-----|------|--------|
| 1 | June 4 (Thu) | 🟡 Starting today |
| 2 | June 5 (Fri) | ⏳ Pending |
| 3 | June 8 (Mon) | ⏳ Pending |
| 4 | June 9 (Tue) | ⏳ Pending |
| 5 | June 10 (Wed) | ⏳ Pending |
| 6 | June 11 (Thu) | ⏳ Pending |
| 7 | June 12 (Fri) | ⏳ Pending |
| 8 | June 15 (Mon) | ⏳ Pending |
| 9 | June 16 (Tue) | ⏳ Pending |
| 10 | June 17 (Wed) | ⏳ Pending |

### Target Metrics
- **Daily target:** 1-3% return per day
- **Win rate target:** >60%
- **Max drawdown:** <5%
- **Profit factor:** >1.5

### After 10 Days
- **Profitable →** Fund live Alpaca account ($5K minimum)
- **Break-even →** Extend paper trading 5 more days
- **Losing →** Review strategy, fix issues, restart paper

### Auto-Tracking
- Daily P&L report sent to Telegram at 23:10 GMT+3
- All trades logged to `us_trades_YYYY-MM-DD.json`
- Performance tracked in `US_PAPER_TRADING_10DAY.md`

---

---

## Systemd Services

| Service | Purpose | Command |
|---------|---------|---------|
| `us-trading-bot.service` | Telegram bot (always on) | `systemctl --user start us-trading-bot.service` |
| `us-trading-poller.service` | Entry/exit poller (market hours) | `systemctl --user start us-trading-poller.service` |

Enable on boot:
```bash
systemctl --user enable us-trading-bot.service
```

---

## Cron Schedule

| Time (GMT+3) | Time (ET) | Task |
|--------------|-----------|------|
| 16:20 | 09:20 | Pre-market screener |
| 17:00 | 10:00 | Mid-screen 1 (early momentum) |
| 18:30 | 11:30 | Mid-screen 2 (mid-morning) |
| 20:30 | 13:30 | Re-screen (afternoon setups) |
| 16:30 | 09:30 | Start poller |
| 23:00 | 16:00 | Stop poller |
| 23:05 | 16:05 | Post-market report |
| 07:00 | 00:00 | Daily cleanup |

Install:
```bash
crontab /home/mino/us-exec/crontab.txt
```

---

## Next Steps

### Phase 1: Data Only (This Week)
1. ✅ Set up Alpaca paper account
2. ✅ Add environment variables
3. ✅ Alpaca API connected
4. ✅ Poller built
5. ✅ Capital/position tracking
6. ✅ Systemd services
7. ✅ Cron schedule
8. [ ] Install cron jobs
9. [ ] Enable systemd services
10. [ ] Test bot commands
11. [ ] Run screener at 09:20 ET daily
12. [ ] Observe picks for 5 days
13. **NO TRADING** — just data

### Phase 2: Paper Trading (Next Week)
1. Start `us_bot.py` and `us_poller.py`
2. Test `/us_status`, `/us_picks` commands
3. Paper trade with small size
4. Compare P&L with TASI

### Phase 3: Live Trading (Week 3)
1. Fund Alpaca account ($5K minimum recommended)
2. Switch `ALPACA_PAPER="false"`
3. Start with $1K positions
4. Scale up gradually

---

## Sharia Compliance

### Stocks Included (211)
- Technology: AAPL, MSFT, NVDA, AVGO, ADBE, CRM, ORCL, etc.
- Healthcare: JNJ, UNH, LLY, PFE, ABBV, TMO, etc.
- Consumer: PG, KO, PEP, WMT, COST, NKE, etc.
- Industrials: CAT, DE, HON, UPS, CSX, etc.
- Energy: XOM, CVX, COP, EOG, etc.

### Stocks Excluded
- Banks: JPM, BAC, WFC, C, GS
- Alcohol: STZ, DEO, MO, PM
- Gambling: MGM, CZR, WYNN, DKNG
- Pork: TSN, HRL
- Defense: LMT, NOC, RTX

### Verification
```python
from us_sharia_universe import is_sharia_compliant

is_sharia_compliant("AAPL")  # True
is_sharia_compliant("JPM")   # False
```

---

## Commands

| Command | Purpose |
|---------|---------|
| `/us_status` | Account status + positions |
| `/us_positions` | Open positions only |
| `/us_picks` | Latest pre-market picks |
| `/us_buy SYM QTY` | Manual buy (Sharia-checked) |
| `/us_sell SYM QTY` | Manual sell |
| `/us_stand_down` | Halt US trading |
| `/us_resume` | Resume US trading |
| `/us_help` | Command list |

---

## Differences from TASI

| | TASI | US |
|---|---|---|
| **Broker** | Derayah (web scraping) | Alpaca (official API) |
| **Data** | TickerChart CDP | Alpaca real-time |
| **Hours** | 10:00-15:00 GMT+3 | 16:30-23:00 GMT+3 |
| **Currency** | SAR | USD |
| **Sharia** | Tadawul filter | HLAL ETF holdings |
| **Keepalive** | Chrome/CDP hack | Not needed |
| **API** | Brittle scraping | Robust official API |
| **Settlement** | T+2 | T+1 |
| **Poller** | Manual (no true poller) | `us_poller.py` auto entry/exit |

---

## Ready?

1. ✅ Alpaca API keys configured
2. ✅ `.env` file in place
3. ✅ All scripts built
4. ✅ Systemd services created
5. ✅ Cron schedule defined

**Next:**
```bash
# Install cron
crontab /home/mino/us-exec/crontab.txt

# Enable bot on boot
systemctl --user enable us-trading-bot.service
systemctl --user start us-trading-bot.service

# Test
systemctl --user start us-trading-poller.service
```

**The system is completely separate from TASI. Both can run simultaneously.**
