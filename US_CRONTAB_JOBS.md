# US Cron Jobs Reference

Last updated: 2026-07-04

## Fix Applied (2026-07-05)

**Problem:** US screener, midscreen, evaluator, and daily report were NOT sending Telegram notifications because `US_BOT_TOKEN` was not loaded in the cron environment.

**Root Cause:** The crontab entries didn't source the `.env` file before running the scripts. The scripts use `os.environ.get("US_BOT_TOKEN")` which returns empty string when the variable isn't exported in cron's minimal environment.

**Fix:** Updated all US cron entries to source `. /home/mino/us-exec/.env` before running the Python scripts:

```bash
# Before (broken — no env vars loaded):
20 16 * * 1-5 cd /home/mino/us-exec && PYTHONPATH=/home/mino/us-exec /usr/bin/python3 us_screener.py

# After (fixed — env vars loaded):
20 16 * * 1-5 cd /home/mino/us-exec && . /home/mino/us-exec/.env && PYTHONPATH=/home/mino/us-exec /usr/bin/python3 us_screener.py
```

**Affected Jobs:**
- US Pre-market Screener
- US Evaluator  
- US Mid-screen 1 & 2
- US Re-screen
- US Daily P&L Report

**Verification:** `.env` contains `US_BOT_TOKEN=8617061863:AAEPDTEn1UAwsrlsdo4q8hjjjEcq4Fc0Lws` and `US_CHAT_ID=5529987063`.

---

## System Crontab (All US Jobs)

| # | Schedule (KSA) | Schedule (ET) | Job | Script | Log File |
|---|---------------|---------------|-----|--------|----------|
| 1 | `*/5 16-23 * * 1-5` | Every 5 min | Bookkeeper sync | `us_bookkeeper.quick_refresh()` | `bookkeeper.log` |
| 2 | `30 9 * * 1-5` | 09:30 | Start trading poller | `systemctl start us-trading-poller` | `cron.log` |
| 3 | `35 9 * * 1-5` | 09:35 | Start Alpaca WS | `systemctl start us-alpaca-ws` | `cron.log` |
| 4 | `20 16 * * 1-5` | 09:20 | **Screener** | `us_screener.py` | `screener.log` |
| 5 | `0 17 * * 1-5` | 10:00 | **Midscreen 1** | `us_midscreen.py` | `midscreen.log` |
| 6 | `40 17-20 * * 1-5` | 10:40-13:40 | **Evaluator** | `us_evaluator.py` | `evaluator.log` |
| 7 | `30 18 * * 1-5` | 11:30 | **Midscreen 2** | `us_midscreen.py` | `midscreen.log` |
| 8 | `30 20 * * 1-5` | 13:30 | **Re-screen** | `us_midscreen.py` | `midscreen.log` |
| 9 | `0 17 * * 1-5` | 16:00 | Stop trading poller | `systemctl stop us-trading-poller` | `cron.log` |
| 10 | `5 17 * * 1-5` | 17:05 | Stop Alpaca WS | `systemctl stop us-alpaca-ws` | `cron.log` |
| 11 | `10 23 * * 1-5` | 16:10 | **Daily P&L report** | `us_daily_report.py` | `report.log` |
| 12 | `0 7 * * 1-5` | 00:00 | Reset positions | `rm us_positions.json` | N/A |

## OpenClaw Cron Jobs

| # | Schedule (KSA) | Schedule (ET) | Job | Status |
|---|---------------|---------------|-----|--------|
| — | — | — | No US-specific OpenClaw jobs | All trading jobs are in system crontab |

## Market Hours
- **US Market:** Mon–Fri, 09:30–16:00 ET
- **KSA Conversion:** 16:30–23:00 (Mon–Fri)

## Services
- `us-trading-poller.service` — Price polling
- `us-alpaca-ws.service` — Alpaca WebSocket (running 24/7, started/stopped by cron)

## Config Files
- `/home/mino/us-exec/.env` — API keys, tokens
- `/home/mino/us-exec/us_positions.json` — Live positions (reset daily)
- `/home/mino/us-exec/us_capital.json` — Capital state

## Key Differences from TASI
- US runs **Mon–Fri** (TASI runs Sun–Thu)
- US uses **systemd services** for poller/WS (TASI also uses systemd)
- US **screener is pre-market** (TASI screener is at market open)
- US has **no aftermarket screener scheduled** (exists but not in cron)
- US **evaluator runs 4x/day** (TASI runs every 30 min 10:00–14:00)

## Backups
- `crontab_live_backup_20260704_0550.txt` — Created when jobs were added
