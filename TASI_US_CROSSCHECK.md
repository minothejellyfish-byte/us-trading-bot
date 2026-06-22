# TASI v4.3 vs US System — Component Cross-Check
## Detailed Comparison | 2026-06-15

---

## Section 1: System Overview

| Component | TASI v4.3 | US System | Status | Gap |
|-----------|-----------|-----------|--------|-----|
| **Market** | TASI (Saudi) | US (NYSE/NASDAQ) | Different | N/A |
| **Trading Hours** | 10:00-15:00 KSA | 09:30-16:00 ET | Different | N/A |
| **Broker Interface** | Chrome CDP + Derayah web | Alpaca API | Different | N/A |
| **Browser as Source of Truth** | Yes (localStorage) | No (API responses) | Different | N/A |
| **Sharia Compliance** | Yes | Yes | ✅ Same | None |
| **Paper Trading** | No (live) | Yes | Different | N/A |

---

## Section 2: Architecture Components

### 2.1 Screener

| Feature | TASI v4.3 | US System | Status | Gap |
|---------|-----------|-----------|--------|-----|
| **Pre-market Screen** | 09:50 | 09:20 ET | ✅ Yes | Different timing |
| **Mid-session Rescreen** | 10:30, 12:00, 13:30 | 10:05, 11:35, 13:35 | ✅ Yes | Different timing |
| **Price Filter** | 5-500 SAR | Not set | ⚠️ Missing | US needs min/max price |
| **Volume Filter** | 500K avg | 500K avg | ✅ Same | None |
| **Gap Filter** | ≥1% | ≥1% | ✅ Same | None |
| **VWAP Calculation** | Yes | Yes | ✅ Same | None |
| **RSI Indicator** | Yes | No | ❌ Missing | Add RSI to US screener |
| **ATR Indicator** | Yes | No | ❌ Missing | Add ATR to US screener |
| **Score-Based Ranking** | 0-100 | 0-100 | ✅ Same | None |
| **Entry Zone** | min(prev_high×0.995, close×0.98) | Simple range | ⚠️ Different | US could use TASI formula |
| **Alpaca Integration** | No | Yes | ✅ US has | N/A |
| **Sharia Filter** | Derayah API | us_sharia_universe.py | ✅ Both have | N/A |
| **Output Files** | picks.json, pm_cache.json | us_picks.json | ✅ Equivalent | None |

### 2.2 Poller

| Feature | TASI v4.3 | US System | Status | Gap |
|---------|-----------|-----------|--------|-----|
| **Fast Poll** | 10s interval | 10s interval | ✅ Same | None |
| **Slow Poll** | 300s interval | 300s interval | ✅ Same | None |
| **Regime-Aware Params** | Yes | Yes | ✅ Same | None |
| **Hard Stop** | -7% (regime-adjustable) | -5% (regime-adjustable) | ✅ Similar | TASI wider in TRENDING |
| **Trailing Stop** | -3% from peak | -3% from peak | ✅ Same | None |
| **Time Stop** | 30 min (dynamic) | 30 min (fixed) | ⚠️ Partial | US missing dynamic time stops |
| **Profit Target** | Tiered (+2%, +5%, +10%) | Single target | ❌ Missing | US needs tiered targets |
| **Market Open Cooldown** | 10:00-10:15 | None | ❌ Missing | Add cooldown to US |
| **Entry Cutoff** | 13:30 | 14:30 | ✅ Similar | Different timing |
| **Hard Close** | 14:30-14:50 | 15:45 | ✅ Similar | Different timing |
| **VWAP Direction Filter** | Yes | No | ❌ Missing | Add to US |
| **Recovery Score** | 1-min candles | None | ❌ Missing | Add to US |
| **VWAP Exit Control** | Disabled in TRENDING | Always on | ⚠️ Partial | US should disable in TRENDING |
| **Cycle Management** | Tier 1/2/3 + upgrade/switch/recycle | Win/scratch only | ❌ Missing | US needs full cycle mgmt |
| **Position Upgrade** | Yes (score threshold) | No | ❌ Missing | Add to US |
| **Position Switch** | Yes (score threshold) | No | ❌ Missing | Add to US |
| **Capital Recycling** | Yes | No | ❌ Missing | Add to US |
| **Min Hold Time** | 15 min (regime-adjustable) | None | ❌ Missing | Add to US |

### 2.3 Bot

