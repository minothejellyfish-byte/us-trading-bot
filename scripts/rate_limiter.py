"""Rate limiter for Twelve Data API.
Free tier: 8 requests/minute, 800/day.
"""

import time
from threading import Lock

class TwelveDataRateLimiter:
    """Simple rate limiter: max 1 request per 8 seconds (7.5/min for safety)."""
    
    def __init__(self, min_interval=8.0):
        self.min_interval = min_interval  # seconds between requests
        self.last_request = 0
        self.lock = Lock()
    
    def wait(self):
        """Block until rate limit allows next request."""
        with self.lock:
            now = time.time()
            elapsed = now - self.last_request
            if elapsed < self.min_interval:
                sleep_time = self.min_interval - elapsed
                time.sleep(sleep_time)
            self.last_request = time.time()

# Global limiter instance
rate_limiter = TwelveDataRateLimiter(min_interval=8.0)
