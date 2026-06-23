#!/usr/bin/env python3
"""
US System Watchdog — Daily Activity Logger
Runs from 09:25 to 16:15 ET (25 min before first job, 15 min after last job)
Logs: all cron events, bot actions, system state, errors
Purpose: Post-mortem investigation — when something breaks, read this log
"""

import json
import os
import subprocess
import time
import signal
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
import pytz

ET = pytz.timezone("America/New_York")
BASE_DIR = Path("/home/mino/us-exec")
WATCHDOG_LOG = BASE_DIR / "logs" / "us_watchdog.log"
STATE_LOG = BASE_DIR / "logs" / "us_watchdog_state.jsonl"
PID_FILE = BASE_DIR / ".us_watchdog.pid"

# Telegram DM escalation
TELEGRAM_OWNER_ID  = 5529987063
ALERT_DM_COOLDOWN  = 900
ALERT_DM_ENABLED   = os.getenv("US_WATCHDOG_DM_ENABLED", "1") == "1"

def _read_us_bot_token() -> str:
    env_token = os.getenv("US_BOT_TOKEN", "").strip()
    if env_token:
        return env_token
    try:
        poller_py = (BASE_DIR / "us_poller.py").read_text()
        for line in poller_py.splitlines():
            if "BOT_TOKEN" in line and "os.getenv" in line:
                import re
                m = re.search(r'"([^"]+)"\s*\)', line)
                if m:
                    return m.group(1)
    except Exception:
        pass
    return ""

TELEGRAM_BOT_TOKEN = _read_us_bot_token()
_alert_last_dm: dict = {}

WATCHDOG_LOG.parent.mkdir(parents=True, exist_ok=True)

# ─── Config ──────────────────────────────────────────────────────────

FIRST_JOB_TIME = "09:25"  # 5 min before pre-market screener
LAST_JOB_TIME  = "16:15"  # 15 min after US daily report

CHECK_INTERVAL = 30

COMPONENTS = {
    "us-bot": "ps aux | grep 'python.*us_bot.py' | grep -v grep",
    "us-poller": "pgrep -f 'python.*us_poller.py'",
    "us-alpaca-ws": "systemctl --user is-active us-alpaca-ws",
    "alpaca-api": "curl -s --max-time 3 https://paper-api.alpaca.markets/v2/account | head -c 1",
}

KEY_LOGS = [
    "/home/mino/us-exec/logs/bot.log",
    "/home/mino/us-exec/logs/poller.log",
    "/home/mino/us-exec/logs/ws.log",
    "/home/mino/us-exec/logs/us_exec.log",
]

TRACKED_FILES = [
    ("picks", "/home/mino/us-exec/us_picks.json"),
    ("positions", "/home/mino/us-exec/us_positions.json"),
    ("capital", "/home/mino/us-exec/us_capital.json"),
    ("regime", "/home/mino/us-exec/us_regime.json"),
    ("trades", "/home/mino/us-exec/us_trades.json"),
    ("order_history", "/home/mino/us-exec/us_order_history.json"),
    ("config", "/home/mino/us-exec/config.json"),
    (".env", "/home/mino/us-exec/.env"),
    # Pick archives by date — check today's
]

_file_mtimes: dict = {}
running = True


def log(msg: str, level: str = "INFO"):
    ts = datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S %Z")
    line = f"[{ts}] [{level}] {msg}"
    print(line)
    with open(WATCHDOG_LOG, "a") as f:
        f.write(line + "\n")


def tg_send_dm(text: str) -> bool:
    if not ALERT_DM_ENABLED or not TELEGRAM_BOT_TOKEN:
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = urllib.parse.urlencode({
            "chat_id": TELEGRAM_OWNER_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        }).encode("utf-8")
        req = urllib.request.Request(url, data=payload, method="POST")
        with urllib.request.urlopen(req, timeout=8) as resp:
            return resp.status == 200
    except Exception as e:
        log(f"Telegram DM failed: {e}", level="WARNING")
        return False


def maybe_dm_alert(alerts: list) -> None:
    critical = [a for a in alerts if a.startswith("CRITICAL")]
    if not critical:
        return
    now_ts = time.time()
    fresh = []
    for a in critical:
        last = _alert_last_dm.get(a, 0)
        if now_ts - last >= ALERT_DM_COOLDOWN:
            fresh.append(a)
            _alert_last_dm[a] = now_ts
    if not fresh:
        return
    body = (
        f"🚨 US Watchdog — {len(fresh)} CRITICAL alert(s)\n\n"
        + "\n".join(f"• {a}" for a in fresh)
        + f"\n\nTime: {datetime.now(ET).strftime('%Y-%m-%d %H:%M:%S %Z')}"
        + f"\nFull log: {WATCHDOG_LOG}"
    )
    if tg_send_dm(body):
        log(f"DM sent to owner ({len(fresh)} alerts)", level="INFO")


def save_state(state: dict):
    with open(STATE_LOG, "a") as f:
        f.write(json.dumps(state) + "\n")


