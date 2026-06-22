# US Trading System — Critical Bug Fix
**Date:** 2026-06-19 00:33 KSA  
**File:** `/home/mino/us-exec/us_poller.py`  
**Severity:** CRITICAL — Position tracking broken, orders out of sync with Alpaca

---

## 1. Bug Summary

Both `auto_buy()` and `auto_sell()` functions checked for `result.get("success")` but `alpaca_api.submit_order()` returns `"status"`, not `"success"`. This caused:
- Orders submitted successfully to Alpaca but bot reported them as failed
- Positions NOT saved to internal tracking (`us_positions.json`)
- Capital NOT updated
- Bot and Alpaca completely out of sync

## 2. Affected Functions

| Function | Line | Bug | Impact |
|----------|------|-----|--------|
| `auto_buy()` | ~359 | Checked `result.get("success")` | Buy orders reported as failed, positions not saved |
| `auto_sell()` | ~415 | Checked `result.get("success")` | Sell orders reported as failed, positions not closed |

## 3. Root Cause

`submit_order()` in `alpaca_api.py` returns:
```python
result = {
    "id": order.id,
    "symbol": order.symbol,
    "side": order.side,
    "qty": order.qty,
    "type": order.type,
    "status": order.status,      # ← "status" not "success"
    "created_at": order.created_at,
}
```

But `auto_buy` and `auto_sell` checked:
```python
if result.get("success"):      # ← Always None!
```

## 4. Evidence — June 18, 2026 Session

### Buy Orders (16:30 KSA = 09:30 ET — Market Open)
| Symbol | Qty | Status | Bot Report | Reality |
|--------|-----|--------|------------|---------|
| **VZ** | 654 | `pending_new` | "Buy failed" | ✅ **Filled by Alpaca** |
| **BMY** | 543 | `pending_new` | "Buy failed" | ✅ **Filled by Alpaca** |
| **EQT** | 590 | `pending_new` | "Buy failed" | ✅ **Filled by Alpaca** |

Positions existed in Alpaca but bot had no record of them.

### Sell Orders (22:45 KSA = 15:45 ET — Hard Close)
| Symbol | Qty | Status | Bot Report | Reality |
|--------|-----|--------|------------|---------|
| **BMY** | 543 | `pending_new` | "Sell failed" (implied) | ✅ **Sold by Alpaca** |
| **EQT** | 590 | `pending_new` | "Sell failed" (implied) | ✅ **Sold by Alpaca** |
| **VZ** | 654 | `pending_new` | "Sell failed" (implied) | ✅ **Sold by Alpaca** |

## 5. Impact Analysis

### Before Fix (June 18, 2026)
- **3 buy orders** executed by Alpaca but invisible to bot
- **3 sell orders** (hard close) executed by Alpaca but bot unaware
- Bot kept generating "Buy detected" signals for already-held positions
- Position file `us_positions.json` empty or stale
- Capital tracking completely broken
- No stop-loss, trail-stop, or VWAP exit monitoring on real positions

### After Fix
- Orders correctly recognized as successful when status is valid
- Positions saved/closed properly in `us_positions.json`
- Capital updated accurately
- Bot and Alpaca in sync

## 6. Fix Applied

Changed both functions from:
```python
if result.get("success"):
```

To:
```python
if result.get("status") in ("pending_new", "accepted", "filled", "partially_filled"):
```

This accepts all valid order states as "success" since Alpaca paper trading may return `pending_new` even for market orders during active hours.

## 7. Additional Issues Discovered (Not Fixed)

| Issue | Location | Severity | Notes |
|-------|----------|----------|-------|
| tg_send 401 Unauthorized | `us_bot.py` | Medium | Old bot token? Telegram notifications failing |
| VWAP "Series is ambiguous" | `us_poller.py:285` | Medium | yfinance returning Series in some code paths |
| Position "invalid entry price" | `us_poller.py` | Medium | Related to bot not knowing about Alpaca positions |
| EQT/CSX/EXC "possibly delisted" | yfinance data | Low | Data feed issues for some symbols |

## 8. Files Modified

- `/home/mino/us-exec/us_poller.py` (lines ~359, ~415)

## 9. Verification

- ✅ Syntax check passed (`python3 -m py_compile`)
- ✅ US bot restarted (PID 17414)
- ✅ US poller will auto-start at next market open (09:30 ET = 16:30 KSA)
- ⚠️ Live verification pending next trading session (Friday, June 19, 2026)

## 10. Action Items

1. **Monitor tomorrow's session** (Fri Jun 19, 16:30 KSA) — verify buys/sells recognized correctly
2. **Fix tg_send 401 error** — update Telegram bot token if needed
3. **Investigate VWAP Series error** — may need similar scalar extraction as TASI fix
4. **Sync positions** — check if `us_positions.json` matches Alpaca after fix
5. **Add order status polling** — consider checking order status after submission to confirm fill

---
*Fix applied: 2026-06-19 00:33 KSA*  
*System: Ocean (US paper trading via Alpaca)*
