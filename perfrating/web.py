"""Render the lists as a single self-contained web page.

    python -m perfrating.web            # writes site/index.html

Reads ``results/{format}.json`` and ``data/games.json`` (written by
``perfrating.build``) and embeds the top rows of each list, with each
player's events, into ``perfrating/page.html``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .build import FORMATS, MONTHS
from .performance import performance

TEMPLATE = Path(__file__).with_name("page.html")


def event_summary(e: dict) -> list:
    rated = [(float(g["opponent_rating"]), float(g["result"]))
             for g in e["games"] if g["counted"] and g["opponent_rating"]]
    perf = performance(rated)
    return [e["period"][:7], e["name"], e["start"], e["end"], perf.games if perf else 0,
            perf.score if perf else 0, round(perf.avg_opp) if perf else None,
            perf.tpr if perf else None]


def page_data(results: Path, data: Path, top: int) -> dict:
    saved = json.loads(data.read_text())
    players = saved["players"]
    out = {"periods": saved["periods"], "pool": len(players), "lists": {}}
    for fmt in FORMATS:
        rows = json.loads((results / f"{fmt}.json").read_text())
        qualified = len(rows)
        lst = []
        for r in rows[:top]:
            events = sorted(players[str(r["fide_id"])]["games"][fmt],
                            key=lambda e: (e["start"] or "", e["period"]), reverse=True)
            lst.append({**r, "ev": [event_summary(e) for e in events]})
        out["lists"][fmt] = {"qualified": qualified, "rows": lst}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", default="results")
    ap.add_argument("--data", default="data/games.json")
    ap.add_argument("--top", type=int, default=100)
    ap.add_argument("--min-games", default="20,20,40")
    ap.add_argument("--out", default="site/index.html")
    args = ap.parse_args(argv)

    d = page_data(Path(args.results), Path(args.data), args.top)
    d["min"] = dict(zip(FORMATS, (int(x) for x in args.min_games.split(","))))
    first, last = d["periods"][0], d["periods"][-1]
    d["span"] = (f"{MONTHS[int(first[5:7]) - 1]} {first[:4]} – "
                 f"{MONTHS[int(last[5:7]) - 1]} {last[:4]}")
    blob = json.dumps(d, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8").replace("/*DATA*/null", blob)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out} ({len(html) // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