| Feature | TASI v4.3 | US System | Status | Gap |
|---------|-----------|-----------|--------|-----|
| **Runtime** | Continuous (systemd) | Continuous (systemd) | ✅ Same | None |
| **Command: /Login** | Yes (Phase 1 capture) | No | ❌ N/A | Alpaca uses API key |
| **Command: /SS** | Yes (full system status) | No | ❌ Missing | Add to US |
| **Command: /buy** | Yes | Yes (/us_buy) | ✅ Both have | N/A |
| **Command: /sell** | Yes | Yes (/us_sell) | ✅ Both have | N/A |
| **Command: /CloseAll** | Yes | No | ❌ Missing | Add to US |
| **Command: /DryRun** | Yes | No | ❌ Missing | Add to US |
| **Command: /History** | Yes | No | ❌ Missing | Add to US |
| **Command: /PnL** | Yes | No | ❌ Missing | Add to US |
| **Command: /HisCap** | Yes | No | ❌ Missing | Add to US |
| **Command: /Status** | Yes | Yes (/us_status) | ✅ Both have | N/A |
| **Command: /Regime** | Yes | No | ❌ Missing | Add to US |
| **Command: /Picks** | Yes | Yes (/us_picks) | ✅ Both have | N/A |
| **Command: /HELP** | Yes | No | ❌ Missing | Add to US |
| **Command: /Fund** | Yes | No | ❌ Missing | Add to US |
| **Command: /Withdraw** | Yes | No | ❌ Missing | Add to US |
| **WebSocket Keepalive** | Yes (ws_keepalive_v2) | No | ❌ N/A | Alpaca has own WS |
| **Session Integration** | Yes (derayah_session_manager) | No | ❌ N/A | Alpaca uses API key |
| **Position Tracking** | Yes (manual trades) | Yes | ✅ Both have | N/A |
| **Capital Updates** | Yes | Yes | ✅ Both have | N/A |

### 2.4 Bookkeeper

| Feature | TASI v4.3 | US System | Status | Gap |
|---------|-----------|-----------|--------|-----|
| **File** | bookkeeper.py (1,200 lines) | None | ❌ Missing | Create us_bookkeeper.py |
| **Capital Sync** | Every 5 min from browser | None | ❌ Missing | Alpaca provides balances |
| **Daily PnL CSV** | Yes (daily_pnl.csv) | No | ❌ Missing | Add to US |
| **FIFO Matching** | Yes (history_io.py) | No | ❌ Missing | Add to US |
| **Reconciliation** | Ghost position fix | No | ❌ Missing | Add to US |
| **End-of-Day PnL** | Yes | Partial (us_daily_report.py) | ⚠️ Partial | Enhance US report |
| **Capital Snapshots** | JSONL every 5 min | None | ❌ Missing | Add to US |

### 2.5 Session Manager

| Feature | TASI v4.3 | US System | Status | Gap |
|---------|-----------|-----------|--------|-----|
| **3-Phase Lifecycle** | Yes | No | ❌ N/A | Alpaca API key doesn't expire |
| **Token Capture** | Yes (CDP localStorage) | No | ❌ N/A | Alpaca uses API key |
| **SSO Refresh** | Yes (5-min cron) | No | ❌ N/A | Not needed for Alpaca |
| **Auto-Recovery** | Yes (email OTP) | No | ❌ N/A | Not needed for Alpaca |
| **Tab Deduplication** | Yes | No | ❌ N/A | No browser tabs |
| **CDP Navigation** | Yes | No | ❌ N/A | No CDP needed |
| **Token Storage** | derayah_tokens.json | .env file | ✅ Equivalent | Different mechanism |
| **Security** | chmod 600 creds | .env file | ✅ Equivalent | Different mechanism |

### 2.6 WebSocket Keepalive

| Feature | TASI v4.3 | US System | Status | Gap |
|---------|-----------|-----------|--------|-----|
| **WS Monitor** | ws_keepalive_v2.sh | No | ❌ N/A | Alpaca has built-in WS |
| **Stuck Detection** | File size check | No | ❌ N/A | Not applicable |
| **Auto-Restart** | Kill + restart ws_probe | No | ❌ N/A | Not applicable |
| **Price Feed** | ws_frames_raw.jsonl | No | ❌ Missing | Could add Alpaca WS |

### 2.7 Market Regime

