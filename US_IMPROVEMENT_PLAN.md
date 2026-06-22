# US Trading System — Improvement Plan
## Based on TASI Blueprint Analysis | 2026-06-15
## Status: PROPOSED — Awaits A A approval

---

## Current US System Analysis

### What US System HAS (Working)
| Component | File | Lines | Status |
|-----------|------|-------|--------|
| **Poller** | us_poller.py | 1,002 | ✅ Fast/slow poll, regime params, exits, entries |
| **Screener** | us_screener.py | 591 | ✅ Pre-market screen, Alpaca, Sharia filter |
| **Bot** | us_bot.py | 508 | ✅ Basic Telegram commands, manual buy/sell |
| **Market Regime** | us_market_regime.py | 357 | ✅ TRENDING/NEUTRAL/DEFENSIVE with sector breadth |
| **Alpaca API** | alpaca_api.py | 419 | ✅ Paper trading, orders, quotes |
| **Trade Logger** | us_trade_logger.py | 292 | ✅ Basic trade logging, close tracking |
| **Mid-Screen** | us_midscreen.py | 487 | ✅ Mid-session screening |
| **Daily Report** | us_daily_report.py | 207 | ✅ End-of-day reporting |
| **Sharia Universe** | us_sharia_universe.py | 218 | ✅ Sharia-compliant stock list |

### What US System LACKS (Gaps vs TASI)

#### A. Trading Strategy Gaps
| # | Gap | TASI Has | US Impact |
|---|-----|----------|-----------|
| 1 | **No Market Open Cooldown** | Block 10:00-10:15 | US enters noisy first 15 min |
| 2 | **No VWAP Direction Filter** | Require rising VWAP | US enters falling VWAP positions |
| 3 | **No Recovery Score** | 1-min candle analysis | US sells into temporary dips |
| 4 | **No Tiered Profit Targets** | +2%/+5%/+10% | US only has single target |
| 5 | **Fixed Time Stops** | Dynamic by entry time | US uses fixed 30 min |
| 6 | **No Position Upgrade/Switch** | Cycle management | US no position recycling |
| 7 | **No VWAP Exit Control** | Disable in TRENDING | US exits trends too early |

#### B. Infrastructure Gaps
| # | Gap | TASI Has | US Impact |
|---|-----|----------|-----------|
| 8 | **No Bookkeeper** | Daily P&L CSV, FIFO | US no historical tracking |
| 9 | **No File Locking** | fcntl advisory locks | US JSON corruption risk |
| 10 | **No Deduplication** | Order dedup | US duplicate orders |
| 11 | **Basic Capital Tracking** | 3-bucket system | US simple JSON |
| 12 | **No Session Manager** | 3-phase lifecycle | US just API key |

#### C. Bot/UX Gaps
| # | Gap | TASI Has | US Impact |
|---|-----|----------|-----------|
| 13 | **Basic Bot Commands** | 12+ commands | US only 6 |
| 14 | **No /Fund /Withdraw** | Capital movement tracking | US can't track deposits |
| 15 | **No /History /PnL** | Daily/weekly reports | US no trade history |

---

## Applicability Analysis: What from TASI Fits US?

### ✅ APPLICABLE (US market compatible)

| TASI Feature | US Applicability | Reason |
|-------------|-----------------|--------|
| Market Open Cooldown | ✅ HIGH | US also has noisy opens |
| VWAP Direction Filter | ✅ HIGH | Same technical analysis |
| Recovery Score (1-min) | ✅ HIGH | Same price action behavior |
| Profit Targets | ✅ HIGH | Alpaca supports limit orders |
| Time Stops (dynamic) | ✅ HIGH | Same logic, different times |
| File Locking | ✅ HIGH | Same concurrency issues |
| Deduplication | ✅ HIGH | Same order duplication risk |
| Bot Commands (/Fund etc) | ✅ HIGH | Alpaca has deposit/withdrawal |
| Daily P&L CSV | ✅ HIGH | Same reporting need |

### ⚠️ PARTIALLY APPLICABLE (Needs adaptation)

| TASI Feature | US Adaptation | Reason |
|-------------|--------------|--------|
| Position Upgrade/Switch | ⚠️ MEDIUM | US has cycle limits (3 positions) |
| VWAP Exit Control | ⚠️ MEDIUM | US has different VWAP behavior |
| Session Manager | ⚠️ LOW | Alpaca uses API key, not browser |
| Sector Breadth | ⚠️ MEDIUM | Already in us_market_regime.py |

### ❌ NOT APPLICABLE (US-specific differences)

| TASI Feature | US Status | Reason |
|-------------|-----------|--------|
| Chrome CDP automation | ❌ N/A | Alpaca is API-based, no browser |
| SSO Refresh | ❌ N/A | Alpaca API key doesn't expire |
| Email OTP Login | ❌ N/A | No 2FA for Alpaca API |
| WebSocket Keepalive | ⚠️ PARTIAL | Alpaca has its own WebSocket |
| Derayah-specific logic | ❌ N/A | US uses Alpaca |

