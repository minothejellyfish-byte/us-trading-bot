#!/usr/bin/env python3
"""
US Evaluator — v4.12
====================
Two-gate evaluation system for US paper trading.

Gate 1: Validation (softer than TASI)
  - Pick freshness (< 45 min old)
  - Price in entry zone
  - Volume confirmation (relaxed)
  
Gate 2: Scoring (dynamic, regime-aware)
  - Real-time WS data integration
  - Symmetric thresholds (softer for paper)
  - Midscreen picks get bonus

Author: Mino (kimi-k2.6)
Version: 4.12
Date: 2026-06-23
"""

import json
import os
from datetime import datetime, time, timedelta
from typing import Dict, List, Optional, Tuple
from pathlib import Path

import pytz

ET = pytz.timezone("America/New_York")
BASE_DIR = Path("/home/mino/us-exec")

# ─── Softer Thresholds for Paper Trading ────────────────────────────────────

# Gate 1: Validation thresholds (softer than TASI)
GATE1_CONFIG = {
    "TRENDING": {
        "max_age_min": 45,           # Was 30 in TASI
        "price_zone_tol": 0.03,     # ±3% zone (was ±0.5% in TASI)
        "min_rel_volume": 1.0,       # 1x avg volume (was 1.5x)
        "min_change_pct": -2.0,      # Accept down to -2%
        "max_change_pct": 8.0,       # Up to 8%
    },
    "NEUTRAL": {
        "max_age_min": 45,
        "price_zone_tol": 0.025,    # ±2.5%
        "min_rel_volume": 1.0,
        "min_change_pct": -1.5,
        "max_change_pct": 6.0,
    },
    "DEFENSIVE": {
        "max_age_min": 45,
        "price_zone_tol": 0.02,     # ±2%
        "min_rel_volume": 0.8,       # Even lower in defensive
        "min_change_pct": -1.0,
        "max_change_pct": 4.0,
    },
}

# Gate 2: Scoring thresholds (symmetric, softer)
GATE2_CONFIG = {
    "TRENDING": {
        "pass_threshold": 65,        # Was 80 in TASI
        "momentum_weight": 25,       # ±25 points (was ±30)
        "volume_weight": 20,         # ±20 points (was ±25)
        "vwap_weight": 20,           # ±20 points
        "breakout_weight": 10,       # ±10 points
    },
    "NEUTRAL": {
        "pass_threshold": 60,        # Was 70 in TASI
        "momentum_weight": 20,       # ±20 points
        "volume_weight": 15,         # ±15 points
        "vwap_weight": 15,           # ±15 points
        "breakout_weight": 10,       # ±10 points
    },
    "DEFENSIVE": {
        "pass_threshold": 55,        # Was 60 in TASI
        "momentum_weight": 15,       # ±15 points
        "volume_weight": 10,         # ±10 points
        "vwap_weight": 10,           # ±10 points
        "breakout_weight": 5,        # ±5 points
    },
}

# ─── Gate 1: Validation ───────────────────────────────────────────────────────

def gate1_validate(pick: Dict, regime: str = "NEUTRAL", 
                   current_price: Optional[float] = None) -> Tuple[bool, str, Dict]:
    """Validate a pick before scoring.
    
    Returns:
        (passed, reason, enriched_pick)
    """
    config = GATE1_CONFIG.get(regime, GATE1_CONFIG["NEUTRAL"])
    
    symbol = pick.get("symbol", "")
    if not symbol:
        return False, "Missing symbol", pick
    
    # Check pick freshness
    pick_time = pick.get("time", "")
    if pick_time:
        try:
            # Parse time string (HH:MM:SS format)
            now = datetime.now(ET)
            pick_dt = now.replace(
                hour=int(pick_time.split(":")[0]),
                minute=int(pick_time.split(":")[1]),
                second=int(pick_time.split(":")[2]) if len(pick_time.split(":")) > 2 else 0
            )
            age_min = (now - pick_dt).total_seconds() / 60
            if age_min > config["max_age_min"]:
                return False, f"Stale pick ({age_min:.0f} min > {config['max_age_min']} min)", pick
        except:
            pass
    
    # Check price in zone
    entry_low = pick.get("entry_low", 0)
    entry_high = pick.get("entry_high", 0)
    price = current_price or pick.get("price", 0)
    
    if price > 0 and entry_low > 0 and entry_high > 0:
        zone_tol = config["price_zone_tol"]
        if not (entry_low * (1 - zone_tol) <= price <= entry_high * (1 + zone_tol)):
            return False, f"Price ${price:.2f} outside zone ${entry_low:.2f}-${entry_high:.2f} (±{zone_tol*100:.0f}%)", pick
    
    # Check volume
    rel_volume = pick.get("rel_volume", 0)
    if rel_volume < config["min_rel_volume"]:
        return False, f"Volume {rel_volume:.1f}x < {config['min_rel_volume']}x", pick
    
    # Check change %
    change_pct = pick.get("change_pct", 0)
    if change_pct < config["min_change_pct"] or change_pct > config["max_change_pct"]:
        return False, f"Change {change_pct:.1f}% outside range [{config['min_change_pct']:.0f}%, {config['max_change_pct']:.0f}%]", pick
    
    # Enrich pick with validation info
    enriched = dict(pick)
    enriched["validated"] = True
    enriched["validation_time"] = datetime.now(ET).isoformat()
    
    return True, "Passed Gate 1", enriched