def check_component(name: str, cmd: str) -> tuple:
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            return "OK", result.stdout.strip()[:100]
        else:
            return "FAIL", result.stderr.strip()[:200] or result.stdout.strip()[:200]
    except subprocess.TimeoutExpired:
        return "TIMEOUT", "Command timed out after 5s"
    except Exception as e:
        return "ERROR", str(e)[:200]


def get_recent_log_lines(log_file: str, lines: int = 3) -> list:
    try:
        if not Path(log_file).exists():
            return ["FILE_NOT_FOUND"]
        result = subprocess.run(
            ["tail", "-n", str(lines), log_file],
            capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip().split("\n")
    except Exception as e:
        return [f"ERROR: {e}"]


def check_alpaca_api() -> dict:
    result = {"status": "UNKNOWN", "response_time_ms": 0}
    try:
        start = time.time()
        r = subprocess.run(
            ["curl", "-s", "--max-time", "5", "-o", "/dev/null", "-w", "%{http_code}",
             "https://paper-api.alpaca.markets/v2/account"],
            capture_output=True, text=True, timeout=6
        )
        elapsed = (time.time() - start) * 1000
        result["response_time_ms"] = round(elapsed, 1)
        code = r.stdout.strip()
        if code == "200":
            result["status"] = "OK"
        elif code == "401":
            result["status"] = "AUTH_FAIL"
        elif code == "403":
            result["status"] = "FORBIDDEN"
        else:
            result["status"] = f"HTTP_{code}"
    except Exception as e:
        result["status"] = f"ERROR: {e}"
    return result


def check_tracked_files() -> list:
    file_status = []
    for name, filepath in TRACKED_FILES:
        path = Path(filepath)
        if not path.exists():
            file_status.append({"name": name, "path": filepath, "status": "MISSING", "size": 0, "changed": False})
            continue
        stat = path.stat()
        size = stat.st_size
        mtime = stat.st_mtime
        prev_mtime = _file_mtimes.get(filepath)
        changed = prev_mtime is not None and mtime > prev_mtime
        _file_mtimes[filepath] = mtime
        file_status.append({
            "name": name, "path": filepath, "status": "OK",
            "size": size, "changed": changed
        })
    return file_status


def check_positions_health() -> dict:
    result = {"open_count": 0, "unrealized_pnl": 0, "alerts": []}
    positions_file = BASE_DIR / "us_positions.json"
    if not positions_file.exists():
        return result
    try:
        with open(positions_file) as f:
            data = json.load(f)
        positions = data.get("positions", {})
        for sym, pos in positions.items():
            if not pos.get("closed", True):
                result["open_count"] += 1
                entry = pos.get("entry_price", 0)
                current = pos.get("current_price", entry)
                qty = pos.get("quantity", 0)
                unrealized = (current - entry) * qty
                result["unrealized_pnl"] += unrealized
                
                entry_time = pos.get("entry_time", "")
                if entry_time:
                    try:
                        entry_dt = datetime.fromisoformat(entry_time)
                        if entry_dt.tzinfo is None:
                            entry_dt = entry_dt.replace(tzinfo=ET)
                        mins_held = (datetime.now(ET) - entry_dt).total_seconds() / 60
                        if mins_held > 240:  # > 4 hours
                            result["alerts"].append(f"{sym} held {mins_held/60:.1f}h")
                    except:
                        pass
    except:
        pass
    return result


def check_all_components():
    now = datetime.now(ET)
    date_str = now.strftime("%Y-%m-%d")
    
    state = {
        "timestamp": datetime.now(ET).isoformat(),
        "components": {},
        "log_snippets": {},
        "system": {},
        "alpaca_api": {},
        "tracked_files": [],
        "positions_health": {},
    }

    for name, cmd in COMPONENTS.items():
        status, detail = check_component(name, cmd)
        state["components"][name] = {"status": status, "detail": detail}

    for log_file in KEY_LOGS:
        log_name = Path(log_file).name
        state["log_snippets"][log_name] = get_recent_log_lines(log_file)

    # System metrics
    for cmd, key in [("free -m | grep Mem", "memory"), ("df -h / | tail -1", "disk"), ("uptime | awk -F'load average:' '{print $2}'", "load")]:
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=2)
            state["system"][key] = r.stdout.strip()
        except:
            state["system"][key] = "UNAVAILABLE"
    
    state["alpaca_api"] = check_alpaca_api()
    state["tracked_files"] = check_tracked_files()
    state["positions_health"] = check_positions_health()

    return state


