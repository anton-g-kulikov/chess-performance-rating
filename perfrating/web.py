"""Render the lists as a single self-contained web page.

    python -m perfrating.web            # writes site/index.html

Reads the rolling lists (``results/``, ``data/games.json``) and every
calendar-year race that has been built (``results/YYYY/``,
``data/games-YYYY.json``).  The rolling lists and the newest year are embedded
in ``perfrating/page.html``; every older year is written to
``site/data/yYYYY.json`` and loaded by the page when someone opens it.

Every player in any pool also gets ``site/data/p/<FIDE id>.json``: their
results in each period and format, ranked or not, down to single games.  The
page shows it at ``/player/<FIDE id>``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from . import race
from .build import FORMATS, rated_games
from .performance import dp, performance, round_p
from .race import race_frames, rolling_frames

TEMPLATE = Path(__file__).with_name("page.html")


def event_summary(e: dict) -> list:
    rated = [(float(g["opponent_rating"]), float(g["result"]))
             for g in e["games"] if g["counted"] and g["opponent_rating"]]
    perf = performance(rated)
    return [e["period"][:7], e["name"], e["start"], e["end"], perf.games if perf else 0,
            perf.score if perf else 0, round(perf.avg_opp) if perf else None,
            perf.tpr if perf else None]


def name_key(name: str) -> tuple:
    """A name's words, ignoring case, punctuation and order: FIDE writes
    "Gukesh D" on the lists and "Gukesh, D" in rating calculations."""
    return tuple(sorted(name.lower().replace(",", " ").replace(".", " ").split()))


def event_games(e: dict, ids: dict) -> list:
    """Rated games of an event as [opponent, rating, result, capped, opponent's id or 0]."""
    return [[g["opponent"], g["opponent_rating"], g["result"], int(bool(g.get("capped"))),
             ids.get(name_key(g["opponent"]), 0)]
            for g in e["games"] if g["counted"] and g["opponent_rating"]]


def progress(events: list) -> list:
    """For each event (newest first, as listed): [player's rating going into
    it, TPR over all games up to and including it, games up to it]."""
    out, so_far = [], []
    for e in reversed(events):
        so_far += [g for g in rated_games([e])]
        perf = performance(so_far)
        out.append([int(e["ro"]) if e.get("ro") else None, perf.tpr if perf else None, len(so_far)])
    return out[::-1]


def player_entries(saved: dict, rows_by_fmt: dict, ids: dict) -> dict:
    """One period's results for every player in its pool, per format.

    Ranked players carry their row from the list; the others get the same
    numbers over the games they have, with ``rank`` None."""
    ranked = {fmt: {r["fide_id"]: r for r in rows} for fmt, rows in rows_by_fmt.items()}
    out = {}
    for fid, info in saved["players"].items():
        fid = int(fid)
        fmts = {}
        for fmt in FORMATS:
            events = sorted(info["games"].get(fmt, []),
                            key=lambda e: (e["start"] or "", e["period"]), reverse=True)
            if not events:
                continue
            r = ranked[fmt].get(fid)
            if r is None:
                perf = performance(rated_games(events))
                r = {"rank": None, "games": perf.games if perf else 0, "score": perf.score if perf else 0,
                     "pct": round(float(perf.p) * 100, 2) if perf else 0,
                     "avg_opp": round(perf.avg_opp) if perf else None, "tpr": perf.tpr if perf else None,
                     "true_perf": round(perf.true) if perf and perf.true is not None else None}
            fmts[fmt] = {
                "rank": r["rank"], "of": len(rows_by_fmt[fmt]), "rating": info["ratings"].get(fmt),
                **{k: r[k] for k in ("games", "score", "pct", "avg_opp", "tpr", "true_perf")},
                "ev": [event_summary(e) + [event_games(e, ids)] + p
                       for e, p in zip(events, progress(events))],
            }
        out[fid] = {"name": info["name"], "fed": info["fed"], "formats": fmts}
    return out


def mode_data(results: Path, data: Path, top: int, mode_id: str, label: str) -> dict:
    saved = json.loads(data.read_text())
    meta = json.loads((results / "meta.json").read_text())
    players = saved["players"]
    lists = {}
    full = {}
    for fmt in FORMATS:
        rows = full[fmt] = json.loads((results / f"{fmt}.json").read_text())
        lst = []
        for r in rows[:top]:
            events = sorted(players[str(r["fide_id"])]["games"][fmt],
                            key=lambda e: (e["start"] or "", e["period"]), reverse=True)
            won = [x for _, x in rated_games(events)]
            lst.append({**r, "dp": dp(round_p(r["score"], r["games"])),
                        # Wins, draws, losses: the page draws the score from them.
                        "wdl": [sum(x == 1 for x in won), sum(0 < x < 1 for x in won), sum(x == 0 for x in won)],
                        "ev": [event_summary(e) for e in events]})
        lists[fmt] = {"qualified": len(rows), "rows": lst}
        if meta.get("year"):
            lists[fmt]["race"] = race_frames(saved, fmt, round((meta.get("fraction") or 1) * 12),
                                             meta["min_games"][fmt])
        elif saved.get("history"):
            lists[fmt]["race"] = rolling_frames(saved, fmt, meta["min_games"][fmt])
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
    }, saved, full


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

    builds = [mode_data(Path("results"), Path("data/games.json"), args.top, "", "Last 12 months")]
    for d in sorted(Path("results").glob("[0-9][0-9][0-9][0-9]"), reverse=True):
        data = Path(f"data/games-{d.name}.json")
        if data.exists() and (d / "meta.json").exists():
            m = mode_data(d, data, args.top, f"y{d.name}", d.name)
            if (m[0]["fraction"] or 1) < 1:
                m[0]["label"] = f"{d.name} race"
            builds.append(m)
    modes = [m for m, _, _ in builds]

    # Everyone listed in any mode, so kept players and shared links can be
    # named before their year is loaded.
    people = {}
    for m in modes:
        for fmt in FORMATS:
            for r in m["lists"][fmt]["rows"]:
                people[r["fide_id"]] = [r["name"], r["fed"]]
    # Race leaders early in a year can be players who end up outside the top 100.
    for m, saved, _ in builds:
        for fmt in FORMATS:
            for f in m["lists"][fmt].get("race", []):
                for fid, *_ in f["rows"]:
                    if fid not in people:
                        p = saved["players"][str(fid)]
                        people[fid] = [p["name"], p["fed"]]

    # Player pages.  Opponents are linked by name when exactly one player in
    # any pool has it.
    names = {}
    for _, saved, _ in builds:
        for fid, info in saved["players"].items():
            names.setdefault(name_key(info["name"]), set()).add(int(fid))
    ids = {n: next(iter(s)) for n, s in names.items() if len(s) == 1}
    pages = {}
    for m, saved, full in builds:
        for fid, entry in player_entries(saved, full, ids).items():
            page = pages.setdefault(fid, {"id": fid, "name": entry["name"], "fed": entry["fed"], "modes": {}})
            page["modes"][m["id"]] = entry["formats"]
    players_dir = data_dir / "p"
    players_dir.mkdir(exist_ok=True)
    for old in players_dir.glob("*.json"):
        old.unlink()
    # One version for all player files: any rebuild that changes one changes it.
    ver = hashlib.sha1()
    for fid in sorted(pages):
        body = json.dumps(pages[fid], ensure_ascii=False, separators=(",", ":"))
        (players_dir / f"{fid}.json").write_text(body, encoding="utf-8")
        ver.update(body.encode())

    # The rolling lists and the newest year go in the page; older years are
    # separate files, fetched on demand.
    # The file's hash goes in its URL, so browsers holding an older copy
    # fetch the new one after a rebuild.
    for m in modes[2:]:
        body = json.dumps({"lists": m.pop("lists")}, ensure_ascii=False, separators=(",", ":"))
        (data_dir / f"{m['id']}.json").write_text(body, encoding="utf-8")
        m["src"] = f"/data/{m['id']}.json?v={hashlib.sha1(body.encode()).hexdigest()[:10]}"
    blob = json.dumps({"modes": modes, "people": people, "pver": ver.hexdigest()[:10]}, ensure_ascii=False,
                      separators=(",", ":")).replace("</", "<\\/")
    html = race.inline(TEMPLATE.read_text(encoding="utf-8")).replace("/*DATA*/null", blob)
    out.write_text(html, encoding="utf-8")
    lazy = sum(f.stat().st_size for f in data_dir.glob("y*.json"))
    print(f"wrote {out} ({len(html) // 1024} KB, modes: {', '.join(m['label'] for m in modes)})"
          + (f"; {len(modes) - 2} more in {data_dir}/ ({lazy // 1024} KB)" if len(modes) > 2 else "")
          + f"; {len(pages)} player pages ({sum(f.stat().st_size for f in players_dir.glob('*.json')) // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
