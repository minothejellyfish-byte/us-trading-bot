#!/usr/bin/env python3

import sys
from datetime import datetime
import pandas_market_calendars as mcal

def is_us_trading_day(date=None):
    """
    Check if today is a US trading day
    Returns 0 if it's a trading day, 1 if it's a holiday/weekend
    """
    if date is None:
        date = datetime.now()
    
    # Get NYSE calendar
    nyse = mcal.get_calendar('NYSE')
    
    # Check if date is in valid range (pandas_market_calendars has limits)
    try:
        schedule = nyse.schedule(start_date=date.strftime('%Y-%m-%d'), 
                                end_date=date.strftime('%Y-%m-%d'))
        is_trading_day = not schedule.empty
        return 0 if is_trading_day else 1
    except Exception:
        # Fallback check for weekends
        return 1 if date.weekday() > 4 else 0

if __name__ == "__main__":
    result = is_us_trading_day()
    if result == 0:
        print("Today is a US trading day")
    else:
        print("Today is not a US trading day (holiday/weekend)")
    sys.exit(result)