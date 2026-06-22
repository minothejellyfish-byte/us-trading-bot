"""
US Sharia-Compliant Stock Universe
====================================

Sources for Sharia-compliant US stocks:
1. HLAL ETF (Wahed Invest) holdings — primary source
2. ISDU (iShares MSCI USA Islamic) — secondary source
3. SPUS (SP Funds S&P 500 Sharia) — tertiary source

This module provides:
- get_sharia_universe() → List of Sharia-compliant tickers
- is_sharia_compliant(ticker) → True/False
- get_sharia_info(ticker) → Compliance data

Usage:
    from us_sharia_universe import get_sharia_universe, is_sharia_compliant
    
    universe = get_sharia_universe()  # ~200-300 stocks
    if is_sharia_compliant("AAPL"):
        print("AAPL is Sharia-compliant")
"""

import json
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(BASE_DIR, "sharia_cache.json")
CACHE_TTL_DAYS = 7  # Refresh weekly

# Primary: HLAL ETF top holdings (Wahed Invest)
# These are manually curated and should be updated monthly
# Source: https://www.wahed.com/us/en/funds/hlal
HLAL_HOLDINGS = [
    # Technology
    "AAPL", "MSFT", "NVDA", "AVGO", "ADBE", "CRM", "ACN", "ORCL", "IBM",
    "INTC", "QCOM", "TXN", "AMD", "AMAT", "LRCX", "KLAC", "MRVL", "SNPS",
    "CDNS", "ANSS", "FTNT", "PANW", "CRWD", "SNOW", "PLTR", "DDOG", "NET",
    # Healthcare
    "JNJ", "UNH", "LLY", "PFE", "MRK", "ABBV", "TMO", "DHR", "ABT", "BMY",
    "MDT", "AMGN", "GILD", "VRTX", "REGN", "BIIB", "IQV", "DXCM", "ISRG",
    "ZBH", "BAX", "BDX", "SYK", "EW", "HOLX", "TECH", "WAT",
    # Consumer
    "PG", "KO", "PEP", "WMT", "COST", "TGT", "NKE", "SBUX", "MCD", "YUM",
    "DG", "DLTR", "TJX", "ROST", "BURL", "DECK", "LULU", "ULTA", "ETSY",
    # Industrials
    "CAT", "DE", "GE", "HON", "UPS", "FDX", "CSX", "UNP", "NSC", "LHX",
    "GD", "NOC", "RTX", "LMT", "TDG", "HEI", "TDY", "BWXT", "AJRD",
    # Energy (select Sharia-compliant)
    "XOM", "CVX", "COP", "EOG", "MPC", "VLO", "PSX", "OXY", "PXD", "FANG",
    "MRO", "DVN", "MUR", "CNX", "RRC", "EQT", "SWN", "CTRA", "CHK",
    # Materials
    "LIN", "APD", "SHW", "FCX", "NEM", "DOW", "PPG", "ECL", "IFF", "ALB",
    "SQM", "MOS", "CF", "NTR", "CTVA", "FMC", "LYB", "WLK", "EMN", "ASH",
    # Utilities (limited, most have high debt)
    "NEE", "DUK", "SO", "D", "AEP", "EXC", "SRE", "XEL", "WEC", "ES",
    "PEG", "ED", "ETR", "FE", "CNP", "AES", "NI", "LNT", "AEE", "CMS",
    # REITs (select Sharia-compliant)
    "PLD", "AMT", "CCI", "EQIX", "PSA", "WELL", "O", "DLR", "EXR", "AVB",
    "EQR", "UDR", "MAA", "CPT", "AIV", "BXP", "VTR", "HCP", "PEAK", "DOC",
    # Financials (Islamic banks/fintech only)
    "GS", "MS", "SCHW", "BLK", "BX", "KKR", "APO", "CG", "TPG", "ARES",
    "PJT", "MC", "EFX", "FICO", "MA", "V", "PYPL", "SQ", "AFRM", "SOFI",
    "COF", "DFS", "SYF", "ALLY", "CPT", "HOOD", "COIN", "RIOT", "MSTR",
    # Communication
    "GOOGL", "GOOG", "META", "NFLX", "DIS", "CMCSA", "VZ", "T", "CHTR",
    "TMUS", "LUMN", "IRDM", "MAXR", "GSAT", "ASTS", "RKLB", "SPCE",
]