| Feature | TASI v4.3 | US System | Status | Gap |
|---------|-----------|-----------|--------|-----|
| **File** | market_regime.py (200 lines) | us_market_regime.py (357 lines) | ✅ US has more | None |
| **Regimes** | TRENDING/NEUTRAL/DEFENSIVE | TRENDING/NEUTRAL/DEFENSIVE | ✅ Same | None |
| **Indicators** | Trend strength, volatility, breadth | SPY, VIX, sector breadth | ✅ Similar | US has sector ETFs |
| **Classification** | Every 30 min | Every 30 min | ✅ Same | None |
| **Output** | regime.json | us_regime.json | ✅ Equivalent | None |
| **Regime Confirmation** | 60 min stability | Not specified | ⚠️ Partial | Check US confirmation |

### 2.8 Post Market

| Feature | TASI v4.3 | US System | Status | Gap |
|---------|-----------|-----------|--------|-----|
| **File** | post_market.py (600 lines) | us_daily_report.py (207 lines) | ✅ US has | US simpler |
| **Daily PnL Analysis** | Yes | Partial | ⚠️ Partial | Enhance US |
| **Trade Analysis** | Win rate, avg gain/loss | Basic | ⚠️ Partial | Enhance US |
| **Pattern Learning** | Yes | No | ❌ Missing | Add to US |
| **HTML Report** | Yes | No | ❌ Missing | Add to US |
| **Telegram Report** | Yes | Yes | ✅ Same | None |
| **Trigger** | 15:35 | 16:15 ET | ✅ Similar | Different timing |

---

## Section 3: Strategy Logic

### 3.1 Entry Signals

| Feature | TASI v4.3 | US System | Status | Gap |
|---------|-----------|-----------|--------|-----|
| **Pre-market Screen** | Yes | Yes | ✅ Same | None |
| **Mid-session Rescreen** | Yes | Yes | ✅ Same | None |
| **Entry Evaluation** | Price + VWAP + regime | Price + VWAP + regime | ✅ Same | None |
| **Position Limits** | Max 3 | Max 3 | ✅ Same | None |
| **Time Cutoff** | 13:30 | 14:30 | ✅ Similar | Different |
| **VWAP Reclaim** | Yes | Yes | ✅ Same | None |
| **Breakout** | Yes | Yes | ✅ Same | None |
| **Gap-Up** | Yes | Yes | ✅ Same | None |
| **Cooldown** | 10:00-10:15 | None | ❌ Missing | Add to US |
| **VWAP Direction** | Required (NEUTRAL/DEF) | Not checked | ❌ Missing | Add to US |

### 3.2 Exit Signals

| Feature | TASI v4.3 | US System | Status | Gap |
|---------|-----------|-----------|--------|-----|
| **Hard Stop** | Yes | Yes | ✅ Same | None |
| **Trailing Stop** | Yes | Yes | ✅ Same | None |
| **Time Stop** | Dynamic | Fixed | ⚠️ Partial | US needs dynamic |
| **Hard Close** | Yes | Yes | ✅ Same | None |
| **Profit Target** | Tiered | Single | ❌ Missing | US needs tiered |
| **VWAP Exit** | Regime-aware | Always on | ⚠️ Partial | US should be regime-aware |
| **Recovery Check** | Yes | No | ❌ Missing | Add to US |
| **Min Hold** | Yes | No | ❌ Missing | Add to US |

### 3.3 Cycle Management

| Feature | TASI v4.3 | US System | Status | Gap |
|---------|-----------|-----------|--------|-----|
| **Tier System** | 3 tiers | No tiers | ❌ Missing | Add to US |
| **Upgrade** | Score threshold | No | ❌ Missing | Add to US |
| **Recycle** | Capital recycling | No | ❌ Missing | Add to US |
| **Switch** | Direct switch | No | ❌ Missing | Add to US |

---

## Section 4: Order Management System

### 4.1 Files

| File | TASI v4.3 | US System | Status | Gap |
|------|-----------|-----------|--------|-----|
| **order_helpers.py** | Yes (350 lines) | No | ❌ Missing | Add to US |
| **history_io.py** | Yes (500 lines) | No | ❌ Missing | Add to US |
| **bookkeeper.py** | Yes (1,200 lines) | No | ❌ Missing | Add to US |

### 4.2 Order Lifecycle

