"""Render the lists as a single self-contained web page.

    python -m perfrating.web            # writes site/index.html

Reads the rolling lists (``results/``, ``data/games.json``) and every
calendar-year race that has been built (``results/YYYY/``,
``data/games-YYYY.json``).  The rolling lists and the newest year are embedded
in ``perfrating/page.html``; every older year is written to
``site/data/yYYYY.json`` and loaded by the page when someone opens it.

Every player in any pool also gets a page at ``/player/<FIDE id>``, from
``site/data/p/<FIDE id>.json`` (their numbers in each period and format,
ranked or not) and one ``site/data/p/<FIDE id>/<period>-<hash>.json`` per
period with the events and games behind them, fetched when the period is
opened.  A period file's name changes only when its content does, so a new
year adds files without rewriting the old ones.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from itertools import permutations
from pathlib import Path
from statistics import median

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


# A longer or shorter spelling is taken for a pool player only when the ratings agree:
# the opponent's rating in those games is typically within this of the player's.
NAMESAKE_GAP = 60


def same_but_initials(a: tuple, b: tuple) -> bool:
    """The same words, a given name cut to its initial on either side:
    "Praggnanandhaa R" and "Rameshbabu, Praggnanandhaa"."""
    if len(a) != len(b) or a == b:
        return False
    for other in permutations(b):
        pairs = list(zip(a, other))
        if all(x == y or (len(x) == 1 and y.startswith(x)) or (len(y) == 1 and x.startswith(y))
               for x, y in pairs) and any(x == y and len(x) > 1 for x, y in pairs):
            return True
    return False


def one_within_other(a: tuple, b: tuple) -> bool:
    """One name is the other with words left out, and they share two full
    words: "Niemann, Hans" and "Niemann, Hans Moke"."""
    sa, sb = set(a), set(b)
    return (sa < sb or sb < sa) and sum(len(t) > 1 for t in sa & sb) >= 2


def opponent_ids(saveds: list) -> tuple:
    """Who an opponent is, by name: ``(spelling key -> FIDE id, id -> listed name)``.

    FIDE spells the same player differently from event to event.  A spelling
    is a pool player's when it is their listed name (in any word order), or
    when it differs from exactly one listed name only by initials or by words
    left out and the ratings agree.  The rating check keeps namesakes apart:
    "Flores Quillas, Diego Saul Rodri" is not "Flores, Diego"."""
    names, listed = {}, {}
    for saved in saveds:
        for fid, info in saved["players"].items():
            names.setdefault(name_key(info["name"]), set()).add(int(fid))
            listed.setdefault(int(fid), info["name"])
    exact = {k: next(iter(s)) for k, s in names.items() if len(s) == 1}
    # Every other spelling met as an opponent, with where and at what rating.
    met = {}
    for saved in saveds:
        for info in saved["players"].values():
            for fmt, events in info["games"].items():
                for e in events:
                    for g in e["games"]:
                        key = name_key(g["opponent"])
                        if key not in names and g["opponent_rating"]:
                            met.setdefault(key, []).append((saved, fmt, g["opponent_rating"]))
    ids = dict(exact)
    for key, where in met.items():
        fits = [fid for k, fid in exact.items() if same_but_initials(k, key)]
        if len(fits) != 1:
            fits = [fid for k, fid in exact.items() if one_within_other(k, key)]
        if len(fits) != 1:
            continue
        gaps = [abs(rating - player["ratings"][fmt]) for saved, fmt, rating in where
                for player in [saved["players"].get(str(fits[0]))]
                if player and player["ratings"].get(fmt)]
        if gaps and median(gaps) <= NAMESAKE_GAP:
            ids[key] = fits[0]
    return ids, listed


def event_games(e: dict, ids: dict, listed: dict) -> list:
    """Rated games of an event as [opponent, rating, result, capped, opponent's id or 0].
    An opponent who is a pool player goes by their listed name, however FIDE
    spelled them in this event."""
    out = []
    for g in e["games"]:
        if g["counted"] and g["opponent_rating"]:
            oid = ids.get(name_key(g["opponent"]), 0)
            out.append([listed.get(oid, g["opponent"]), g["opponent_rating"], g["result"],
                        int(bool(g.get("capped"))), oid])
    return out


def progress(events: list) -> list:
    """For each event (newest first, as listed): [player's rating going into
    it, TPR over all games up to and including it, games up to it]."""
    out, so_far = [], []
    for e in reversed(events):
        so_far += [g for g in rated_games([e])]
        perf = performance(so_far)
        out.append([int(e["ro"]) if e.get("ro") else None, perf.tpr if perf else None, len(so_far)])
    return out[::-1]


def player_entries(saved: dict, rows_by_fmt: dict, ids: dict, listed: dict = None) -> dict:
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
                "ev": [event_summary(e) + [event_games(e, ids, listed or {})] + p
                       for e, p in zip(events, progress(events))],
            }
        out[fid] = {"name": info["name"], "fed": info["fed"], "formats": fmts}
    return out


def split_page(page: dict) -> tuple:
    """A player's page as a small summary plus one file per period.

    Returns ``(summary, {file name: body})``.  The summary has every number but
    the events, and names each period's file; the name carries a hash of the
    file, so it can be cached for good and is untouched while the period is."""
    summary = {k: page[k] for k in ("id", "name", "fed")}
    summary["modes"], summary["files"], files = {}, {}, {}
    for mode_id, fmts in page["modes"].items():
        summary["modes"][mode_id] = {f: {k: v for k, v in e.items() if k != "ev"} for f, e in fmts.items()}
        body = json.dumps({f: e["ev"] for f, e in fmts.items()}, ensure_ascii=False, separators=(",", ":"))
        name = f"{mode_id or 'r12'}-{hashlib.sha1(body.encode()).hexdigest()[:10]}.json"
        summary["files"][mode_id] = name
        files[name] = body
    return summary, files


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

    # Player pages.  Opponents who are pool players are linked and named as listed.
    ids, listed = opponent_ids([saved for _, saved, _ in builds])
    pages = {}
    for m, saved, full in builds:
        for fid, entry in player_entries(saved, full, ids, listed).items():
            page = pages.setdefault(fid, {"id": fid, "name": entry["name"], "fed": entry["fed"], "modes": {}})
            page["modes"][m["id"]] = entry["formats"]
    players_dir = data_dir / "p"
    players_dir.mkdir(exist_ok=True)
    for old in players_dir.iterdir():
        shutil.rmtree(old) if old.is_dir() else old.unlink()
    # One version for all summaries: any rebuild that changes one changes it.
    # Period files are named by their hash and need none.
    ver = hashlib.sha1()
    for fid in sorted(pages):
        summary, files = split_page(pages[fid])
        body = json.dumps(summary, ensure_ascii=False, separators=(",", ":"))
        (players_dir / f"{fid}.json").write_text(body, encoding="utf-8")
        ver.update(body.encode())
        (players_dir / str(fid)).mkdir()
        for name, period in files.items():
            (players_dir / str(fid) / name).write_text(period, encoding="utf-8")

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
          + f"; {len(pages)} player pages ({sum(f.stat().st_size for f in players_dir.glob('*.json')) // 1024} KB"
          + f" + {sum(f.stat().st_size for f in players_dir.glob('*/*.json')) // 1024} KB by period)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
