"""Race replay: how a calendar-year list developed, month by month.

The data side, ``race_frames``, gives each year list the top of the table at
the end of every month so far.  The page side is ``race.html`` (markup),
``race.css`` and ``race.js``, which ``inline`` puts into ``page.html`` at its
``<!--RACE_HTML-->``, ``/*RACE_CSS*/`` and ``/*RACE_JS*/`` markers.  The
script runs in the page's own scope and uses its helpers (``$``, ``M``,
``state``, ``PEOPLE``...); the page calls ``renderRace()`` and ``stopRace()``.
"""

from __future__ import annotations

import re
from pathlib import Path

from .build import DEFAULT_MIN_GAMES, FORMATS, build_rows, event_month, scaled_minimum

HERE = Path(__file__).parent
RACE_TOP = 10


def race_frames(saved: dict, fmt: str, months: int, final_min: int) -> list:
    """The top of a year's list at the end of each month so far.

    Each frame counts events that ended by then, with the minimum number of
    games scaled to the months played (never below half the full minimum);
    the last frame is the published list."""
    base = dict(zip(FORMATS, (int(x) for x in DEFAULT_MIN_GAMES.split(","))))
    year = saved["year"]
    pool = {int(fid): info for fid, info in saved["players"].items()}
    frames = []
    for m in range(1, months + 1):
        cut = f"{year}-{m:02d}"
        last = m == months
        games = {fid: {fmt: [e for e in info["games"][fmt] if last or event_month(e) <= cut]}
                 for fid, info in pool.items()}
        need = final_min if last else scaled_minimum(base, m / 12)[fmt]
        rows = build_rows(pool, games, fmt, need)
        frames.append({"m": m, "min": need, "q": len(rows),
                       "rows": [[r["fide_id"], r["tpr"], r["games"]] for r in rows[:RACE_TOP]]})
    return frames


def inline(page: str) -> str:
    """``page`` with the race markup, styles and script filled in."""
    def read(name: str) -> str:
        return (HERE / name).read_text(encoding="utf-8").rstrip("\n")

    def markup(m: re.Match) -> str:
        return "\n".join(m.group(1) + line if line else line for line in read("race.html").split("\n"))

    page = re.sub(r"^([ \t]*)<!--RACE_HTML-->", markup, page, count=1, flags=re.M)
    return page.replace("/*RACE_CSS*/", read("race.css")).replace("/*RACE_JS*/", read("race.js"))