| Feature | TASI v4.3 | US System | Status | Gap |
|---------|-----------|-----------|--------|-----|
| **Status Constants** | INITIATED→PLACED→PARTIAL→FILLED | Not formalized | ❌ Missing | Add status codes |
| **Trigger Basis** | 13 triggers | Not tracked | ❌ Missing | Add trigger tracking |
| **PnL Calculation** | FIFO matching | Not implemented | ❌ Missing | Add FIFO |
| **Fee Calculation** | 0.0575% per side | Not tracked | ❌ Missing | Add fee tracking |
| **Deduplication** | Yes | No | ❌ Missing | Add dedup |
| **File Locking** | fcntl advisory locks | No | ❌ Missing | Add locks |
| **Async Safety** | Thread-safe wrappers | Partial | ⚠️ Partial | Enhance US |
| **Self-Test Isolation** | tempfile | Not isolated | ❌ Missing | Add isolation |

---

## Section 5: Session Management

| Feature | TASI v4.3 | US System | Status | Gap |
|---------|-----------|-----------|--------|-----|
| **3-Phase Lifecycle** | Yes | No | ❌ N/A | Alpaca doesn't need |
| **Manual Login** | /Login command | N/A | ❌ N/A | Alpaca uses API key |
| **Auto-Recovery** | Yes | No | ❌ N/A | Not needed |
| **Token Storage** | JSON file | .env file | ✅ Equivalent | Different mechanism |
| **Chrome Config** | derayah-live profile | N/A | ❌ N/A | No Chrome |
| **CDP Port** | 18801 | N/A | ❌ N/A | No CDP |
| **Tab Management** | Yes | No | ❌ N/A | No tabs |
| **SSO Refresh** | 5-min cron | N/A | ❌ N/A | Not needed |
| **Auto-Login** | Email OTP | N/A | ❌ N/A | Not needed |

**Conclusion:** Session management is NOT applicable to US system (Alpaca API-based).

---

## Section 6: Cron System

| Feature | TASI v4.3 | US System | Status | Gap |
|---------|-----------|-----------|--------|-----|
| **Total Crons** | 18 | 7 | ⚠️ Fewer | US missing some |
| **Bookkeeper Sync** | Every 5 min | None | ❌ Missing | Add to US |
| **Pre-market Screener** | 09:50 | 09:20 ET | ✅ Similar | Different timing |
| **Price Poller** | 10:00 | 09:30 ET | ✅ Similar | Different timing |
| **Mid-screens** | 10:30, 12:00, 13:30 | 10:05, 11:35, 13:35 | ✅ Similar | Different timing |
| **Post Market** | 15:35 | 16:15 ET | ✅ Similar | Different timing |
| **Ghost Position Fix** | 15:42 | None | ❌ Missing | Add to US |
| **Session Check** | 15:45 | N/A | ❌ N/A | Not needed |
| **Position Upgrade** | 15:48 | None | ❌ Missing | Add to US |
| **Watchdog** | Start 09:25, Stop 16:35 | None | ❌ Missing | Add to US |
| **Weekly Report** | Fri 20:00 | None | ❌ Missing | Add to US |
| **RAM Cleanup** | 04:00 daily | None | ⚠️ Missing | Consider adding |
| **Log Cleanup** | 04:00 daily | None | ⚠️ Missing | Consider adding |
| **Health Monitor** | Every 30 min | None | ❌ Missing | Add to US |
| **Derayah Keepalive** | Every 5 min | N/A | ❌ N/A | Not needed |

---

## Section 7: Generated Files

### 7.1 Trading Data (Real-time)

| File | TASI v4.3 | US System | Status | Gap |
|------|-----------|-----------|--------|-----|
| **positions.json** | Yes | Yes | ✅ Same | None |
| **capital.json** | Yes | Yes | ✅ Same | None |
| **orders.json** | Yes | No | ❌ Missing | Add to US |
| **trade_book.json** | Yes | No | ❌ Missing | Add to US |
| **regime.json** | Yes | Yes (us_regime.json) | ✅ Same | None |
| **ws_prices_*.jsonl** | Yes | No | ❌ N/A | Could add Alpaca WS |
| **order_history.csv** | Yes | No | ❌ Missing | Add to US |

### 7.2 Daily Files

