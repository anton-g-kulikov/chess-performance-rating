"""World Championship matches: a page for each, and a line for each on the main page.

A match is a few facts kept by hand (``MATCHES``).  Everything else comes from
the two players' games in the saved data:

* whether it has been played: the match year holds a classical event in which
  one of the two met only the other (tiebreaks are the rapid and blitz events
  between them after it);
* for a played match, how the two stood going into it: every classical game in
  events that ended in the 12 months before the first game, the match itself
  not counted.

A match still to come is compared on the rolling lists, which the page reads
from the players' own files.
"""

from __future__ import annotations

from datetime import date

from .names import parts
from .performance import performance

# The champion (or, with the title vacant, the Candidates winner) first.  Names
# come from FIDE's, shown as perfrating/names.py shows them everywhere.  A match
# still to come can carry the date of its first game; a played one has its dates
# in the data.
MATCHES = [
    {"year": 2026, "place": "Geneva", "games": 14, "first_game": "2026-11-24",
     "a": {"id": 46616543, "role": "World champion"}, "b": {"id": 14205483, "role": "Challenger"}},
    {"year": 2024, "place": "Singapore", "games": 14,
     "a": {"id": 8603677, "role": "World champion"}, "b": {"id": 46616543, "role": "Challenger"}},
    {"year": 2023, "place": "Astana", "games": 14,
     "a": {"id": 4168119, "role": "Candidates winner"}, "b": {"id": 8603677, "role": "Candidates runner-up"}},
    {"year": 2021, "place": "Dubai", "games": 14,
     "a": {"id": 1503014, "role": "World champion"}, "b": {"id": 4168119, "role": "Challenger"}},
]


def slug(year: int) -> str:
    return f"world-championship-{year}"


def href(year: int) -> str:
    return f"/event/{slug(year)}"


def opponent_id(g: dict, e: dict, ids: dict):
    """The pool player a game was against, as the player pages link it."""
    from .web import name_key
    key = name_key(g["opponent"])
    return ids.get(key) or ids.get((e.get("event_id"), key))


def counted(e: dict) -> list:
    return [g for g in e["games"] if g["counted"] and g["opponent_rating"]]


def _versus(saved: dict, fid: int, other: int, fmt: str, ids: dict) -> dict:
    """``event id -> event`` for the events in which ``fid`` met only ``other``."""
    info = saved["players"].get(str(fid))
    out = {}
    for e in (info or {}).get("games", {}).get(fmt, []):
        games = counted(e)
        if games and all(opponent_id(g, e, ids) == other for g in games):
            out[e["event_id"]] = e
    return out


def _pairings(saved: dict, a: int, b: int, fmt: str, ids: dict) -> list:
    """The events between the two in one format, oldest first, each with both
    sides' copies where the data has them and the results from ``a``'s side."""
    ea, eb = _versus(saved, a, b, fmt, ids), _versus(saved, b, a, fmt, ids)
    out = []
    for eid in set(ea) | set(eb):
        own, their = ea.get(eid), eb.get(eid)
        e = own or their
        res = [float(g["result"]) for g in counted(own)] if own else [1 - float(g["result"]) for g in counted(their)]
        out.append({"f": fmt, "start": e["start"], "end": e["end"] or e["start"], "res": res, "a": own, "b": their})
    return sorted(out, key=lambda x: x["start"] or "")


def _side(own, their):
    """One player's rating going in and TPR in the match, from their own copy
    of the event, or else from what the other side's copy records."""
    if own:
        perf = performance((float(g["opponent_rating"]), float(g["result"])) for g in counted(own))
        return (int(own["ro"]) if own.get("ro") else None), (perf.tpr if perf else None)
    games = counted(their)
    rating = int(games[0]["opponent_rating"]) if games else None
    perf = performance((float(their["ro"]), 1 - float(g["result"])) for g in games) if their.get("ro") else None
    return rating, (perf.tpr if perf else None)


