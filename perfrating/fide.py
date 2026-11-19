"""Small, polite, cached client for ratings.fide.com."""

from __future__ import annotations

import hashlib
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional, Tuple

BASE = "https://ratings.fide.com"

# FIDE rating type codes used by the calculation endpoints.
FORMAT_CODES = {"classical": 0, "rapid": 1, "blitz": 2}
# Names of the period arrays on calculations.phtml.
FORMAT_ARRAYS = {"classical": "std", "rapid": "rapid", "blitz": "blitz"}
# Open top-100 lists.
TOP_LISTS = {"classical": "open", "rapid": "men_rapid", "blitz": "men_blitz"}


class FideClient:
    def __init__(
        self,
        cache_dir: Optional[Path] = Path(".cache/fide"),
        min_interval: float = 0.25,
        max_interval: Optional[float] = None,
        breaks: Optional[Tuple[int, int]] = None,
        break_length: Tuple[float, float] = (60.0, 120.0),
        retries: int = 4,
        timeout: float = 30.0,
    ) -> None:
        """Requests start at least ``min_interval`` seconds apart, or a random
        gap up to ``max_interval``.  With ``breaks`` = (lo, hi), the client
        also rests for ``break_length`` seconds after every lo..hi requests."""
        self.cache_dir = cache_dir
        self.min_interval = min_interval
        self.max_interval = max_interval if max_interval is not None else min_interval
        self.breaks = breaks
        self.break_length = break_length
        self.retries = retries
        self.timeout = timeout
        self._lock = threading.Lock()
        self._next_slot = 0.0
        self._until_break = random.randint(*breaks) if breaks else 0
        self.requests_made = 0
        if cache_dir:
            cache_dir.mkdir(parents=True, exist_ok=True)

    def _throttle(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait = self._next_slot - now
            gap = random.uniform(self.min_interval, self.max_interval)
            if self.breaks:
                self._until_break -= 1
                if self._until_break <= 0:
                    gap += random.uniform(*self.break_length)
                    self._until_break = random.randint(*self.breaks)
            self._next_slot = max(now, self._next_slot) + gap
        if wait > 0:
            time.sleep(wait)

    def get(self, path: str, params: dict, ajax: bool = False, refresh: bool = False) -> str:
        """Fetch a page.  ``refresh`` skips the cache read but still stores.

        Empty bodies are never cached: FIDE sometimes returns one for a page
        that does have content, so they are worth asking for again.
        """
        url = f"{BASE}{path}?{urllib.parse.urlencode(params)}"
        cache_file = None
        if self.cache_dir:
            cache_file = self.cache_dir / (hashlib.sha1(url.encode()).hexdigest() + ".html")
            if not refresh and cache_file.exists():
                return cache_file.read_text(encoding="utf-8")
        headers = {"User-Agent": "chess-performance-rating (+https://github.com/anton-g-kulikov/chess-performance-rating)"}
        if ajax:
            # The calculation fragments are only served to the site's own
            # XHR requests, which send this header.
            headers["X-Requested-With"] = "XMLHttpRequest"
        last_err: Optional[Exception] = None
        for attempt in range(self.retries + 1):
            self._throttle()
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    body = resp.read().decode("utf-8-sig", errors="replace")
                self.requests_made += 1
                break
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                last_err = e
                time.sleep(2 ** attempt)
        else:
            raise RuntimeError(f"failed to fetch {url}: {last_err}")
        if cache_file and body.replace("\ufeff", "").strip():
            cache_file.write_text(body, encoding="utf-8")
        return body

    # Endpoints -----------------------------------------------------------

    def top_list(self, fmt: str) -> str:
        return self.get("/a_top.php", {"list": TOP_LISTS[fmt]})

    def calculations_page(self, fide_id: int, period: str) -> str:
        return self.get(
            "/calculations.phtml", {"id_number": fide_id, "period": period, "rating": 0}
        )

    def calculation(self, fide_id: int, period: str, fmt: str, refresh: bool = False) -> str:
        return self.get(
            "/a_indv_calculation.php",
            {"id_number": fide_id, "rating_period": period, "t": FORMAT_CODES[fmt]},
            ajax=True,
            refresh=refresh,
        )
