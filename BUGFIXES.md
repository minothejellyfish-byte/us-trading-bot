# Bug Fixes — 2026-06-04 02:05 GMT+3

## Fixed Issues

### 1. us_midscreen.py — time module conflict
**Problem:** `import time` conflicted with `from datetime import time`
**Fix:** Renamed to `import time as time_mod` and used `dt_time` for datetime.time

### 2. us_bot.py — Float format errors
**Problem:** Alpaca returns some values as strings, causing `:.2f` format errors
**Fix:** Added type conversion: `float(val) if isinstance(val, str) else val`

### 3. alpaca_api.py — Same float format issue
**Problem:** Same string/float issue in test block
**Fix:** Added type conversion

### 4. .env — Wrong bot token
**Problem:** US_BOT_TOKEN had invalid token
**Fix:** Updated to use same token as TASI bot

### 5. us_telegram_handler.py — .env path
**Problem:** Handler looked for .env in shared/ subdirectory
**Fix:** Now checks both shared/ and parent directory

### 6. Dependency conflicts
**Problem:** yfinance 1.3 requires websockets>=13, alpaca-trade-api requires websockets<11
**Fix:** Downgraded yfinance to 1.2.2, websockets to 10.4

## Current Status

| Component | Status |
|-----------|--------|
| US Bot | ✅ Running (PID 19965 since Jun 3) |
| Alpaca API | ✅ Connected |
| Telegram | ✅ Sending messages |
| Pre-market screener | ✅ Ready (first run: today 16:20 GMT+3) |
| Mid-screen | ✅ Fixed and ready |
| Poller | ✅ Ready (starts today 16:30 GMT+3) |
