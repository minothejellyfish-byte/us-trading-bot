# TASI vs US — Detailed File-by-File Comparison
## Component Deep Dive | 2026-06-15

---

## File Count Comparison

| System | Python Files | Ratio |
|--------|-------------|-------|
| **TASI** | 42 files | 3.2× more |
| **US** | 13 files | Baseline |

---

## Core Trading Files

### TASI Files → US Equivalents

| # | TASI File | Lines | Purpose | US Equivalent | US Lines | Status |
|---|-----------|-------|---------|--------------|----------|--------|
| 1 | **screener.py** | 885 | Pre-market + mid-session screen | **us_screener.py** | 591 | ⚠️ Partial |
| 2 | **poller.py** | 2,200 | Price polling, entry/exit signals | **us_poller.py** | 1,002 | ⚠️ Partial |
| 3 | **bot.py** | 2,179 | Telegram interface, commands | **us_bot.py** | 508 | ⚠️ Partial |
| 4 | **bookkeeper.py** | 1,200 | Capital sync, PnL, reconciliation | **NONE** | 0 | ❌ Missing |
| 5 | **market_regime.py** | 200 | Regime classification | **us_market_regime.py** | 357 | ✅ Better |
| 6 | **midscreen_ws.py** | ~400 | Mid-session rescreen | **us_midscreen.py** | 487 | ✅ Equivalent |
| 7 | **post_market.py** | 600 | Daily PnL analysis, reporting | **us_daily_report.py** | 207 | ⚠️ Simpler |
| 8 | **order_helpers.py** | 350 | Order constants, status codes | **NONE** | 0 | ❌ Missing |
| 9 | **history_io.py** | 500 | Order history, FIFO PnL | **NONE** | 0 | ❌ Missing |
| 10 | **derayah_api.py** | ~300 | Derayah API wrapper | **alpaca_api.py** | 419 | ✅ Equivalent |
| 11 | **derayah_session_manager.py** | 1,500 | Session lifecycle (3-phase) | **NONE** | 0 | ❌ N/A |
| 12 | **tasi_watchdog.py** | ~200 | Activity logging | **NONE** | 0 | ❌ Missing |
| 13 | **ws_probe.py** | ~300 | WebSocket price feed | **NONE** | 0 | ❌ N/A |
| 14 | **ws_logger.py** | ~150 | WebSocket frame logging | **NONE** | 0 | ❌ N/A |
| 15 | **weekly_report_v5.py** | ~400 | Weekly analysis report | **NONE** | 0 | ❌ Missing |
| 16 | **capital_tracker.py** | ~200 | Capital snapshot tracking | **NONE** | 0 | ❌ Missing |
| 17 | **bot_commands.py** | ~300 | Command handler functions | **us_telegram_handler.py** | ? | ⚠️ Partial |
| 18 | **tasi_telegram_handler.py** | ~250 | Telegram message handler | **NONE** | 0 | ❌ Missing |

---

## Probe System (TASI Only)

| Component | TASI File | Purpose | US Status |
|-----------|-----------|---------|-----------|
| **ws_probe.py** | WebSocket price feed | Real-time prices from Derayah WS | ❌ N/A |
| **ws_logger.py** | WebSocket logging | Log WS frames to JSONL | ❌ N/A |
| **ws_keepalive_v2.sh** | WS monitor | Monitor and restart ws_probe | ❌ N/A |
| **ws_frames_raw.log** | WS output | Raw price feed data | ❌ N/A |
| **ws_frames.json** | Parsed WS | Processed price data | ❌ N/A |

**A A — US doesn't need WS probe because Alpaca provides prices via API.**

---

## Bookkeeper System (TASI Only)

| Component | TASI File | Purpose | US Status |
|-----------|-----------|---------|-----------|
| **bookkeeper.py** | 1,200 lines | Capital sync, PnL, reconciliation | ❌ Missing |
| **history_io.py** | 500 lines | Order history, FIFO matching | ❌ Missing |
| **capital_tracker.py** | ~200 lines | Capital snapshot JSONL | ❌ Missing |
| **daily_pnl.csv** | Output | Daily PnL summary | ❌ Missing |
| **order_history.csv** | Output | Order history with FIFO | ❌ Missing |