def log_components(state: dict):
    log("--- Component Check ---")
    for name, data in state["components"].items():
        emoji = "✅" if data["status"] == "OK" else "❌"
        log(f"{emoji} {name}: {data['status']} — {data['detail'][:80]}")
    
    api = state.get("alpaca_api", {})
    emoji = "✅" if api.get("status") == "OK" else "❌"
    log(f"{emoji} Alpaca API: {api.get('status')} ({api.get('response_time_ms', 0)}ms)")
    
    files = state.get("tracked_files", [])
    if files:
        log("--- Tracked Files ---")
        changed = [f for f in files if f.get("changed")]
        missing = [f for f in files if f.get("status") == "MISSING"]
        if changed:
            log(f"📝 Changed: {', '.join(f['name'] for f in changed[:5])}")
        if missing:
            log(f"⚠️ Missing: {', '.join(f['name'] for f in missing[:5])}")
        if not changed and not missing:
            log("✅ All tracked files present")
    
    pos = state.get("positions_health", {})
    if pos.get("open_count", 0) > 0:
        log(f"📊 Open positions: {pos['open_count']} | Unrealized PnL: ${pos.get('unrealized_pnl', 0):.2f}")
        if pos.get("alerts"):
            for alert in pos["alerts"]:
                log(f"⏰ {alert}", level="WARNING")


def should_be_running(now: datetime = None) -> bool:
    if now is None:
        now = datetime.now(ET)
    def time_to_minutes(t_str):
        h, m = map(int, t_str.split(":"))
        return h * 60 + m
    current_mins = now.hour * 60 + now.minute
    first_mins = time_to_minutes(FIRST_JOB_TIME)
    last_mins = time_to_minutes(LAST_JOB_TIME)
    return first_mins <= current_mins <= last_mins


def detect_anomalies(state: dict) -> list:
    alerts = []
    
    # Critical components
    critical = ["us-bot", "us-alpaca-ws"]
    for name in critical:
        if state["components"].get(name, {}).get("status") != "OK":
            alerts.append(f"CRITICAL: {name} is {state['components'][name]['status']}")
    
    # Alpaca API
    alpaca = state.get("alpaca_api", {})
    if alpaca.get("status") != "OK":
        alerts.append(f"CRITICAL: Alpaca API {alpaca.get('status')}")
    
    # Memory
    mem_str = state["system"].get("memory", "")
    try:
        mem_parts = mem_str.split()
        if len(mem_parts) >= 7:
            available_pct = int(mem_parts[6]) / int(mem_parts[1]) * 100
            if available_pct < 10:
                alerts.append(f"WARNING: Memory critically low ({available_pct:.1f}% available)")
            elif available_pct < 20:
                alerts.append(f"WARNING: Memory low ({available_pct:.1f}% available)")
    except:
        pass
    
    # Disk
    disk_str = state["system"].get("disk", "")
    try:
        usage_pct = int(disk_str.split()[4].rstrip("%"))
        if usage_pct > 90:
            alerts.append(f"CRITICAL: Disk usage {usage_pct}%")
        elif usage_pct > 75:
            alerts.append(f"WARNING: Disk usage {usage_pct}%")
    except:
        pass
    
    # Missing critical files
    files = state.get("tracked_files", [])
    critical_files = ["picks", "positions", "capital", ".env"]
    for f in files:
        if f["name"] in critical_files and f["status"] == "MISSING":
            alerts.append(f"CRITICAL: {f['name']} file missing")
    
    # Stale positions
    pos = state.get("positions_health", {})
    if pos.get("alerts"):
        for alert in pos["alerts"]:
            alerts.append(f"WARNING: {alert}")
    
    return alerts


def run_watchdog_cycle():
    now = datetime.now(ET)
    time_str = now.strftime("%H:%M:%S")
    
    state = check_all_components()
    save_state(state)
    
    if int(time.time()) % 300 < CHECK_INTERVAL:
        log_components(state)
    
    alerts = detect_anomalies(state)
    if alerts:
        for alert in alerts:
            log(alert, level="ALERT")
        maybe_dm_alert(alerts)
    
    for log_file in KEY_LOGS:
        if Path(log_file).exists():
            try:
                result = subprocess.run(
                    f"tail -n 10 {log_file} | grep -i 'error\\|fail\\|critical\\|exception' | tail -n 3",
                    shell=True, capture_output=True, text=True, timeout=5
                )
                if result.stdout.strip():
                    log(f"LOG ALERT [{Path(log_file).name}]: {result.stdout.strip()[:200]}", level="ALERT")
            except:
                pass


def signal_handler(signum, frame):
    global running
    log(f"Received signal {signum}, shutting down gracefully...", level="INFO")
    running = False


def main():
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))
    
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    log("=" * 60)
    log("US System Watchdog Started")
    log(f"Active window: {FIRST_JOB_TIME} — {LAST_JOB_TIME} ET")
    log(f"Check interval: {CHECK_INTERVAL}s")
    log("=" * 60)
    
    try:
        while running:
            now = datetime.now(ET)
            
            if should_be_running(now):
                run_watchdog_cycle()
            else:
                if now.minute == 0:
                    log(f"Off-duty ({now.strftime('%H:%M')}), waiting for {FIRST_JOB_TIME}")
            
            time.sleep(CHECK_INTERVAL)
    
    except Exception as e:
        log(f"FATAL ERROR: {e}", level="CRITICAL")
        import traceback
        traceback.print_exc()
        raise
    finally:
        if PID_FILE.exists():
            PID_FILE.unlink()
        log("Watchdog stopped")


if __name__ == "__main__":
    main()