# ─── Gate 2: Scoring ────────────────────────────────────────────────────────

def gate2_evaluate(pick: Dict, regime: str = "NEUTRAL",
                   ws_price: Optional[float] = None,
                   ws_volume: Optional[int] = None) -> Tuple[float, str, Dict]:
    """Score a validated pick.
    
    Returns:
        (score, reason, enriched_pick)
    """
    config = GATE2_CONFIG.get(regime, GATE2_CONFIG["NEUTRAL"])
    
    symbol = pick.get("symbol", "")
    score = pick.get("score", 50)  # Base score from screener
    
    # Start with base score
    final_score = score
    adjustments = []
    
    # Momentum adjustment (symmetric)
    change_pct = pick.get("change_pct", 0)
    if abs(change_pct) <= 0.5:
        # Neutral — small bonus for stability
        momentum_adj = config["momentum_weight"] * 0.3
        adjustments.append(f"Stable momentum: +{momentum_adj:.0f}")
    elif change_pct > 0:
        # Positive momentum — scale bonus
        momentum_adj = min(change_pct * 5, config["momentum_weight"])
        adjustments.append(f"Positive momentum: +{momentum_adj:.0f}")
    else:
        # Negative momentum — penalty
        momentum_adj = max(change_pct * 3, -config["momentum_weight"])
        adjustments.append(f"Negative momentum: {momentum_adj:.0f}")
    
    final_score += momentum_adj
    
    # Volume adjustment (symmetric)
    rel_volume = pick.get("rel_volume", 1.0)
    if rel_volume >= 2.0:
        volume_adj = config["volume_weight"]
        adjustments.append(f"High volume ({rel_volume:.1f}x): +{volume_adj:.0f}")
    elif rel_volume >= 1.5:
        volume_adj = config["volume_weight"] * 0.5
        adjustments.append(f"Above avg volume ({rel_volume:.1f}x): +{volume_adj:.0f}")
    elif rel_volume >= 1.0:
        volume_adj = 0
        adjustments.append(f"Normal volume ({rel_volume:.1f}x): +0")
    else:
        volume_adj = -config["volume_weight"] * 0.5
        adjustments.append(f"Low volume ({rel_volume:.1f}x): {volume_adj:.0f}")
    
    final_score += volume_adj
    
    # VWAP adjustment
    vwap = pick.get("vwap")
    price = ws_price or pick.get("price", 0)
    if vwap and price > 0:
        if price > vwap * 1.01:
            vwap_adj = config["vwap_weight"]
            adjustments.append(f"Above VWAP (${vwap:.2f}): +{vwap_adj:.0f}")
        elif price < vwap * 0.99:
            vwap_adj = -config["vwap_weight"] * 0.5
            adjustments.append(f"Below VWAP (${vwap:.2f}): {vwap_adj:.0f}")
        else:
            vwap_adj = 0
            adjustments.append(f"At VWAP (${vwap:.2f}): +0")
        final_score += vwap_adj
    
    # Breakout adjustment
    if pick.get("source") == "midscreen":
        # Midscreen picks get bonus for intraday momentum
        breakout_adj = config["breakout_weight"] * 0.5
        adjustments.append(f"Midscreen source: +{breakout_adj:.0f}")
        final_score += breakout_adj
    
    # WS price confirmation bonus
    if ws_price and price > 0:
        ws_diff = abs(ws_price - price) / price
        if ws_diff <= 0.001:  # Within 0.1%
            ws_adj = 5
            adjustments.append(f"WS confirmed: +{ws_adj:.0f}")
            final_score += ws_adj
    
    # Clamp score
    final_score = max(0, min(100, final_score))
    
    # Determine pass/fail
    passed = final_score >= config["pass_threshold"]
    
    if passed:
        reason = f"✅ PASS ({final_score:.0f}/100 >= {config['pass_threshold']}) — " + " | ".join(adjustments)
    else:
        reason = f"❌ FAIL ({final_score:.0f}/100 < {config['pass_threshold']}) — " + " | ".join(adjustments)
    
    # Enrich pick
    enriched = dict(pick)
    enriched["evaluator_score"] = round(final_score, 1)
    enriched["evaluator_passed"] = passed
    enriched["evaluator_reason"] = reason
    enriched["evaluated_at"] = datetime.now(ET).isoformat()
    enriched["regime"] = regime
    
    return final_score, reason, enriched


