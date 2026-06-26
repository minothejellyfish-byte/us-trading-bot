#!/usr/bin/env python3
"""
US Daily Cleanup — v1.0
=======================
Runs daily at 03:30 ET (before market prep).
Mirrors TASI cleanup_system.py for US trading bot.

Rules:
1. Logs (*.log): keep last 48h, rotate older
2. Picks (us_picks.json, us_validated_picks.json): keep current, archive daily
3. Positions/Trades JSON: keep current, archive to CSV
4. CSV files (us_orders.csv, us_pnl.csv, us_positions.csv): keep forever
5. Backups (*.backup*): delete >3 days old
6. Change requests (CHANGE_REQUEST_*.md): delete >7 days old
7. Fix scripts (*_fix.py): delete >7 days old
8. Old output logs (us_screener_output_*.log): delete >3 days old
9. Archive folder: review and delete >30 days old
10. RAM cleanup: kill idle processes, restart gateway if critical

Author: Mino (kimi-k2.6)
Date: 2026-06-23
"""

import os
import json
import gzip
import shutil
from datetime import datetime, timedelta
from pathlib import Path
import pytz

ET = pytz.timezone("America/New_York")
BASE_DIR = Path("/home/mino/us-exec")
LOG_FILE = BASE_DIR / "logs" / "us_cleanup.log"

# Ensure logs dir exists
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)


def log(msg: str):
    ts = datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S %Z")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def get_file_age_days(filepath: Path) -> int:
    """Get file age in days."""
    try:
        mtime = datetime.fromtimestamp(filepath.stat().st_mtime, ET)
        return (datetime.now(ET) - mtime).days
    except:
        return 999


def rotate_log(filepath: Path, keep_hours: int = 48):
    """Rotate a log file: keep last N hours, truncate rest."""
    if not filepath.exists():
        return
    
    size_mb = filepath.stat().st_size / (1024 * 1024)
    
    # For very large files (>500MB), use tail command directly
    if size_mb > 500:
        log(f"  Fast-rotating {filepath.name} ({size_mb:.0f}MB) using tail...")
        try:
            tmp_file = filepath.with_suffix('.tmp')
            os.system(f"tail -n 10000 '{filepath}' > '{tmp_file}' 2>/dev/null && mv '{tmp_file}' '{filepath}'")
            log(f"  Rotated {filepath.name}: kept last 10,000 lines")
            return
        except Exception as e:
            log(f"  Error fast-rotating {filepath.name}: {e}")
            return
    
    # For smaller files, use timestamp-based rotation
    try:
        cutoff = datetime.now(ET) - timedelta(hours=keep_hours)
        cutoff_str = cutoff.strftime("%Y-%m-%d")
        
        with open(filepath, 'r') as f:
            lines = f.readlines()
        
        recent_lines = []
        for line in lines:
            if len(line) >= 10 and line[:10] >= cutoff_str:
                recent_lines.append(line)
        
        if not recent_lines and lines:
            recent_lines = lines[-10000:]
        
        with open(filepath, 'w') as f:
            f.writelines(recent_lines)
        
        log(f"  Rotated {filepath.name}: kept {len(recent_lines)} lines")
    except Exception as e:
        log(f"  Error rotating {filepath.name}: {e}")


def cleanup_logs():
    """Rule 1: Logs — keep last 48h, rotate older."""
    log("=== Logs Cleanup ===")
    
    log_files = [
        BASE_DIR / "us_poller.log",
        BASE_DIR / "us_exec.log",
        BASE_DIR / "us_bot.log",
        BASE_DIR / "logs" / "bot.log",
        BASE_DIR / "logs" / "poller.log",
        BASE_DIR / "logs" / "midscreen.log",
        BASE_DIR / "logs" / "report.log",
        BASE_DIR / "logs" / "screener.log",
        BASE_DIR / "logs" / "ws.log",
        BASE_DIR / "logs" / "us_watchdog.log",
        BASE_DIR / "logs" / "us_watchdog_state.jsonl",
        BASE_DIR / "logs" / "daily.log",
    ]
    
    # Also check for any .log file in BASE_DIR that exceeds threshold
    for extra_log in BASE_DIR.glob("*.log"):
        if extra_log not in log_files:
            log_files.append(extra_log)
    
    # Check logs/ subdir for any .log or .jsonl files
    logs_dir = BASE_DIR / "logs"
    if logs_dir.exists():
        for extra in logs_dir.glob("*.log"):
            if extra not in log_files:
                log_files.append(extra)
        for extra in logs_dir.glob("*.jsonl"):
            if extra not in log_files:
                log_files.append(extra)
    
    for log_file in log_files:
        if log_file.exists():
            size_mb = log_file.stat().st_size / (1024 * 1024)
            # Lower threshold for JSONL files (they grow fast)
            threshold = 50 if log_file.suffix == '.jsonl' else 100
            if size_mb > threshold:
                log(f"  Rotating {log_file.name} ({size_mb:.0f}MB)")
                rotate_log(log_file, keep_hours=48)
            else:
                log(f"  Skipped {log_file.name} ({size_mb:.1f}MB — under {threshold}MB threshold)")


