# US Trading System — Comprehensive Improvement Plan
## Based on TASI v4.3 Blueprint Cross-Analysis | 2026-06-15
## Status: PROPOSED — Awaits A A approval

---

## Executive Summary

**Analysis Method:** Cross-checked all 42 TASI Python files against 13 US files component-by-component.

**Findings:**
- TASI has **42 Python files**, US has **13 files** (3.2× more)
- US is **missing 18 key components** from TASI
- US regime system is **MORE advanced** than TASI (357 vs 200 lines)
- Some TASI components are **NOT applicable** to Alpaca-based US system

---

## Part 1: What US Already Has (Don't Need to Build)

| Component | TASI | US | Status |
|-----------|------|-----|--------|
| **Basic Poller** | poller.py (2,200 lines) | us_poller.py (1,002 lines) | ✅ Working |
| **Screener** | screener.py (885 lines) | us_screener.py (591 lines) | ✅ Working |
| **Market Regime** | market_regime.py (200 lines) | us_market_regime.py (357 lines) | ✅ US is BETTER |
| **Mid-Screen** | midscreen_ws.py (~400 lines) | us_midscreen.py (487 lines) | ✅ Working |
| **Daily Report** | post_market.py (600 lines) | us_daily_report.py (207 lines) | ⚠️ Simpler but works |
| **Alpaca API** | derayah_api.py (~300 lines) | alpaca_api.py (419 lines) | ✅ Working |
| **Telegram Bot** | bot.py (2,179 lines) | us_bot.py (508 lines) | ⚠️ Basic but works |
| **Trade Logger** | In bot.py | us_trade_logger.py (292 lines) | ✅ Working |
| **Sharia Filter** | Derayah API | us_sharia_universe.py (218 lines) | ✅ Working |
| **Session Manager** | derayah_session_manager.py (1,500 lines) | .env file | ✅ Equivalent (API key) |

---

## Part 2: What is NOT Applicable (Alpaca Differences)

These TASI components don't apply to US because Alpaca works differently:

| Component | TASI | Why Not Applicable |
|-----------|------|-------------------|
| **ws_probe.py** | WebSocket price feed | Alpaca provides prices via API |
| **ws_logger.py** | WS frame logging | No WS to log |
| **ws_keepalive_v2.sh** | WS monitor | No WS to monitor |
| **derayah_session_manager.py** | 3-phase session lifecycle | Alpaca API key doesn't expire |
| **Chrome CDP automation** | Browser control | No browser needed |
| **SSO Refresh (5-min cron)** | Token refresh | Alpaca key is permanent |
| **Email OTP Login** | Auto-recovery | No 2FA for Alpaca API |
| **Tab Management** | Chrome tab dedup | No browser tabs |
| **Token Storage (JSON)** | derayah_tokens.json | .env file is equivalent |

---

## Part 3: What US is Missing (18 Gaps)

### Category A: Trading Strategy (7 gaps)

| # | Gap | TASI File | Impact | Applicability |
|---|-----|-----------|--------|---------------|
| 1 | **Market Open Cooldown** | poller.py | Enters noisy first 15 min | ✅ HIGH |
| 2 | **VWAP Direction Filter** | poller.py | Enters falling VWAP positions | ✅ HIGH |
| 3 | **Recovery Score (1-min)** | poller.py | Sells into temporary dips | ✅ HIGH |
| 4 | **Tiered Profit Targets** | poller.py | Only single target (+2%) | ✅ HIGH |
| 5 | **Dynamic Time Stops** | poller.py | Fixed 30 min for all | ✅ HIGH |
| 6 | **VWAP Exit Control** | poller.py | Exits trends too early | ✅ MEDIUM |
| 7 | **Cycle Management** | poller.py | No position recycling | ✅ MEDIUM |

### Category B: Infrastructure (5 gaps)

| # | Gap | TASI File | Impact | Applicability |
|---|-----|-----------|--------|---------------|
| 8 | **Bookkeeper** | bookkeeper.py (1,200 lines) | No PnL tracking at all | ✅ CRITICAL |
| 9 | **Order History (FIFO)** | history_io.py (500 lines) | No FIFO matching | ✅ HIGH |
| 10 | **File Locking** | order_helpers.py | JSON corruption risk | ✅ HIGH |
| 11 | **Order Deduplication** | history_io.py | Duplicate orders possible | ✅ MEDIUM |
| 12 | **Watchdog** | tasi_watchdog.py | No activity logging | ✅ LOW |

### Category C: Bot/UX (6 gaps)

