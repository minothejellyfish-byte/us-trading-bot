# US Pre-Market Screener — Alpaca Credentials Issue

## Problem
The US pre-market screener has been returning **0 picks for all stocks** since (at least) August 31, 2026.

## Root Cause
The Alpaca API credentials in `.env` are still **placeholder values**:

```
ALPACA_API_KEY=YOUR_A…HERE
ALPACA_SECRET_KEY=YOUR_A…HERE
```

The `…` (ellipsis, U+2026) character in the placeholder triggers a `latin-1` encoding error when sent as an HTTP header. Every Alpaca API request fails, so every stock gets rejected with:

```
Alpaca error: 'latin-1' codec can't encode character '\u2026' in position 6
```

## Impact
- 194 stocks screened → 194 failures → 0 picks
- `us_picks.json` is empty every day
- No Telegram alert is sent (script exits cleanly with 0 picks, not an error)

## Fix Required
Replace the placeholder values in `/home/mino/us-exec/.env` with real Alpaca credentials:

```bash
ALPACA_API_KEY=your_real_key_here
ALPACA_SECRET_KEY=your_real_secret_here
```

Then restart any running services.

## Where to Get Credentials
Log into https://alpaca.markets/ → Paper Trading → API Keys → Generate new key

## Files Affected
- `us_screener.py` (pre-market screener)
- `us_aftermarket_screener.py` (after-market screener, also uses Alpaca)

## Date Discovered
2026-09-01