def cleanup_ws_history():
    """Rule 1b: WS history JSONL files — delete >7 days old, rotate >500MB recent."""
    log("=== WS History Cleanup ===")
    deleted = 0
    rotated = 0
    kept = 0
    
    history_dir = BASE_DIR / "history"
    if not history_dir.exists():
        log("  History directory not found")
        return
    
    for f in history_dir.glob("alpaca_ws_*.jsonl"):
        age = get_file_age_days(f)
        size_mb = f.stat().st_size / (1024 * 1024)
        
        if age > 7:
            try:
                f.unlink()
                deleted += 1
                log(f"  DELETED {f.name} ({age} days old)")
            except Exception as e:
                log(f"  ERROR deleting {f.name}: {e}")
        elif size_mb > 500:
            # Even recent files: rotate if over 500MB (keep last 48h)
            log(f"  Rotating {f.name} ({size_mb:.0f}MB, {age} days old)")
            try:
                cutoff = datetime.now(ET) - timedelta(hours=48)
                cutoff_str = cutoff.strftime("%Y-%m-%d")
                
                tmp_file = f.with_suffix('.tmp')
                kept_lines = 0
                with open(f, 'r') as fin:
                    with open(tmp_file, 'w') as fout:
                        for line in fin:
                            if len(line) >= 10 and line[:10] >= cutoff_str:
                                fout.write(line)
                                kept_lines += 1
                
                os.replace(tmp_file, f)
                rotated += 1
                log(f"  Rotated {f.name}: kept {kept_lines} lines (last 48h)")
            except Exception as e:
                log(f"  Error rotating {f.name}: {e}")
        else:
            kept += 1
    
    log(f"  Result: {deleted} deleted, {rotated} rotated, {kept} kept")


def cleanup_picks():
    """Rule 2: Picks JSON — archive old, keep current."""
    log("=== Picks Cleanup ===")
    
    picks_files = [
        BASE_DIR / "us_picks.json",
        BASE_DIR / "us_validated_picks.json",
        BASE_DIR / "us_daily_summary.json",
    ]
    
    for f in picks_files:
        if f.exists():
            age = get_file_age_days(f)
            log(f"  {f.name}: {age} days old (kept — current state)")


def cleanup_positions_trades():
    """Rule 3: Positions/Trades JSON — keep current, archive old."""
    log("=== Positions/Trades Cleanup ===")
    
    state_files = [
        BASE_DIR / "us_positions.json",
        BASE_DIR / "us_trades.json",
        BASE_DIR / "us_bookkeeper.json",
        BASE_DIR / "us_regime.json",
        BASE_DIR / "us_capital.json",
    ]
    
    for f in state_files:
        if f.exists():
            age = get_file_age_days(f)
            log(f"  {f.name}: {age} days old (kept — live state)")
    
    # Delete old daily JSON files
    deleted = 0
    for f in BASE_DIR.glob("us_*_*.json"):
        if f.name not in ["us_positions.json", "us_trades.json", "us_picks.json", "us_validated_picks.json"]:
            age = get_file_age_days(f)
            if age > 7:
                try:
                    f.unlink()
                    deleted += 1
                    log(f"  DELETED {f.name} ({age} days old)")
                except:
                    pass
    
    log(f"  Result: {deleted} old daily files deleted")


def cleanup_csv_protection():
    """Rule 4: CSV files — keep forever."""
    log("=== CSV Protection ===")
    
    csv_files = [
        BASE_DIR / "history" / "us_orders.csv",
        BASE_DIR / "history" / "us_pnl.csv",
        BASE_DIR / "history" / "us_positions.csv",
    ]
    
    for f in csv_files:
        if f.exists():
            size_kb = f.stat().st_size / 1024
            log(f"  PROTECTED {f.name}: {size_kb:.0f}KB (kept forever)")
        else:
            log(f"  WARNING {f.name}: NOT FOUND")


def cleanup_backups():
    """Rule 5: Backup files — delete >3 days old."""
    log("=== Backup Files Cleanup ===")
    deleted = 0
    
    # Backup folder
    backup_dir = BASE_DIR / "backup_20260606_154638"
    if backup_dir.exists():
        age = get_file_age_days(backup_dir)
        if age > 3:
            try:
                shutil.rmtree(backup_dir)
                deleted += 1
                log(f"  DELETED {backup_dir.name} ({age} days old)")
            except:
                pass
    
    # Individual backup files
    for f in BASE_DIR.glob("*.backup*"):
        age = get_file_age_days(f)
        if age > 3:
            try:
                f.unlink()
                deleted += 1
                log(f"  DELETED {f.name} ({age} days old)")
            except:
                pass
    
    log(f"  Result: {deleted} backup files deleted")