| # | Gap | TASI File | Impact | Applicability |
|---|-----|-----------|--------|---------------|
| 13 | **/History command** | bot.py | No trade history view | ✅ MEDIUM |
| 14 | **/PnL command** | bot.py | No daily PnL view | ✅ MEDIUM |
| 15 | **/HisCap command** | bot.py | No capital history | ✅ MEDIUM |
| 16 | **/Fund command** | bot.py | No deposit tracking | ✅ LOW |
| 17 | **/Withdraw command** | bot.py | No withdrawal tracking | ✅ LOW |
| 18 | **/CloseAll command** | bot.py | No emergency close | ✅ HIGH |

---

## Part 4: Detailed Gap Descriptions

### Gap #1: Market Open Cooldown
**TASI:** Block entries 10:00-10:15 KSA (first 15 minutes)
**US:** No cooldown — enters immediately at 09:30 ET
**Impact:** High false entries during noisy open
**Fix:** Add time check in us_poller.py entry logic
**Effort:** 2 hours

### Gap #2: VWAP Direction Filter
**TASI:** Require rising VWAP before entry in NEUTRAL/DEFENSIVE
**US:** No direction check — enters any VWAP reclaim
**Impact:** Enters positions that immediately reverse
**Fix:** Add get_vwap_direction() function, check before entry
**Effort:** 4 hours

### Gap #3: Recovery Score (1-Minute)
**TASI:** Check 15×1-min candles before VWAP breakdown sell
**US:** Sells immediately on VWAP breakdown
**Impact:** Sells into temporary dips that recover
**Fix:** Add calculate_recovery_1min() using Alpaca bars
**Effort:** 1 day

### Gap #4: Tiered Profit Targets
**TASI:** Tier 1 (+2%), Tier 2 (+5%), Tier 3 (+10%)
**US:** Single target (+2%) — no tiers
**Impact:** Misses larger profit opportunities
**Fix:** Add tier system with limit orders via Alpaca
**Effort:** 1 day

### Gap #5: Dynamic Time Stops
**TASI:** Time stop based on entry time and regime
- TRENDING: No time stop
- NEUTRAL: 12:00/14:00/14:30 based on entry
- DEFENSIVE: 11:30/13:00/14:00 based on entry
**US:** Fixed 30 minutes for all
**Impact:** Exits too early in trends, too late in chop
**Fix:** Add get_time_stop() function with regime-aware logic
**Effort:** 1 day

### Gap #6: VWAP Exit Control
**TASI:** Disable VWAP exits in TRENDING regime (let trends run)
**US:** VWAP exits always enabled
**Impact:** Exits trends too early
**Fix:** Add regime check before VWAP breakdown sell
**Effort:** 4 hours

### Gap #7: Cycle Management
**TASI:** Tier 1/2/3 positions with upgrade/switch/recycle
**US:** Simple win/scratch tracking, no position cycling
**Impact:** Doesn't recycle capital to better opportunities
**Fix:** Add tier system and cycle logic
**Effort:** 2-3 days

### Gap #8: Bookkeeper (MOST CRITICAL)
**TASI:** bookkeeper.py (1,200 lines)
- Syncs capital every 5 minutes
- Calculates daily PnL with FIFO matching
- Fixes ghost positions
- Writes daily_pnl.csv
**US:** NOTHING — no PnL tracking at all
**Impact:** No historical tracking, no reconciliation, no reports
**Fix:** Create us_bookkeeper.py
**Effort:** 2-3 days

### Gap #9: Order History (FIFO)
**TASI:** history_io.py (500 lines)
- FIFO matching for PnL
- Order deduplication
- CSV read/write with locking
**US:** No FIFO, no dedup
**Impact:** Can't calculate accurate PnL
**Fix:** Create us_history_io.py
**Effort:** 1-2 days

### Gap #10: File Locking
**TASI:** fcntl advisory locks on positions.json, orders.json
**US:** No locking — concurrent writes risk corruption
**Impact:** JSON corruption when poller + bot write simultaneously
**Fix:** Add fcntl locks to save_positions(), save_capital()
**Effort:** 4 hours

### Gap #11: Order Deduplication
**TASI:** Check for existing order before inserting
**US:** No dedup check
**Impact:** Duplicate orders possible
**Fix:** Add dedup logic to auto_buy()
**Effort:** 2 hours

### Gap #12: Watchdog
**TASI:** tasi_watchdog.py — activity logging
**US:** No watchdog
**Impact:** No system health monitoring
**Fix:** Create us_watchdog.py
**Effort:** 4 hours

---

## Part 5: Implementation Phases

### Phase 1: Critical Infrastructure (Week 1)
**Goal:** Fix corruption risk and add PnL tracking

| # | Feature | Files | Effort | Risk |
|---|---------|-------|--------|------|
| 1 | File Locking | us_poller.py | 4 hours | LOW |
| 2 | Order Deduplication | us_poller.py | 2 hours | LOW |
| 3 | Create us_history_io.py | NEW | 1-2 days | MEDIUM |
| 4 | Create us_bookkeeper.py | NEW | 2-3 days | MEDIUM |

