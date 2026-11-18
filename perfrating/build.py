"""Build last-12-months performance rating lists from FIDE data.

Usage::

    python -m perfrating.build                # default: latest list, 12 periods
    python -m perfrating.build --end 2026-11 --months 12 --min-games 20,20,40

Steps:

1. Read FIDE's current open top-100 lists for classical, rapid and blitz;
   the player pool is the union of the three.
2. For every player, find which rating periods in the window contain games
   in each format, then download FIDE's game-by-game rating calculations for
   those periods.
3. Pool every rated game per format and compute the performance rating
   (see ``performance.py``).  Players with fewer than the minimum number of
   games in a format are left out of that format's list.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

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


def fetch_tournaments(client: FideClient, fide_id: int, period: str, fmt: str,
                      expect_games: bool) -> List[Tournament]:
    tournaments = parse_calculation(client.calculation(fide_id, period, fmt))
    # FIDE occasionally answers with an empty body.  Ask again: a few times
    # when the period is known to have games, once otherwise.
    tries = 3 if expect_games else 1
    while tries and not any(t.games for t in tournaments):
        tries -= 1
        tournaments = parse_calculation(client.calculation(fide_id, period, fmt, refresh=True))
    return tournaments


def collect_player(client: FideClient, player: Player, periods: List[str],
                   exhaustive: bool) -> Dict[str, List[dict]]:
    todo = periods_with_games(client, player.fide_id, periods, exhaustive)
    end_year = periods[-1][:4]
    result: Dict[str, List[dict]] = {}
    for fmt in FORMATS:
        events = []
        for period in todo[fmt]:
            expect = not exhaustive and period[:4] == end_year
            for t in fetch_tournaments(client, player.fide_id, period, fmt, expect):
                if t.games:
                    d = asdict(t)
                    d["period"] = period
                    events.append(d)
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


def write_outputs(out_dir: Path, rows_by_fmt: Dict[str, List[dict]], periods: List[str],
                  min_games: Dict[str, int], pool_size: int, top: int) -> None:
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

    first, last = date.fromisoformat(periods[0]), date.fromisoformat(periods[-1])
    span = f"{MONTHS[first.month-1]} {first.year} – {MONTHS[last.month-1]} {last.year}"
    lines = [
        "# Performance rating lists",
        "",
        f"Rating periods: **{span}** FIDE lists ({len(periods)} periods). "
        f"Player pool: the {pool_size} players on FIDE's current open top-100 "
        "classical, rapid and blitz lists.",
        "",
        "**TPR** is the FIDE performance rating over all rated games in the window "
        "(average opponent + dp from the FIDE table). **True** is the rating whose "
        "expected score against the actual opponents equals the actual score. "
        "**Δ** is TPR minus the player's current FIDE rating in that format.",
        "",
    ]
    for fmt, rows in rows_by_fmt.items():
        lines += [
            f"## {fmt.capitalize()}",
            "",
            f"Minimum {min_games[fmt]} games. {len(rows)} players qualify"
            + (f"; top {top} shown, full list in [`{fmt}.csv`]({fmt}.csv)." if len(rows) > top else "."),
            "",
            "| # | Player | Fed | TPR | True | Games | Score | Avg opp | Rating | Δ |",
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


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--end", help="last rating period, YYYY-MM (default: FIDE's latest list)")
    ap.add_argument("--months", type=int, default=12, help="number of rating periods (default 12)")
    ap.add_argument("--min-games", default="20,20,40",
                    help="minimum games for classical,rapid,blitz (default 20,20,40)")
    ap.add_argument("--top", type=int, default=100, help="rows per list in the Markdown summary")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--exhaustive", action="store_true",
                    help="fetch every period instead of using FIDE's list of periods with games")
    ap.add_argument("--cache", default=".cache/fide", help="cache directory ('' to disable)")
    ap.add_argument("--out", default="results")
    ap.add_argument("--data", default="data/games.json", help="where to save the raw games")
    ap.add_argument("--from-data", action="store_true",
                    help="rebuild the lists from --data without fetching anything")
    args = ap.parse_args(argv)
    min_games = dict(zip(FORMATS, (int(x) for x in args.min_games.split(","))))

    if args.from_data:
        saved = json.loads(Path(args.data).read_text())
        periods = saved["periods"]
        pool = {int(fid): {k: v for k, v in info.items() if k != "games"}
                for fid, info in saved["players"].items()}
        games = {int(fid): info["games"] for fid, info in saved["players"].items()}
        finish(pool, games, periods, min_games, args)
        return 0

    client = FideClient(cache_dir=Path(args.cache) if args.cache else None)

    top_pages = {fmt: client.get("/a_top.php", {"list": TOP_LISTS[fmt]}, refresh=True)
                 for fmt in FORMATS}
    end = (date.fromisoformat(args.end + "-01") if args.end
           else latest_list_month(top_pages["classical"]))
    periods = window(end, args.months)

    pool: Dict[int, dict] = {}
    for fmt, page in top_pages.items():
        for p in parse_top_list(page):
            entry = pool.setdefault(p.fide_id, {"name": p.name, "fed": p.fed, "ratings": {}})
            entry["ratings"][fmt] = p.rating
    print(f"pool: {len(pool)} players; periods {periods[0]} .. {periods[-1]}", file=sys.stderr)

    games: Dict[int, dict] = {}

    def job(fid: int):
        info = pool[fid]
        player = Player(fid, info["name"], info["fed"], 0)
        return fid, collect_player(client, player, periods, args.exhaustive)

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for i, (fid, data) in enumerate(ex.map(job, pool), 1):
            games[fid] = data
            if i % 10 == 0 or i == len(pool):
                print(f"  {i}/{len(pool)} players ({client.requests_made} requests)", file=sys.stderr)

    # Ratings for formats where the player is outside the top 100: take the
    # player's own rating from the latest event in that format, if any.
    for fid, info in pool.items():
        for fmt in FORMATS:
            if fmt not in info["ratings"] and games[fid][fmt]:
                latest = max(games[fid][fmt], key=lambda e: (e["period"], e["end"] or ""))
                if latest.get("ro"):
                    info["ratings"][fmt] = int(latest["ro"])

    if args.data:
        Path(args.data).parent.mkdir(parents=True, exist_ok=True)
        Path(args.data).write_text(json.dumps({
            "periods": periods,
            "players": {str(fid): {**pool[fid], "games": games[fid]} for fid in pool},
        }, ensure_ascii=False, separators=(",", ":")))

    finish(pool, games, periods, min_games, args)
    return 0


def finish(pool, games, periods, min_games, args) -> None:
    rows_by_fmt = {fmt: build_rows(pool, games, fmt, min_games[fmt]) for fmt in FORMATS}
    write_outputs(Path(args.out), rows_by_fmt, periods, min_games, len(pool), args.top)
    for fmt, rows in rows_by_fmt.items():
        print(f"{fmt}: {len(rows)} qualify; leader: "
              + (f"{rows[0]['name']} {rows[0]['tpr']}" if rows else "-"), file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