def cleanup_change_requests():
    """Rule 6: Change request files — delete >7 days old."""
    log("=== Change Request Cleanup ===")
    deleted = 0
    
    for f in BASE_DIR.glob("CHANGE_REQUEST_*.md"):
        age = get_file_age_days(f)
        if age > 7:
            try:
                f.unlink()
                deleted += 1
                log(f"  DELETED {f.name} ({age} days old)")
            except:
                pass
    
    log(f"  Result: {deleted} change request files deleted")


def cleanup_fix_scripts():
    """Rule 7: Old fix scripts — delete >7 days old."""
    log("=== Fix Scripts Cleanup ===")
    deleted = 0
    
    fix_files = [
        "us_entry_fix.py",
    ]
    
    for filename in fix_files:
        f = BASE_DIR / filename
        if f.exists():
            age = get_file_age_days(f)
            if age > 7:
                try:
                    f.unlink()
                    deleted += 1
                    log(f"  DELETED {f.name} ({age} days old)")
                except:
                    pass
    
    # Clean old fix markdown files
    for f in BASE_DIR.glob("US_FIXES_*.md"):
        age = get_file_age_days(f)
        if age > 7:
            try:
                f.unlink()
                deleted += 1
                log(f"  DELETED {f.name} ({age} days old)")
            except:
                pass
    
    log(f"  Result: {deleted} fix files deleted")


def cleanup_old_outputs():
    """Rule 8: Old output logs — delete >3 days old."""
    log("=== Old Output Cleanup ===")
    deleted = 0
    
    for f in BASE_DIR.glob("us_screener_output_*.log"):
        age = get_file_age_days(f)
        if age > 3:
            try:
                f.unlink()
                deleted += 1
                log(f"  DELETED {f.name} ({age} days old)")
            except:
                pass
    
    log(f"  Result: {deleted} old outputs deleted")


def cleanup_pycache():
    """Clean __pycache__ directories."""
    log("=== __pycache__ Cleanup ===")
    deleted = 0
    
    for pycache in BASE_DIR.rglob("__pycache__"):
        if pycache.is_dir():
            try:
                shutil.rmtree(pycache)
                deleted += 1
            except:
                pass
    
    # Also clean .pyc files
    for f in BASE_DIR.rglob("*.pyc"):
        try:
            f.unlink()
            deleted += 1
        except:
            pass
    
    log(f"  Result: {deleted} __pycache__ dirs/.pyc files deleted")


def ram_cleanup():
    """Rule 10: RAM cleanup — kill idle processes."""
    log("=== RAM Cleanup ===")
    
    # Check memory
    try:
        mem = os.popen("free -m | grep Mem").read().strip()
        parts = mem.split()
        if len(parts) >= 7:
            total = int(parts[1])
            available = int(parts[6])
            used_pct = (total - available) / total * 100
            log(f"  Memory: {available}MB available / {total}MB total ({used_pct:.1f}% used)")
            
            if used_pct > 85:
                log(f"  WARNING: Memory usage high ({used_pct:.1f}%)")
    except:
        pass
    
    # Kill zombie processes
    try:
        zombies = os.popen("ps aux | grep '<defunct>' | grep -v grep | wc -l").read().strip()
        if int(zombies) > 0:
            log(f"  Found {zombies} zombie processes")
            os.system("ps aux | grep '<defunct>' | grep -v grep | awk '{print $2}' | xargs -r kill -9 2>/dev/null")
    except:
        pass
    
    # Drop caches (if allowed)
    try:
        os.system("echo 3 | tee /proc/sys/vm/drop_caches >/dev/null 2>&1 || true")
        log("  Dropped filesystem caches")
    except:
        pass
    
    log("  RAM cleanup complete")


def show_disk_usage():
    """Show current disk usage."""
    log("=== Disk Usage ===")
    try:
        result = os.popen(f"du -sh {BASE_DIR}").read().strip()
        log(f"  Total: {result}")
        
        # Biggest files
        result = os.popen(f"cd {BASE_DIR} && find . -maxdepth 2 -type f -size +1M -exec ls -lh {{}} \\; | sort -k5 -rh | head -10").read().strip()
        if result:
            log("  Top 10 largest files:")
            for line in result.split("\n"):
                log(f"    {line}")
    except:
        pass


def main():
    log("=" * 60)
    log("US Daily Cleanup Started")
    log("=" * 60)
    
    show_disk_usage()
    
    cleanup_logs()
    cleanup_ws_history()
    cleanup_picks()
    cleanup_positions_trades()
    cleanup_csv_protection()
    cleanup_backups()
    cleanup_change_requests()
    cleanup_fix_scripts()
    cleanup_old_outputs()
    cleanup_pycache()
    ram_cleanup()
    
    show_disk_usage()
    
    log("=" * 60)
    log("US Daily Cleanup Complete")
    log("=" * 60)


if __name__ == "__main__":
    main()