# ─── Full Evaluation Pipeline ──────────────────────────────────────────────

def evaluate_picks(picks: List[Dict], regime: str = "NEUTRAL",
                   ws_prices: Optional[Dict[str, float]] = None) -> List[Dict]:
    """Evaluate a list of picks through both gates.
    
    Returns:
        List of enriched picks that passed Gate 1 ( Gate 2 score attached)
    """
    results = []
    
    for pick in picks:
        # Gate 1
        g1_pass, g1_reason, g1_pick = gate1_validate(pick, regime)
        
        if not g1_pass:
            # Still include but mark as failed
            failed = dict(pick)
            failed["gate1_passed"] = False
            failed["gate1_reason"] = g1_reason
            failed["gate2_passed"] = False
            failed["evaluator_score"] = 0
            results.append(failed)
            continue
        
        # Gate 2
        symbol = pick.get("symbol", "")
        ws_price = ws_prices.get(symbol) if ws_prices else None
        
        score, g2_reason, g2_pick = gate2_evaluate(g1_pick, regime, ws_price)
        
        g2_pick["gate1_passed"] = True
        g2_pick["gate1_reason"] = g1_reason
        g2_pick["gate2_passed"] = g2_pick["evaluator_passed"]
        
        results.append(g2_pick)
    
    # Sort by evaluator score (highest first)
    results.sort(key=lambda x: x.get("evaluator_score", 0), reverse=True)
    
    return results


# ─── File I/O ──────────────────────────────────────────────────────────────

def load_picks() -> List[Dict]:
    """Load picks from us_picks.json."""
    picks_file = BASE_DIR / "us_picks.json"
    if not picks_file.exists():
        return []
    try:
        with open(picks_file) as f:
            data = json.load(f)
            picks = data.get("picks", [])
            return picks if isinstance(picks, list) else []
    except:
        return []


def save_evaluated_picks(picks: List[Dict]):
    """Save evaluated picks back to us_picks.json."""
    picks_file = BASE_DIR / "us_picks.json"
    try:
        with open(picks_file, "w") as f:
            json.dump({
                "picks": picks,
                "evaluated_at": datetime.now(ET).isoformat(),
                "count": len(picks),
                "passed": sum(1 for p in picks if p.get("evaluator_passed", False)),
            }, f, indent=2)
    except Exception as e:
        print(f"Failed to save picks: {e}")


# ─── Main ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== US Evaluator Test ===\n")
    
    # Test picks
    test_picks = [
        {
            "symbol": "AAPL",
            "score": 70,
            "price": 175.50,
            "entry_low": 174.0,
            "entry_high": 176.0,
            "change_pct": 2.5,
            "rel_volume": 1.8,
            "vwap": 174.80,
            "source": "screener",
            "time": "09:45:00",
        },
        {
            "symbol": "AMD",
            "score": 65,
            "price": 145.00,
            "entry_low": 144.0,
            "entry_high": 146.0,
            "change_pct": -1.2,
            "rel_volume": 0.8,
            "vwap": 146.50,
            "source": "midscreen",
            "time": "09:30:00",
        },
    ]
    
    # Test with NEUTRAL regime
    print("NEUTRAL Regime:")
    config = GATE2_CONFIG["NEUTRAL"]
    print(f"  Pass threshold: {config['pass_threshold']}/100")
    print(f"  Momentum weight: ±{config['momentum_weight']}")
    print(f"  Volume weight: ±{config['volume_weight']}")
    print()
    
    results = evaluate_picks(test_picks, regime="NEUTRAL")
    
    for pick in results:
        symbol = pick["symbol"]
        score = pick.get("evaluator_score", 0)
        passed = pick.get("evaluator_passed", False)
        reason = pick.get("evaluator_reason", "")
        
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} {symbol}: {score:.0f}/100")
        print(f"  Reason: {reason}")
        print()
    
    print("=== Test Complete ===")