| File | TASI v4.3 | US System | Status | Gap |
|------|-----------|-----------|--------|-----|
| **picks.json** | Yes | Yes (us_picks.json) | ✅ Same | None |
| **picks_*.json** | Yes | No | ❌ Missing | Add timestamps |
| **pm_cache.json** | Yes | No | ❌ Missing | Add cache |
| **learning.json** | Yes | No | ❌ Missing | Add learning |
| **daily_pnl.csv** | Yes | No | ❌ Missing | Add to US |
| **daily_pnl_*.md** | Yes | No | ❌ Missing | Add reports |
| **post_market_*.html** | Yes | No | ❌ Missing | Add HTML reports |

### 7.3 Log Files

| File | TASI v4.3 | US System | Status | Gap |
|------|-----------|-----------|--------|-----|
| **refresh_cron.log** | Yes | N/A | ❌ N/A | Not needed |
| **ws_frames_raw.log** | Yes | N/A | ❌ N/A | Not needed |
| **bot.log** | Yes | Yes (us_exec.log) | ✅ Same | None |
| **poller.log** | Yes | Yes (us_poller.log) | ✅ Same | None |
| **watchdog.log** | Yes | No | ❌ Missing | Add to US |

---

## Section 8: Bot Commands

### 8.1 Session Commands

| Command | TASI v4.3 | US System | Status | Gap |
|---------|-----------|-----------|--------|-----|
| **/Login** | Yes | No | ❌ N/A | Alpaca uses API key |
| **/SS** | Yes | No | ❌ Missing | Add to US |

### 8.2 Trading Commands

| Command | TASI v4.3 | US System | Status | Gap |
|---------|-----------|-----------|--------|-----|
| **/buy** | Yes | Yes (/us_buy) | ✅ Same | N/A |
| **/sell** | Yes | Yes (/us_sell) | ✅ Same | N/A |
| **/CloseAll** | Yes | No | ❌ Missing | Add to US |
| **/DryRun** | Yes | No | ❌ Missing | Add to US |

### 8.3 Reporting Commands

| Command | TASI v4.3 | US System | Status | Gap |
|---------|-----------|-----------|--------|-----|
| **/History** | Yes | No | ❌ Missing | Add to US |
| **/PnL** | Yes | No | ❌ Missing | Add to US |
| **/HisCap** | Yes | No | ❌ Missing | Add to US |
| **/HELP** | Yes | No | ❌ Missing | Add to US |

### 8.4 Status Commands

| Command | TASI v4.3 | US System | Status | Gap |
|---------|-----------|-----------|--------|-----|
| **/Status** | Yes | Yes (/us_status) | ✅ Same | N/A |
| **/Regime** | Yes | No | ❌ Missing | Add to US |
| **/Picks** | Yes | Yes (/us_picks) | ✅ Same | N/A |

### 8.5 Capital Commands (TASI only)

| Command | TASI v4.3 | US System | Status | Gap |
|---------|-----------|-----------|--------|-----|
| **/Fund** | Yes | No | ❌ Missing | Add to US |
| **/Withdraw** | Yes | No | ❌ Missing | Add to US |

---

## Summary: What US System is Missing

### Missing Components (Need to Create)
1. **bookkeeper.py** — Daily P&L CSV, FIFO matching
2. **history_io.py** — Order history, deduplication
3. **order_helpers.py** — Status codes, trigger basis

### Missing Features (Need to Add)
1. **Market Open Cooldown** — Block 09:30-09:45
2. **VWAP Direction Filter** — Require rising VWAP
3. **Recovery Score** — 1-min candle analysis
4. **Tiered Profit Targets** — +1%, +2%, +3%
5. **Dynamic Time Stops** — Based on entry time
6. **VWAP Exit Control** — Disable in TRENDING
7. **Cycle Management** — Tier 1/2/3 + upgrade/switch/recycle
8. **Min Hold Time** — Before VWAP breakdown sells
9. **File Locking** — fcntl advisory locks
10. **Order Deduplication** — Prevent duplicates
11. **Bot Commands** — /History, /PnL, /HisCap, /CloseAll, /HELP, /Regime, /Fund, /Withdraw

### Not Applicable (Alpaca vs Derayah differences)
1. **Session Manager** — Alpaca API key doesn't expire
2. **Chrome CDP** — No browser automation needed
3. **SSO Refresh** — Not needed for Alpaca
4. **Email OTP** — Not needed for Alpaca
5. **WebSocket Keepalive** — Alpaca has built-in WS
6. **Tab Management** — No browser tabs

---

*Cross-check completed by Mino 🪼 | 2026-06-15*
