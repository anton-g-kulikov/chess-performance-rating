"""World Championship results while the match is being played.

FIDE's game-by-game data only arrives with the rating list after a match, so
until then a match page reads its games from Lichess's official broadcast of
the match, through Lichess's public API (https://lichess.org/api, "Broadcasts").
Only the facts of each game are kept: who had white, the two ratings, the
result.  No moves.

    python -m perfrating.live          # refresh data/live-world-championship-YYYY.json

Run it after each game, then rebuild the site (``python -m perfrating.web``).
The file it writes is small and can be edited by hand if Lichess is down.  Once
FIDE's own data holds the match, the build uses that and ignores the file.

The API asks for a User-Agent naming the site and one request at a time, and
for a minute's wait after a 429; the requests here are made one after another.
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

from .matches import MATCHES, slug

API = "https://lichess.org/api/broadcast"
AGENT = "https://chesstpr.com/ (match results for the World Championship pages)"
RESULTS = {"1-0": 1.0, "0-1": 0.0, "1/2-1/2": 0.5}


def path(year: int, data: Path = Path("data")) -> Path:
    return data / f"live-{slug(year)}.json"


def load(year: int, data: Path = Path("data")) -> Optional[dict]:
    p = path(year, data)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def headers(pgn: str) -> List[Dict[str, str]]:
    """The tag pairs of each game in a PGN file, in order."""
    games, cur = [], None
    for line in pgn.splitlines():
        m = re.match(r'\[(\w+) "(.*)"\]\s*$', line.strip())
        if not m:
            continue
        if m.group(1) == "Event" and cur is not None:
            games.append(cur)
            cur = None
        cur = cur or {}
        cur[m.group(1)] = m.group(2).replace('\\"', '"')
    if cur:
        games.append(cur)
    return games


def time_format(tc: str, fallback: str = "classical") -> str:
    """classical, rapid or blitz from a PGN TimeControl ("40/7200:1800+30",
    "900+10", "180+2"), by FIDE's lines: 60 minutes or more for a 60-move game
    is standard, more than 10 is rapid, the rest blitz."""
    first = (tc or "").split(":")[0]
    m = re.fullmatch(r"(?:(\d+)/)?(\d+)(?:\+(\d+))?", first)
    if not m:
        return fallback
    if m.group(1):          # a move count before the first control: a classical game
        return "classical"
    total = int(m.group(2)) + 60 * int(m.group(3) or 0)
    return "classical" if total >= 3600 else "rapid" if total > 600 else "blitz"


FIDE_TC = {"standard": "classical", "rapid": "rapid", "blitz": "blitz"}


def games(tags: List[Dict[str, str]], a: int, b: int, order: Dict[str, int], fallback: str = "classical") -> List[dict]:
    """The finished games between ``a`` and ``b``, oldest first.  ``order``
    places each broadcast round (its id, the last part of BroadcastURL)."""
    out = []
    for t in tags:
        if t.get("Result") not in RESULTS:
            continue        # not started, or still being played
        try:
            w, k = int(t.get("WhiteFideId", 0)), int(t.get("BlackFideId", 0))
        except ValueError:
            continue
        if {w, k} != {a, b}:
            continue
        rid = (t.get("BroadcastURL") or "").rstrip("/").rsplit("/", 1)[-1]
        out.append({
            "f": time_format(t.get("TimeControl", ""), fallback),
            "date": t.get("Date", "").replace(".", "-"),
            "round": t.get("Round", ""),
            "white": w, "black": k,
            "white_rating": int(t["WhiteElo"]) if t.get("WhiteElo", "").isdigit() else None,
            "black_rating": int(t["BlackElo"]) if t.get("BlackElo", "").isdigit() else None,
            "result": t["Result"],
            "_at": (order.get(rid, 999), t.get("Date", ""), _num(t.get("Round", ""))),
        })
    out.sort(key=lambda g: g.pop("_at"))
    return out


def _num(s: str):
    return tuple(int(x) for x in re.findall(r"\d+", s)) or (999,)


def _get(url: str, accept: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": AGENT, "Accept": accept})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 2:
                raise
            time.sleep(60 * (attempt + 1))  # the API asks for a minute's wait, then fewer requests
    raise RuntimeError("unreachable")


def fetch(spec: dict) -> dict:
    """The match's finished games from its broadcast (and any other tours in
    its group, where Lichess files tiebreaks separately)."""
    a, b = spec["a"]["id"], spec["b"]["id"]
    first = json.loads(_get(f"{API}/{spec['lichess']}", "application/json"))
    tour_ids = [t["id"] for t in (first.get("group") or {}).get("tours", [])] or [spec["lichess"]]
    found, rounds, done = [], 0, []
    for tid in tour_ids:
        tour = first if tid == spec["lichess"] else json.loads(_get(f"{API}/{tid}", "application/json"))
        order = {r["id"]: rounds + i for i, r in enumerate(tour["rounds"])}
        rounds += len(tour["rounds"])
        fallback = FIDE_TC.get((tour["tour"].get("info") or {}).get("fideTC"), "classical")
        found += games(headers(_get(f"{API}/{tid}.pgn", "application/x-chess-pgn")), a, b, order, fallback)
        done.append(all(r.get("finished") for r in tour["rounds"]))
    # Every round marked finished: the match is over (it can also end early, at 7½;
    # matches.py sees that from the score).
    return {"source": "Lichess broadcast", "url": first["tour"]["url"], "over": bool(found) and all(done), "games": found}


def main(argv=None) -> int:
    for spec in MATCHES:
        if not spec.get("lichess"):
            continue
        out = fetch(spec)
        p = path(spec["year"])
        old = load(spec["year"])
        if old and old.get("over") and not out["over"]:
            out["over"] = True          # set by hand: keep it
        p.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        n = sum(g["f"] == "classical" for g in out["games"])
        print(f"{p}: {n} classical games, {len(out['games']) - n} tiebreak games"
              + (", match over" if out["over"] else ""), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
