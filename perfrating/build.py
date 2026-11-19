"""Build performance rating lists from FIDE data.

Two modes:

* **Rolling** (default): every game rated in the last 12 FIDE rating periods.
  Each month the oldest period drops out and the newest comes in.
* **Year** (``--year 2026``): games from events that ended in that calendar
  year.  Everyone starts again from nothing on January 1.  While the year is
  in progress the minimum number of games scales with the share of the year
  covered so far.

Usage::

    python -m perfrating.build                # rolling: latest list, 12 periods
    python -m perfrating.build --end 2026-11 --months 12 --min-games 20,20,40
    python -m perfrating.build --year 2026    # calendar year, -> results/2026/
    python -m perfrating.build --year 2019    # a finished year (2013 onwards)

Steps:

1. Read FIDE's current open top-100 lists for classical, rapid and blitz;
   the player pool is the union of the three.
2. For every player, find which rating periods in the window contain games
   in each format, then download FIDE's game-by-game rating calculations for
   those periods.
   A finished year (before the current one) is built from FIDE's archived
   monthly lists instead (``archive.py``): the pool is everyone in an open
   top 100 at the start of each quarter of that year or in January of the
   next, and each list's ``Gms`` column says which months to download.
3. Pool every rated game per format and compute the performance rating
   (see ``performance.py``).  Players with fewer than the minimum number of
   games in a format are left out of that format's list.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .archive import ListArchive, pool_months
from .fide import FORMAT_ARRAYS, FORMAT_CODES, TOP_LISTS, FideClient
from .parsers import Player, Tournament, parse_calculation, parse_period_arrays, parse_top_list
from .performance import performance

FORMATS = list(FORMAT_CODES)
MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


def month_add(d: date, n: int) -> date:
    m = d.year * 12 + (d.month - 1) + n
    return date(m // 12, m % 12 + 1, 1)


def window(end: date, months: int) -> List[str]:
    return [month_add(end, -i).isoformat() for i in range(months)][::-1]


def latest_list_month(top_page: str) -> date:
    m = re.search(r"Top 100 Players (\w+) (\d{4})", top_page)
    if not m:
        raise RuntimeError("could not read the list month from the FIDE top list")
    return date(int(m.group(2)), MONTHS.index(m.group(1)) + 1, 1)


def event_year(e: dict) -> int:
    """Calendar year an event belongs to: the year it ended."""
    d = e.get("end") or e.get("start")
    if d:
        return int(d[:4])
    # No dates: FIDE usually rates an event in the list after it ends.
    return month_add(date.fromisoformat(e["period"]), -1).year


def year_periods(year: int, latest: date) -> List[str]:
    """FIDE lists that can hold games from ``year``.

    Games reach the list one or two months after the event ends, a few
    later still, so a finished year is read through April of the next.
    """
    end = min(date(year + 1, 4, 1), latest)
    first = date(year, 1, 1)
    n = (end.year - first.year) * 12 + end.month - first.month + 1
    if n < 1:
        raise SystemExit(f"no FIDE lists for {year} yet (latest is {latest:%Y-%m})")
    return window(end, n)


def year_fraction(year: int, periods: List[str]) -> float:
    """Share of ``year`` covered by the lists: games up to the month before
    the last list."""
    covered = month_add(date.fromisoformat(periods[-1]), -1)
    if covered.year > year:
        return 1.0
    if covered.year < year:
        return 0.0
    return covered.month / 12


def scaled_minimum(min_games: Dict[str, int], fraction: float) -> Dict[str, int]:
    return {f: max(1, math.ceil(n * fraction)) for f, n in min_games.items()}


def periods_with_games(client: FideClient, fide_id: int, periods: List[str],
                       exhaustive: bool) -> Dict[str, List[str]]:
    """Periods in ``periods`` worth fetching, per format.

    ``calculations.phtml`` lists the current calendar year's periods that have
    games for each format.  Those are used for periods in that year; earlier
    periods in the window are probed directly.
    """
    if exhaustive:
        return {fmt: list(periods) for fmt in FORMATS}
    end_year = periods[-1][:4]
    arrays = parse_period_arrays(client.calculations_page(fide_id, periods[-1]))
    out = {}
    for fmt in FORMATS:
        listed = set(arrays.get(FORMAT_ARRAYS[fmt], []))
        out[fmt] = [p for p in periods if p[:4] != end_year or p in listed]
    return out


class FideRefusing(RuntimeError):
    """FIDE keeps answering with empty pages where the lists say there are games."""


class Gaps:
    """Pages the list archive says have games but FIDE served empty.

    A long run of them in a row means FIDE has stopped serving us, so the
    build stops instead of grinding on and writing lists with holes."""

    def __init__(self, limit: int = 15) -> None:
        self.pages: List[Tuple[int, str, str]] = []
        self.streak = 0
        self.limit = limit

    def found(self) -> None:
        self.streak = 0

    def missed(self, fide_id: int, fmt: str, period: str) -> None:
        self.pages.append((fide_id, fmt, period))
        self.streak += 1
        if self.streak >= self.limit:
            raise FideRefusing(f"FIDE served {self.streak} empty pages in a row that should have games; "
                               "it is probably refusing requests for now. Try again later: pages already "
                               "fetched are cached.")


def fetch_tournaments(client: FideClient, fide_id: int, period: str, fmt: str,
                      expect_games: bool) -> List[Tournament]:
    tournaments = parse_calculation(client.calculation(fide_id, period, fmt))
    # FIDE answers with empty pages when it is busy.  Ask again, a few times
    # when the period is known to have games and once otherwise, waiting a
    # little longer before each new attempt.
    tries = 3 if expect_games else 1
    pause = 2.0
    while tries and not any(t.games for t in tournaments):
        tries -= 1
        time.sleep(pause)
        pause *= 3
        tournaments = parse_calculation(client.calculation(fide_id, period, fmt, refresh=True))
    return tournaments


def event_rows(tournaments: List[Tournament], period: str) -> List[dict]:
    rows = []
    for t in tournaments:
        if t.games:
            d = asdict(t)
            d["period"] = period
            rows.append(d)
    return rows


def collect_player(client: FideClient, player: Player, periods: List[str],
                   exhaustive: bool, known: Optional[Dict[str, List[str]]] = None,
                   gaps: Optional[Gaps] = None) -> Dict[str, List[dict]]:
    """Events with games for one player.  ``known`` gives the periods with
    games per format (from the list archive); otherwise they are looked up.
    Known periods that come back empty are recorded in ``gaps``."""
    todo = known if known is not None else periods_with_games(client, player.fide_id, periods, exhaustive)
    end_year = periods[-1][:4]
    result: Dict[str, List[dict]] = {}
    for fmt in FORMATS:
        events = []
        for period in todo[fmt]:
            expect = known is not None or (not exhaustive and period[:4] == end_year)
            rows = event_rows(fetch_tournaments(client, player.fide_id, period, fmt, expect), period)
            if gaps is not None and known is not None:
                if rows:
                    gaps.found()
                else:
                    gaps.missed(player.fide_id, fmt, period)
            events.extend(rows)
        result[fmt] = events
    return result


def rated_games(events: List[dict]):
    for e in events:
        for g in e["games"]:
            if g["counted"] and g["opponent_rating"]:
                yield float(g["opponent_rating"]), float(g["result"])


def build_rows(pool: Dict[int, dict], games: Dict[int, dict], fmt: str,
               min_games: int) -> List[dict]:
    rows = []
    for fid, info in pool.items():
        perf = performance(rated_games(games[fid][fmt]))
        if not perf or perf.games < min_games:
            continue
        rating = info["ratings"].get(fmt)
        rows.append({
            "fide_id": fid,
            "name": info["name"],
            "fed": info["fed"],
            "rating": rating,
            "games": perf.games,
            "score": perf.score,
            "pct": float(perf.p) * 100,
            "avg_opp": round(perf.avg_opp),
            "tpr": perf.tpr,
            "true_perf": round(perf.true) if perf.true is not None else None,
            "events": len(games[fid][fmt]),
        })
    rows.sort(key=lambda r: (-r["tpr"], -(r["true_perf"] or 0), -r["games"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


def fmt_score(x: float) -> str:
    return f"{x:g}"


def write_outputs(out_dir: Path, rows_by_fmt: Dict[str, List[dict]], scope: str,
                  min_games: Dict[str, int], pool_note: str, rating_note: str, top: int,
                  title: str = "Performance rating lists") -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    cols = ["rank", "name", "fed", "fide_id", "tpr", "true_perf", "games", "score",
            "pct", "avg_opp", "rating", "events"]
    for fmt, rows in rows_by_fmt.items():
        with open(out_dir / f"{fmt}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for r in rows:
                w.writerow({k: r[k] for k in cols})
        (out_dir / f"{fmt}.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False) + "\n")

    lines = [
        f"# {title}",
        "",
        f"{scope} Player pool: {pool_note}.",
        "",
        "**TPR** is the FIDE performance rating over all rated games in the window "
        "(average opponent + dp from the FIDE table). **True** is the rating whose "
        "expected score against the actual opponents equals the actual score. "
        f"**FIDE** is the player's {rating_note}; **Δ** is TPR minus it.",
        "",
    ]
    for fmt, rows in rows_by_fmt.items():
        lines += [
            f"## {fmt.capitalize()}",
            "",
            f"Minimum {min_games[fmt]} games. {len(rows)} players qualify"
            + (f"; top {top} shown, full list in [`{fmt}.csv`]({fmt}.csv)." if len(rows) > top else "."),
            "",
            "| # | Player | Fed | TPR | True | Games | Score | Avg opp | FIDE | Δ |",
            "|--:|:--|:--|--:|--:|--:|--:|--:|--:|--:|",
        ]
        for r in rows[:top]:
            delta = f"{r['tpr'] - r['rating']:+d}" if r["rating"] else ""
            true = r["true_perf"] if r["true_perf"] is not None else "—"
            lines.append(
                f"| {r['rank']} | {r['name']} | {r['fed']} | **{r['tpr']}** | {true} | {r['games']} | "
                f"{fmt_score(r['score'])} ({r['pct']:.0f}%) | {r['avg_opp']} | {r['rating'] or ''} | {delta} |"
            )
        lines.append("")
    (out_dir / "README.md").write_text("\n".join(lines))


def period_span(periods: List[str]) -> str:
    first, last = date.fromisoformat(periods[0]), date.fromisoformat(periods[-1])
    return f"{MONTHS[first.month-1]} {first.year} – {MONTHS[last.month-1]} {last.year}"


def describe(meta: dict) -> Dict[str, str]:
    """Headline and scope sentence for a saved build."""
    periods = meta["periods"]
    if meta.get("year"):
        y = meta["year"]
        covered = month_add(date.fromisoformat(periods[-1]), -1)
        through = ("the full year" if covered.year > y
                   else f"events ending January – {MONTHS[covered.month-1]} {y}")
        return {
            "title": f"{y} performance race",
            "scope": f"Games from events that ended in **{y}** ({through}), read from the "
                     f"{period_span(periods)} FIDE lists. Everyone starts again on January 1.",
        }
    return {
        "title": "Performance rating lists",
        "scope": f"Rating periods: **{period_span(periods)}** FIDE lists ({len(periods)} periods).",
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, help="calendar-year mode for this year")
    ap.add_argument("--end", help="rolling mode: last rating period, YYYY-MM (default: FIDE's latest list)")
    ap.add_argument("--months", type=int, default=12, help="rolling mode: number of rating periods (default 12)")
    ap.add_argument("--min-games", default="20,20,40",
                    help="minimum games for classical,rapid,blitz over a full year (default 20,20,40)")
    ap.add_argument("--top", type=int, default=100, help="rows per list in the Markdown summary")
    ap.add_argument("--pause", type=lambda v: tuple(float(x) for x in v.split("-")) * (1 if "-" in v else 2),
                    default=(6.0, 12.0), metavar="MIN-MAX",
                    help="seconds between the starts of two FIDE requests, picked at random in this "
                         "range; after every 40-80 requests a 1-2 minute rest. FIDE blocks clients "
                         "that ask for game pages much faster (default 6-12)")
    ap.add_argument("--workers", type=int, default=1,
                    help="parallel requests; FIDE serves one at a time fastest (default 1)")
    ap.add_argument("--exhaustive", action="store_true",
                    help="fetch every period instead of using FIDE's list of periods with games")
    ap.add_argument("--cache", default=".cache/fide", help="cache directory ('' to disable)")
    ap.add_argument("--out", help="output directory (default results/, or results/YEAR/)")
    ap.add_argument("--data", help="raw games file (default data/games.json, or data/games-YEAR.json)")
    ap.add_argument("--from-data", action="store_true",
                    help="rebuild the lists from --data without fetching anything")
    args = ap.parse_args(argv)
    args.out = args.out or (f"results/{args.year}" if args.year else "results")
    args.data = args.data or (f"data/games-{args.year}.json" if args.year else "data/games.json")
    base_min = dict(zip(FORMATS, (int(x) for x in args.min_games.split(","))))

    if args.from_data:
        saved = json.loads(Path(args.data).read_text())
        pool = {int(fid): {k: v for k, v in info.items() if k != "games"}
                for fid, info in saved["players"].items()}
        games = {int(fid): info["games"] for fid, info in saved["players"].items()}
        meta = {k: saved[k] for k in ("periods", "year", "pool_note", "rating_note") if k in saved}
        meta.setdefault("pool_note", current_pool_note(len(pool)))
        meta.setdefault("rating_note", CURRENT_RATING_NOTE)
    else:
        pool, games, meta = fetch(args)

    if meta.get("year"):
        meta["fraction"] = year_fraction(meta["year"], meta["periods"])
        meta["min_games"] = scaled_minimum(base_min, meta["fraction"])
    else:
        meta["min_games"] = base_min
    meta.update(describe(meta))

    if args.data and not args.from_data:
        Path(args.data).parent.mkdir(parents=True, exist_ok=True)
        Path(args.data).write_text(json.dumps({
            **meta,
            "players": {str(fid): {**pool[fid], "games": games[fid]} for fid in pool},
        }, ensure_ascii=False, separators=(",", ":")))

    rows_by_fmt = {fmt: build_rows(pool, games, fmt, meta["min_games"][fmt]) for fmt in FORMATS}
    write_outputs(Path(args.out), rows_by_fmt, meta["scope"], meta["min_games"], meta["pool_note"],
                  meta["rating_note"], args.top, meta["title"])
    (Path(args.out) / "meta.json").write_text(json.dumps(
        {k: meta[k] for k in ("title", "scope", "periods", "min_games", "year", "fraction",
                              "pool_note", "rating_note") if k in meta},
        indent=1, ensure_ascii=False) + "\n")
    for fmt, rows in rows_by_fmt.items():
        print(f"{fmt}: {len(rows)} qualify (min {meta['min_games'][fmt]}); leader: "
              + (f"{rows[0]['name']} {rows[0]['tpr']}" if rows else "-"), file=sys.stderr)
    return 0


def fetch(args):
    client = FideClient(cache_dir=Path(args.cache) if args.cache else None, min_interval=args.pause[0], max_interval=args.pause[1],
                        breaks=(40, 80), break_length=(60.0, 120.0))
    top_pages = {fmt: client.get("/a_top.php", {"list": TOP_LISTS[fmt]}, refresh=True)
                 for fmt in FORMATS}
    latest = latest_list_month(top_pages["classical"])
    if args.year:
        periods = year_periods(args.year, latest)
    else:
        end = date.fromisoformat(args.end + "-01") if args.end else latest
        periods = window(end, args.months)

    past = bool(args.year) and args.year < latest.year
    known: Dict[int, Dict[str, List[str]]] = {}
    if past:
        pool, known = archive_pool(args.year, periods)
        notes = {"pool_note": past_pool_note(len(pool), args.year),
                 "rating_note": f"rating on the January {args.year} list"}
    else:
        pool = {}
        for fmt, page in top_pages.items():
            for p in parse_top_list(page):
                entry = pool.setdefault(p.fide_id, {"name": p.name, "fed": p.fed, "ratings": {}})
                entry["ratings"][fmt] = p.rating
        notes = {"pool_note": current_pool_note(len(pool)), "rating_note": CURRENT_RATING_NOTE}
    print(f"pool: {len(pool)} players; periods {periods[0]} .. {periods[-1]}"
          + (f"; {sum(len(v) for k in known.values() for v in k.values())} player-months with games" if past else ""),
          file=sys.stderr)

    games: Dict[int, dict] = {}

    def job(fid: int):
        info = pool[fid]
        player = Player(fid, info["name"], info["fed"], 0)
        return fid, collect_player(client, player, periods, args.exhaustive,
                                   known.get(fid) if past else None, gaps)

    def in_year(events: List[dict]) -> List[dict]:
        return [e for e in events if event_year(e) == args.year] if args.year else events

    gaps = Gaps()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for i, (fid, data) in enumerate(ex.map(job, pool), 1):
            games[fid] = {f: in_year(evs) for f, evs in data.items()}
            if i % 10 == 0 or i == len(pool):
                print(f"  {i}/{len(pool)} players ({client.requests_made} requests)", file=sys.stderr)

    if gaps.pages:
        # A second go at the pages FIDE served empty, after the rest.
        print(f"  {len(gaps.pages)} pages came back empty; asking again", file=sys.stderr)
        still = []
        for fid, fmt, period in gaps.pages:
            time.sleep(5)
            rows = event_rows(fetch_tournaments(client, fid, period, fmt, True), period)
            if rows:
                games[fid][fmt].extend(in_year(rows))
            else:
                still.append(f"{pool[fid]['name']} {fmt} {period}")
        if still:
            raise FideRefusing(f"{len(still)} pages with games are still empty: " + "; ".join(still))

    # Ratings missing from the lists used: take the player's own rating from
    # an event in that format.  For the current lists that is the latest
    # event; for a past year, the first one, i.e. the rating going into it.
    pick = min if past else max
    for fid, info in pool.items():
        for fmt in FORMATS:
            if fmt not in info["ratings"] and games[fid][fmt]:
                ev = pick(games[fid][fmt], key=lambda e: (e["period"], e["end"] or ""))
                if ev.get("ro"):
                    info["ratings"][fmt] = int(ev["ro"])

    return pool, games, {"periods": periods, "year": args.year, **notes}


CURRENT_RATING_NOTE = "current FIDE rating"


def current_pool_note(n: int) -> str:
    return f"the {n} players on FIDE's current open top-100 classical, rapid and blitz lists"


def past_pool_note(n: int, year: int) -> str:
    return (f"the {n} players in FIDE's open top 100 for classical, rapid or blitz on the "
            f"January, April, July or October {year} list, or the January {year + 1} list")


def archive_pool(year: int, periods: List[str]):
    """Pool, ratings and months with games for a finished year, from FIDE's
    archived monthly lists."""
    archive = ListArchive()
    pool: Dict[int, dict] = {}
    for month in pool_months(year):
        for fmt in FORMATS:
            for r in archive.top(fmt, month):
                # Later lists overwrite the name and federation: the latest spelling wins.
                pool.setdefault(r.fide_id, {"ratings": {}}).update(name=r.name, fed=r.fed)
    jan = date(year, 1, 1)
    for fmt in FORMATS:
        for fid, r in archive.by_id(fmt, jan, pool).items():
            pool[fid]["ratings"][fmt] = r.rating
    known: Dict[int, Dict[str, List[str]]] = {fid: {f: [] for f in FORMATS} for fid in pool}
    for period in periods:
        for fmt in FORMATS:
            for fid, r in archive.by_id(fmt, date.fromisoformat(period), pool).items():
                if r.gms:
                    known[fid][fmt].append(period)
    print(f"list archive: {archive.downloaded} lists downloaded", file=sys.stderr)
    return pool, known


if __name__ == "__main__":
    raise SystemExit(main())