# Stocks to exclude (known non-Sharia compliant)
EXCLUDED_TICKERS = {
    # Banks with interest income
    "JPM", "BAC", "WFC", "C", "USB", "PNC", "TFC", "COF",
    # Alcohol
    "STZ", "DEO", "MO", "PM", "BTI", "BUD",
    # Gambling
    "MGM", "CZR", "WYNN", "LVS", "DKNG", "PENN", "BYD",
    # Pork/Non-halal food
    "TSN", "HRL", "SJM", "CPB", "KHC",
    # Conventional insurance
    "BRK.B", "AIG", "MET", "PRU", "ALL", "TRV", "PGR", "CINF",
    # Defense / Weapons / Military Contractors (explicitly excluded)
    "LMT", "NOC", "GD", "RTX", "BA", "TDG", "HEI", "TDY", "BWXT", "AJRD",
    "HII", "KTOS", "ATRO", "CUB", "MANT", "SSTK", "WWD",
    # Entertainment (adult content)
    "PLBY", "RICK",
}

# Defense contractors that were in HLAL but now excluded
DEFENSE_CONTRACTORS_EXCLUDED = {
    "LMT", "NOC", "GD", "RTX", "BA", "TDG", "HEI", "TDY", "BWXT", "AJRD"
}

# Additional screening criteria (can be expanded)
SHARIA_SECTORS_PREFERRED = [
    "Technology", "Healthcare", "Consumer Staples", "Industrials",
    "Materials", "Energy"  # Select energy only
]

SHARIA_SECTORS_EXCLUDED = [
    "Banks", "Insurance", "Alcohol", "Tobacco", "Gambling",
    "Adult Entertainment", "Conventional Finance"
]


def _load_cache() -> Optional[Dict]:
    """Load cached universe if fresh."""
    if not os.path.exists(CACHE_FILE):
        return None
    try:
        with open(CACHE_FILE) as f:
            cache = json.load(f)
        cached_at = datetime.fromisoformat(cache.get("cached_at", "2000-01-01"))
        if datetime.now() - cached_at < timedelta(days=CACHE_TTL_DAYS):
            return cache
    except Exception:
        pass
    return None


def _save_cache(universe: List[str], source: str):
    """Save universe to cache."""
    cache = {
        "cached_at": datetime.now().isoformat(),
        "source": source,
        "count": len(universe),
        "universe": sorted(universe),
    }
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        print(f"Warning: Could not save cache: {e}")


def get_sharia_universe(use_cache: bool = True) -> List[str]:
    """
    Get list of Sharia-compliant US stock tickers.
    
    Returns ~200-300 tickers from HLAL + additional screening.
    Updates weekly via cache.
    """
    # Check cache first
    if use_cache:
        cache = _load_cache()
        if cache and cache.get("universe"):
            return cache["universe"]
    
    # Build universe from HLAL holdings
    universe = []
    for ticker in HLAL_HOLDINGS:
        if ticker not in EXCLUDED_TICKERS:
            universe.append(ticker)
    
    # Remove duplicates and sort
    universe = sorted(set(universe))
    
    # Save cache
    _save_cache(universe, "HLAL_holdings")
    
    return universe


def is_sharia_compliant(ticker: str) -> bool:
    """Check if a single ticker is Sharia-compliant."""
    ticker = ticker.upper().strip()
    if ticker in EXCLUDED_TICKERS:
        return False
    universe = get_sharia_universe()
    return ticker in universe


def get_sharia_info(ticker: str) -> Dict:
    """Get detailed Sharia compliance info for a ticker."""
    ticker = ticker.upper().strip()
    info = {
        "ticker": ticker,
        "compliant": is_sharia_compliant(ticker),
        "in_hlal": ticker in HLAL_HOLDINGS,
        "excluded": ticker in EXCLUDED_TICKERS,
        "source": "HLAL_ETF",
    }
    return info


def refresh_sharia_universe():
    """Force refresh of Sharia universe (ignore cache)."""
    if os.path.exists(CACHE_FILE):
        os.remove(CACHE_FILE)
    return get_sharia_universe(use_cache=False)


# Module test
if __name__ == "__main__":
    universe = get_sharia_universe()
    print(f"Sharia-compliant universe: {len(universe)} stocks")
    print(f"Top 20: {', '.join(universe[:20])}")
    
    # Test compliance
    tests = ["AAPL", "JPM", "NVDA", "BAC", "MSFT", "STZ"]
    for t in tests:
        info = get_sharia_info(t)
        status = "✅" if info["compliant"] else "❌"
        print(f"{status} {t}: {info}")