def played(saved: dict, a: int, b: int, ids: dict):
    """The match as played, or None if the year's data doesn't hold it yet."""
    found = _pairings(saved, a, b, "classical", ids)
    if not found:
        return None
    m = found[0]
    tb = [t for f in ("rapid", "blitz") for t in _pairings(saved, a, b, f, ids) if (t["start"] or "") >= m["end"]]
    tb.sort(key=lambda t: t["start"] or "")
    sa, tsa = sum(m["res"]), sum(r for t in tb for r in t["res"])
    sb, tsb = len(m["res"]) - sa, sum(len(t["res"]) for t in tb) - tsa
    win = ("a" if sa > sb else "b") if sa != sb else ("a" if tsa > tsb else "b") if tsa != tsb else None
    (ra, ta), (rb, tb_) = _side(m["a"], m["b"]), _side(m["b"], m["a"])
    return {"start": m["start"], "end": m["end"], "res": m["res"],
            "tb": [{"f": t["f"], "start": t["start"], "end": t["end"], "res": t["res"]} for t in tb],
            "a": sa, "b": sb, "tsa": tsa, "tsb": tsb, "win": win,
            "rating": {"a": ra, "b": rb}, "tpr": {"a": ta, "b": tb_}}


def window_start(first_game: str) -> str:
    d = date.fromisoformat(first_game)
    try:
        return d.replace(year=d.year - 1).isoformat()
    except ValueError:  # 29 February
        return d.replace(year=d.year - 1, day=28).isoformat()


def before(saveds: list, fid: int, start: str, fmt: str = "classical"):
    """A player's numbers over the events that ended in the 12 months before ``start``."""
    lo, seen, games = window_start(start), set(), []
    for saved in saveds:
        for e in saved["players"].get(str(fid), {}).get("games", {}).get(fmt, []):
            end = e["end"] or e["start"] or ""
            if e["event_id"] in seen or not (lo <= end < start):
                continue
            seen.add(e["event_id"])
            games += [(float(g["opponent_rating"]), float(g["result"])) for g in counted(e)]
    perf = performance(games)
    if not perf:
        return None
    return {"tpr": perf.tpr, "games": perf.games, "score": perf.score, "pct": round(float(perf.p) * 100, 2),
            "avg_opp": round(perf.avg_opp)}


def match_pages(builds: list, ids: dict, people: dict) -> list:
    """Everything each match page needs beyond the players' own files.

    ``builds`` is web.py's list of ``(mode, saved, full)``: the rolling lists
    first, then the years; ``people`` is ``FIDE id -> (name, federation)``."""
    by_year = {m["year"]: saved for m, saved, _ in builds if m["year"]}
    saveds = [saved for _, saved, _ in builds]
    rolling = builds[0][0]["periods"]
    lists = f"{_month(rolling[0])} – {_month(rolling[-1])}"
    out = []
    for spec in MATCHES:
        year, a, b = spec["year"], spec["a"]["id"], spec["b"]["id"]
        if a not in people or b not in people:
            continue
        named = lambda side: {**spec[side], "full": parts(*people[spec[side]["id"]])[0],
                              "short": parts(*people[spec[side]["id"]])[1]}
        m = {**spec, "slug": slug(year), "lists": lists, "a": named("a"), "b": named("b"),
             "played": played(by_year[year], a, b, ids) if year in by_year else None}
        if m["played"]:
            p = m["played"]
            m["window"] = {"from": window_start(p["start"]), "to": p["start"]}
            m["before"] = {}
            for side, fid in (("a", a), ("b", b)):
                nums = before(saveds, fid, p["start"])
                m["before"][side] = nums and {**nums, "rating": p["rating"][side]}
        out.append(m)
    return out


def _month(period: str) -> str:
    y, mo = period[:4], int(period[5:7])
    return f"{['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][mo - 1]} {y}"


def match_lines(modes: list, matches: list, pages: dict) -> dict:
    """The line on the main page for each period: ``mode id -> line``.

    It follows the period tabs: a year with a match shows it, the rolling list
    shows the newest match, a year without one shows nothing.  A match still
    to come is compared on the rolling lists, a played one on its own year."""
    by_year = {m["year"]: m for m in matches}
    newest = max(matches, key=lambda m: m["year"], default=None)
    out = {}
    for mode in modes:
        m = by_year.get(mode["year"]) if mode["year"] else newest
        if not m:
            continue
        on = f"y{m['year']}" if m["played"] else ""
        tpr = lambda side: (pages.get(m[side]["id"], {}).get("modes", {}).get(on, {})
                            .get("classical", {}).get("tpr"))
        out[mode["id"]] = {
            "href": href(m["year"]),
            "label": f"{m['year']} World Championship match" if m["played"] else "World Championship match",
            "a": [m["a"]["short"], tpr("a")], "b": [m["b"]["short"], tpr("b")],
            "note": f"classical TPR, {m['year']}" if m["played"] else "classical TPR, last 12 months",
        }
    return out

