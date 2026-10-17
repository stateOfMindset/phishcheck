"""In-memory sliding-window rate limiter for POST /chat.

Every /chat request costs real money (2-3 Claude API calls), so each client IP gets a budget,
for example 10 messages per minute and 200 per day. The limiter keeps the timestamps of each
client's recent requests and, for every window, counts how many fall inside it. A request is
allowed only if every window still has room.

State lives in this process's memory: it resets when the server restarts and is not shared
between several server processes. That is fine for this single-process prototype; a deployed
version would keep the counters in a shared store such as Redis.
"""
import bisect
import threading
import time


class RateLimiter:
    def __init__(self, limits: list[tuple[int, int]]):
        """`limits` is a list of (max_requests, window_seconds), e.g. [(10, 60), (200, 86400)]."""
        self.limits = [(n, w) for n, w in limits if n > 0 and w > 0]
        self._longest = max((w for _, w in self.limits), default=0)
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str, now: float | None = None) -> int | None:
        """Record a request from `key` if allowed.

        Returns None when the request is allowed, otherwise the number of seconds until the
        client may try again. Rejected requests are not recorded, so waiting always helps.
        """
        if not self.limits:
            return None
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits.setdefault(key, [])
            # Forget timestamps older than the longest window; they can never count again.
            del hits[:bisect.bisect_right(hits, now - self._longest)]

            retry_after = 0.0
            for max_requests, window in self.limits:
                start = bisect.bisect_right(hits, now - window)
                in_window = len(hits) - start
                if in_window >= max_requests:
                    # The oldest request in the window must expire before there is room.
                    oldest = hits[in_window - max_requests + start]
                    retry_after = max(retry_after, oldest + window - now)
            if retry_after > 0:
                return max(1, int(retry_after + 0.999))

            hits.append(now)
            return None
