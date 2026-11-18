"""Performance-rating maths.

Two numbers are computed for a set of games:

* ``tpr`` -- the FIDE tournament performance rating, ``Ra + dp`` where ``Ra``
  is the average opponent rating and ``dp`` comes from the FIDE conversion
  table (FIDE Handbook B.02, table 8.1a) for the fractional score ``p``
  rounded to two decimals.  This is the number the lists are sorted by.
* ``true`` -- the rating ``R`` at which the FIDE expected score against the
  actual opponents equals the actual score.  It accounts for the spread of
  opponent ratings, and is undefined for 0% and 100% scores.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable, Optional, Sequence, Tuple

# dp for p = 0.50 .. 1.00 in steps of 0.01 (FIDE table 8.1a).
_DP_UPPER = [
    0, 7, 14, 21, 29, 36, 43, 50, 57, 65,      # .50 - .59
    72, 80, 87, 95, 102, 110, 117, 125, 133, 141,  # .60 - .69
    149, 158, 166, 175, 184, 193, 202, 211, 220, 230,  # .70 - .79
    240, 251, 262, 273, 284, 296, 309, 322, 336, 351,  # .80 - .89
    366, 383, 401, 422, 444, 470, 501, 538, 589, 677,  # .90 - .99
    800,                                           # 1.00
]


def round_p(score: float, games: int) -> Decimal:
    """Fractional score rounded half-up to two decimals."""
    return (Decimal(str(score)) / Decimal(games)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def dp(p: Decimal) -> int:
    """FIDE rating difference for a fractional score ``p`` (two decimals)."""
    hundredths = int(p * 100)
    if not 0 <= hundredths <= 100:
        raise ValueError(f"p out of range: {p}")
    if hundredths >= 50:
        return _DP_UPPER[hundredths - 50]
    return -_DP_UPPER[50 - hundredths]


def expected(rating: float, opponent: float) -> float:
    """FIDE/Elo expected score of ``rating`` against ``opponent``."""
    return 1.0 / (1.0 + 10 ** ((opponent - rating) / 400.0))


def true_performance(opponents: Sequence[float], score: float) -> Optional[float]:
    """Rating whose expected score against ``opponents`` equals ``score``."""
    n = len(opponents)
    if n == 0 or score <= 0 or score >= n:
        return None
    lo, hi = min(opponents) - 1600.0, max(opponents) + 1600.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if sum(expected(mid, r) for r in opponents) < score:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


@dataclass(frozen=True)
class Performance:
    games: int
    score: float
    avg_opp: float
    p: Decimal
    tpr: int
    true: Optional[float]


def performance(games: Iterable[Tuple[float, float]]) -> Optional[Performance]:
    """Performance over ``(opponent_rating, result)`` pairs."""
    games = list(games)
    if not games:
        return None
    opps = [g[0] for g in games]
    score = sum(g[1] for g in games)
    n = len(games)
    avg = sum(opps) / n
    p = round_p(score, n)
    return Performance(
        games=n,
        score=score,
        avg_opp=avg,
        p=p,
        tpr=round(avg + dp(p)),
        true=true_performance(opps, score),
    )
