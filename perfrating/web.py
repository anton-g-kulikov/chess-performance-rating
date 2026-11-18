"""Render the lists as a single self-contained web page.

    python -m perfrating.web            # writes site/index.html

Reads the rolling lists (``results/``, ``data/games.json``) and every
calendar-year race that has been built (``results/YYYY/``,
``data/games-YYYY.json``).  The rolling lists and the newest year are embedded
in ``perfrating/page.html``; every older year is written to
``site/data/yYYYY.json`` and loaded by the page when someone opens it.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .build import FORMATS
from .performance import dp, performance, round_p

TEMPLATE = Path(__file__).with_name("page.html")


def event_summary(e: dict) -> list:
    rated = [(float(g["opponent_rating"]), float(g["result"]))
             for g in e["games"] if g["counted"] and g["opponent_rating"]]
    perf = performance(rated)
    return [e["period"][:7], e["name"], e["start"], e["end"], perf.games if perf else 0,
            perf.score if perf else 0, round(perf.avg_opp) if perf else None,
            perf.tpr if perf else None]


def mode_data(results: Path, data: Path, top: int, mode_id: str, label: str) -> dict:
    saved = json.loads(data.read_text())
    meta = json.loads((results / "meta.json").read_text())
    players = saved["players"]
    lists = {}
    for fmt in FORMATS:
        rows = json.loads((results / f"{fmt}.json").read_text())
        lst = []
        for r in rows[:top]:
            events = sorted(players[str(r["fide_id"])]["games"][fmt],
                            key=lambda e: (e["start"] or "", e["period"]), reverse=True)
            lst.append({**r, "dp": dp(round_p(r["score"], r["games"])),
                        "ev": [event_summary(e) for e in events]})
        lists[fmt] = {"qualified": len(rows), "rows": lst}
    return {
        "id": mode_id,
        "label": label,
        "year": meta.get("year"),
        "fraction": meta.get("fraction"),
        "scope": meta["scope"].replace("**", ""),
        "periods": meta["periods"],
        "min": meta["min_games"],
        "pool": len(players),
        "pool_note": meta.get("pool_note") or f"the {len(players)} players on FIDE's current open top-100 classical, rapid and blitz lists",
        "rating_note": meta.get("rating_note") or "current FIDE rating",
        "lists": lists,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--top", type=int, default=100)
    ap.add_argument("--out", default="site/index.html")
    args = ap.parse_args(argv)

    out = Path(args.out)
    data_dir = out.parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    for old in data_dir.glob("y*.json"):
        old.unlink()

    modes = [mode_data(Path("results"), Path("data/games.json"), args.top, "", "Last 12 months")]
    for d in sorted(Path("results").glob("[0-9][0-9][0-9][0-9]"), reverse=True):
        data = Path(f"data/games-{d.name}.json")
        if data.exists() and (d / "meta.json").exists():
            m = mode_data(d, data, args.top, f"y{d.name}", d.name)
            if (m["fraction"] or 1) < 1:
                m["label"] = f"{d.name} race"
            modes.append(m)

    # Everyone listed in any mode, so kept players and shared links can be
    # named before their year is loaded.
    people = {}
    for m in modes:
        for fmt in FORMATS:
            for r in m["lists"][fmt]["rows"]:
                people[r["fide_id"]] = [r["name"], r["fed"]]

    # The rolling lists and the newest year go in the page; older years are
    # separate files, fetched on demand.
    for m in modes[2:]:
        (data_dir / f"{m['id']}.json").write_text(
            json.dumps({"lists": m.pop("lists")}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        m["src"] = f"data/{m['id']}.json"
    blob = json.dumps({"modes": modes, "people": people}, ensure_ascii=False,
                      separators=(",", ":")).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8").replace("/*DATA*/null", blob)
    out.write_text(html, encoding="utf-8")
    lazy = sum(f.stat().st_size for f in data_dir.glob("y*.json"))
    print(f"wrote {out} ({len(html) // 1024} KB, modes: {', '.join(m['label'] for m in modes)})"
          + (f"; {len(modes) - 2} more in {data_dir}/ ({lazy // 1024} KB)" if len(modes) > 2 else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