---

## Recommended Implementation Plan

### Phase 1: Core Trading Fixes (Week 1-2)
**Priority: HIGH | Risk: LOW-MEDIUM**

#### 1.1 Market Open Cooldown
- Block entries 09:30-09:45 ET
- Simple time check in us_poller.py
- **Effort:** 2 hours | **Testing:** 1 day

#### 1.2 VWAP Direction Filter
- Require rising VWAP before entry (NEUTRAL/DEF)
- Add get_vwap_direction() function
- **Effort:** 4 hours | **Testing:** 2 days

#### 1.3 1-Minute Recovery Score
- Check recovery before VWAP breakdown sell
- Use Alpaca bars or yfinance 1m data
- **Effort:** 1 day | **Testing:** 2 days

### Phase 2: Exit Strategy Enhancement (Week 2-3)
**Priority: HIGH | Risk: MEDIUM**

#### 2.1 Tiered Profit Targets
- Add +1%, +2%, +3% tier system
- Use limit orders via Alpaca
- **Effort:** 1 day | **Testing:** 2 days

#### 2.2 Dynamic Time Stops
- Time stops based on entry time and regime
- TRENDING: no time stop, DEF: early exit
- **Effort:** 1 day | **Testing:** 2 days

#### 2.3 VWAP Exit Control
- Disable VWAP exits in TRENDING regime
- Let trends run
- **Effort:** 4 hours | **Testing:** 1 day

### Phase 3: Infrastructure (Week 3-4)
**Priority: MEDIUM | Risk: LOW**

#### 3.1 File Locking
- Add fcntl advisory locks to positions.json, capital.json
- Prevent concurrent corruption
- **Effort:** 1 day | **Testing:** 1 day

#### 3.2 Order Deduplication
- Check for duplicate orders before submitting
- Key: symbol + side + qty + time
- **Effort:** 4 hours | **Testing:** 1 day

#### 3.3 Daily P&L CSV
- Create us_bookkeeper.py
- FIFO matching, daily summary
- **Effort:** 2 days | **Testing:** 2 days

### Phase 4: Bot Enhancement (Week 4)
**Priority: LOW | Risk: LOW**

#### 4.1 New Commands
- /us_history [days]
- /us_pnl
- /us_fund <amount>
- /us_withdraw <amount>
- /us_hiscap
- **Effort:** 2 days | **Testing:** 1 day

---

## Implementation Order Recommendation

| Order | Phase | Feature | Risk | Duration | Depends On |
|-------|-------|---------|------|----------|------------|
| 1 | 1.1 | Market Open Cooldown | LOW | 2 hours | None |
| 2 | 1.2 | VWAP Direction Filter | MEDIUM | 4 hours | None |
| 3 | 1.3 | Recovery Score | MEDIUM | 1 day | None |
| 4 | 2.1 | Tiered Profit Targets | MEDIUM | 1 day | None |
| 5 | 2.2 | Dynamic Time Stops | MEDIUM | 1 day | None |
| 6 | 2.3 | VWAP Exit Control | LOW | 4 hours | None |
| 7 | 3.1 | File Locking | LOW | 1 day | None |
| 8 | 3.2 | Order Deduplication | LOW | 4 hours | None |
| 9 | 3.3 | Daily P&L CSV | LOW | 2 days | None |
| 10 | 4.1 | Bot Commands | LOW | 2 days | None |

**Recommended:** Implement in order 1→10 (low-risk first)

---

## Expected Impact

| Metric | Before | After All Phases |
|--------|--------|-----------------|
| False entries at open | High | Reduced by cooldown |
| Entries on falling VWAP | Common | Filtered out |
| Sells into temporary dips | Common | Recovery check prevents |
| Profit capture | Single target | Tiered targets |
| Time management | Fixed 30 min | Dynamic per regime |
| File corruption risk | Present | Eliminated with locks |
| Duplicate orders | Possible | Prevented |
| Daily reporting | None | CSV + bot commands |

---

## Files to Create/Modify

| File | Action | Purpose |
|------|--------|---------|
| us_poller.py | MODIFY ~200 lines | Add cooldown, filters, recovery, tiers |
| us_market_regime.py | MODIFY ~30 lines | Add time stop params |
| us_bot.py | MODIFY ~150 lines | New commands |
| us_bookkeeper.py | CREATE ~400 lines | Daily P&L, FIFO matching |
| us_history_io.py | CREATE ~200 lines | CSV read/write helpers |

---

## A A — Say "Do it" and I'll start with Phase 1.1 (Market Open Cooldown).

**Or specify:**
- "Phase 1 only" — Core trading fixes (cooldown + filters + recovery)
- "Phases 1-2" — Full trading strategy upgrade
- "Phases 1-3" — Trading + infrastructure
- "All phases" — Complete system upgrade
- "Custom" — Tell me which features matter most

🪼 Mino