**What Bookkeeper Does (that US doesn't):**
1. **Every 5 min:** Sync capital from browser localStorage
2. **End of day:** Calculate PnL using FIFO matching
3. **Reconcile:** Fix ghost positions (book vs actual)
4. **Record:** Write daily_pnl.csv
5. **Track:** Capital snapshots every 5 min

**A A — US NEEDS a bookkeeper because:**
- Alpaca doesn't provide historical PnL CSV
- US has no FIFO matching
- US has no ghost position detection
- US has no daily reporting

---

## Regime System (Both Have)

| Feature | TASI | US | Comparison |
|---------|------|-----|------------|
| **File** | market_regime.py (200 lines) | us_market_regime.py (357 lines) | US has MORE lines |
| **Regimes** | TRENDING/NEUTRAL/DEFENSIVE | TRENDING/NEUTRAL/DEFENSIVE | Same |
| **Indicators** | Trend, volatility, breadth | SPY, VIX, sector ETFs | US more detailed |
| **Sector Analysis** | Basic | 11 sector ETFs | US better |
| **Classification** | Every 30 min | Every 30 min | Same |
| **Confirmation** | 60 min stability | Not specified | TASI more robust |
| **Output** | regime.json | us_regime.json | Equivalent |

**A A — US regime system is actually MORE advanced than TASI!**
- US analyzes 11 sector ETFs
- TASI only has basic breadth
- US has 357 lines vs TASI's 200 lines

---

## Session Manager (TASI Only)

| Component | TASI File | Purpose | US Status |
|-----------|-----------|---------|-----------|
| **derayah_session_manager.py** | 1,500 lines | 3-phase session lifecycle | ❌ N/A |
| **Phase 1: Capture** | Manual login → token capture | Not needed | Alpaca API key |
| **Phase 2: Maintain** | SSO refresh every 5 min | Not needed | Alpaca key doesn't expire |
| **Phase 3: Recovery** | Auto-login via email OTP | Not needed | No 2FA |
| **CDP Navigation** | Chrome DevTools Protocol | Not needed | No browser |
| **Tab Management** | Deduplication, cleanup | Not needed | No tabs |

**A A — Session manager is NOT applicable to US.**

---

## What US is Missing (Detailed)

### A. Trading Strategy (7 gaps)

| # | Gap | TASI File | Impact |
|---|-----|-----------|--------|
| 1 | **Market Open Cooldown** | poller.py | US enters noisy first 15 min |
| 2 | **VWAP Direction Filter** | poller.py | US enters falling VWAP |
| 3 | **Recovery Score** | poller.py | US sells into temporary dips |
| 4 | **Tiered Profit Targets** | poller.py | US misses profit opportunities |
| 5 | **Dynamic Time Stops** | poller.py | US uses fixed 30 min |
| 6 | **VWAP Exit Control** | poller.py | US exits trends too early |
| 7 | **Cycle Management** | poller.py | US no position recycling |

### B. Infrastructure (5 gaps)

| # | Gap | TASI File | Impact |
|---|-----|-----------|--------|
| 8 | **Bookkeeper** | bookkeeper.py | US no PnL tracking |
| 9 | **Order History** | history_io.py | US no FIFO matching |
| 10 | **File Locking** | order_helpers.py | US JSON corruption risk |
| 11 | **Deduplication** | history_io.py | US duplicate orders |
| 12 | **Watchdog** | tasi_watchdog.py | US no activity logging |

### C. Bot/UX (6 gaps)

| # | Gap | TASI File | Impact |
|---|-----|-----------|--------|
| 13 | **/History command** | bot.py | US no trade history |
| 14 | **/PnL command** | bot.py | US no daily PnL |
| 15 | **/HisCap command** | bot.py | US no capital history |
| 16 | **/Fund command** | bot.py | US no deposit tracking |
| 17 | **/Withdraw command** | bot.py | US no withdrawal tracking |
| 18 | **/CloseAll command** | bot.py | US can't emergency close |

---

## Priority Recommendation

### Phase 1: Trading Strategy (Critical)
Implement gaps #1-7 from poller.py
- Market open cooldown
- VWAP direction filter
- Recovery score
- Tiered profit targets
- Dynamic time stops
- VWAP exit control
- Cycle management

### Phase 2: Infrastructure (High)
Create missing files:
- us_bookkeeper.py (from bookkeeper.py)
- us_history_io.py (from history_io.py)
- us_order_helpers.py (from order_helpers.py)
- us_watchdog.py (from tasi_watchdog.py)

### Phase 3: Bot Commands (Medium)
Add commands to us_bot.py:
- /us_history
- /us_pnl
- /us_hiscap
- /us_fund
- /us_withdraw
- /us_closeall

---

## A A — The US system is missing 18 key components from TASI.

**Most critical:**
1. **Bookkeeper** — No PnL tracking at all
2. **Recovery Score** — Selling into temporary dips
3. **Profit Targets** — Missing profit opportunities
4. **File Locking** — JSON corruption risk

**Say "Do it" and I'll start implementing.**

Or specify which components:
- "Bookkeeper first" — Start with PnL tracking
- "Trading strategy" — Cooldown + filters + recovery
- "All" — Everything

🪼 Mino