**Deliverables:**
- No more JSON corruption
- Order history with FIFO matching
- Daily PnL CSV generation

### Phase 2: Core Trading Strategy (Week 2-3)
**Goal:** Port TASI v4.5 trading improvements

| # | Feature | Files | Effort | Risk |
|---|---------|-------|--------|------|
| 5 | Market Open Cooldown | us_poller.py | 2 hours | LOW |
| 6 | VWAP Direction Filter | us_poller.py | 4 hours | MEDIUM |
| 7 | Recovery Score (1-min) | us_poller.py | 1 day | MEDIUM |
| 8 | Tiered Profit Targets | us_poller.py | 1 day | MEDIUM |
| 9 | Dynamic Time Stops | us_poller.py | 1 day | MEDIUM |
| 10 | VWAP Exit Control | us_poller.py | 4 hours | LOW |

**Deliverables:**
- Fewer false entries
- Better exit timing
- Higher profit capture

### Phase 3: Cycle Management (Week 3-4)
**Goal:** Add position cycling

| # | Feature | Files | Effort | Risk |
|---|---------|-------|--------|------|
| 11 | Cycle Management (Tier 1/2/3) | us_poller.py | 2-3 days | MEDIUM |
| 12 | Position Upgrade/Switch | us_poller.py | 1 day | MEDIUM |

**Deliverables:**
- Capital recycling to better picks
- Position optimization

### Phase 4: Bot Enhancement (Week 4)
**Goal:** Add missing commands

| # | Feature | Files | Effort | Risk |
|---|---------|-------|--------|------|
| 13 | /us_history | us_bot.py | 4 hours | LOW |
| 14 | /us_pnl | us_bot.py | 4 hours | LOW |
| 15 | /us_hiscap | us_bot.py | 4 hours | LOW |
| 16 | /us_closeall | us_bot.py | 2 hours | LOW |
| 17 | /us_fund | us_bot.py | 4 hours | LOW |
| 18 | /us_withdraw | us_bot.py | 4 hours | LOW |

**Deliverables:**
- Complete Telegram command set
- Historical tracking access

### Phase 5: Monitoring (Week 4-5)
**Goal:** Add system health

| # | Feature | Files | Effort | Risk |
|---|---------|-------|--------|------|
| 19 | Create us_watchdog.py | NEW | 4 hours | LOW |
| 20 | Health check cron | cron | 2 hours | LOW |

**Deliverables:**
- System activity logging
- Health monitoring

---

## Part 6: Total Effort Estimate

| Phase | Duration | Effort | Priority |
|-------|----------|--------|----------|
| 1: Infrastructure | Week 1 | 4-6 days | CRITICAL |
| 2: Trading Strategy | Week 2-3 | 5-6 days | HIGH |
| 3: Cycle Management | Week 3-4 | 3-4 days | MEDIUM |
| 4: Bot Enhancement | Week 4 | 2-3 days | LOW |
| 5: Monitoring | Week 4-5 | 1 day | LOW |
| **Total** | **5 weeks** | **15-20 days** | **All** |

---

## Part 7: Recommended Order

**A A — I recommend this order:**

1. **Phase 1 first** (infrastructure) — Fix corruption risk, add PnL
2. **Phase 2 next** (trading strategy) — Core improvements
3. **Phase 3 after** (cycle management) — Capital optimization
4. **Phase 4 last** (bot) — Convenience commands

**Or if you want quick wins first:**
1. Phase 2, item 1 (cooldown) — 2 hours
2. Phase 2, item 6 (VWAP exit control) — 4 hours
3. Phase 1, item 1 (file locking) — 4 hours

---

## Part 8: Files to Create

| File | Lines | Purpose |
|------|-------|---------|
| us_bookkeeper.py | ~400 | Daily PnL, FIFO matching, reconciliation |
| us_history_io.py | ~200 | Order history, CSV read/write, deduplication |
| us_order_helpers.py | ~100 | Status constants, trigger basis |
| us_watchdog.py | ~150 | Activity logging, health checks |

---

## Part 9: Files to Modify

| File | Lines Changed | Purpose |
|------|--------------|---------|
| us_poller.py | ~200 | Add cooldown, filters, recovery, tiers, time stops |
| us_bot.py | ~150 | Add new commands |
| us_market_regime.py | ~30 | Add time stop params |

---

## A A — Say "Do it" and I'll start implementing.

**Or specify:**
- **"Phase 1"** — Infrastructure (bookkeeper + locking)
- **"Phase 2"** — Trading strategy (cooldown + filters + recovery)
- **"Phase 1+2"** — Infrastructure + trading strategy
- **"All"** — Everything (5 weeks)
- **"Custom"** — Tell me which items (1-20)

🪼 Mino
