"""Render the lists as a web page, and a page for every player.

    python -m perfrating.web            # writes site/index.html and what it loads

Reads the rolling lists (``results/``, ``data/games.json``) and every
calendar-year race that has been built (``results/YYYY/``,
``data/games-YYYY.json``).  ``perfrating/page.html`` is written out in three
parts: its markup as ``site/index.html``, its styles as ``site/app.css`` and
its script, with the rolling lists and the newest year in it, as
``site/app.js``.  Every older year is written to ``site/data/yYYYY.json`` and
loaded by the page when someone opens it.

Every player in any pool also gets a page at ``/player/<FIDE id>``:
``site/player/<FIDE id>/index.html``, the same markup with the player's own
title, summary, address and heading in it, so a link to it previews as the
player's and the page shows whose it is before the script runs.  The two
shared files keep their names from build to build (the server has browsers
check them on every visit), so a player's page is rewritten only when the
markup or the player's name changes.  The numbers come from
``site/data/p/<FIDE id>.json`` (each period and format, ranked or not) and one
``site/data/p/<FIDE id>/<period>-<hash>.json`` per period with the events and
games behind them, fetched when the period is opened.  A period file's name
changes only when its content does, so a new year adds files without
rewriting the old ones.

Each World Championship match in ``perfrating/matches.py`` gets a page at
``/event/world-championship-YYYY``, written to
``site/event/world-championship-YYYY/index.html`` from ``perfrating/match.html``
with the main page's styles; the main page shows a line linking to it.

For search engines, ``site/sitemap.xml`` lists the main page and every match
and player page (``site/robots.txt``, kept by hand, points to it).  Match and
player pages carry their own title, summary and address in their markup.

Visits are counted by Cloudflare Web Analytics, which sets no cookies: every
page ends with its script once ``CF_BEACON`` holds the site's token.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
from itertools import permutations
from pathlib import Path
from statistics import median

from . import race
from .build import FORMATS, rated_games
from .matches import href, match_lines, match_pages
from .names import exceptions, parts
from .performance import dp, performance, round_p
from .race import race_frames, rolling_frames

TEMPLATE = Path(__file__).with_name("page.html")
MATCH_TEMPLATE = Path(__file__).with_name("match.html")
SITE = "https://chesstpr.com"
SITE_NAME = "Chess Performance Ratings"
# The site's token in Cloudflare Web Analytics (public: it is in every page).
# Empty, the pages carry no analytics.
CF_BEACON = "abcadbe5c7f44541a4cd897c6dc7136d"


def with_analytics(page: str, token: str = None) -> str:
    """``page`` with the Cloudflare Web Analytics script where the template
    marks it.  The script counts a move between the lists and a player page
    as a visit too (it follows the address, not only page loads)."""
    token = CF_BEACON if token is None else token
    tag = ("<script type=\"module\" src=\"https://static.cloudflareinsights.com/beacon.min.js\" "
           f"data-cf-beacon='{json.dumps({'token': token})}'></script>\n") if token else ""
    return page.replace("<!--ANALYTICS-->\n", tag, 1)


def match_head(match: dict) -> tuple:
    """A match page's ``(title, tags)`` for search engines and link previews:
    its summary, its address, and the card shown when the link is shared."""
    a, b, year = match["a"], match["b"], match["year"]
    name = f"{a['short']} vs {b['short']}, World Championship {year}"
    where = f"FIDE World Championship Match {year}, {match['place']}."
    if match.get("played"):
        desc = f"{where} The match game by game, and how {a['full']} and {b['full']} had been playing in the year before it."
    else:
        desc = f"{where} How {a['full']} and {b['full']} have played over the last 12 months, in classical, rapid and blitz."
    url = SITE + href(year)
    e = lambda text: html.escape(text, quote=True)
    tags = [f'<meta name="description" content="{e(desc)}">',
            f'<link rel="canonical" href="{url}">',
            '<meta property="og:type" content="website">',
            f'<meta property="og:site_name" content="{SITE_NAME}">',
            f'<meta property="og:title" content="{e(name)}">',
            f'<meta property="og:description" content="{e(desc)}">',
            f'<meta property="og:url" content="{url}">',
            f'<meta property="og:image" content="{SITE}/og.png">',
            '<meta property="og:image:width" content="1200">',
            '<meta property="og:image:height" content="630">',
            '<meta name="twitter:card" content="summary_large_image">']
    return e(f"{name} · {SITE_NAME}"), "\n".join(tags)


def match_html(match: dict) -> str:
    """A match page: match.html dressed in the main page's stylesheet and SVG patterns."""
    page = TEMPLATE.read_text(encoding="utf-8")
    css = re.search(r"<style>(.*?)</style>", page, re.S).group(1).replace("/*RACE_CSS*/", "")
    defs = re.search(r'<svg class="defs".*?</svg>', page, re.S).group(0)
    blob = json.dumps(match, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    title, tags = match_head(match)
    return (with_analytics(MATCH_TEMPLATE.read_text(encoding="utf-8")).replace("/*TITLE*/", title, 1).replace("<!--HEAD-->", tags, 1)
            .replace("/*SITE_CSS*/", css, 1).replace("<!--SITE_DEFS-->", defs, 1).replace("/*MATCH*/null", blob, 1))


# A player page's summary, for search engines and link previews.  The page's
# script gets it too (``head`` in its data), for moving between players in place.
PLAYER_DESC = "{name}'s performance rating in classical, rapid and blitz, year by year. Every FIDE rated event and game behind it."

_HEAD = {"desc": r'(<meta name="description" content=")([^"]*)(">)',
         "ogTitle": r'(<meta property="og:title" content=")([^"]*)(">)',
         "ogDesc": r'(<meta property="og:description" content=")([^"]*)(">)',
         "ogUrl": r'(<meta property="og:url" content=")([^"]*)(">)',
         "title": r"(<title>)([^<]*)(</title>)"}


def _swap(page: str, pattern: str, value: str) -> str:
    """``page`` with the one place ``pattern`` matches set to ``value``."""
    out, n = re.subn(pattern, lambda m: m.group(1) + value + m.group(3), page)
    if n != 1:
        raise ValueError(f"expected one {pattern!r} in the page, found {n}")
    return out


def home_head(page: str) -> dict:
    """The main page's summary and card as its markup has them, and the
    player pages' summary: what the script needs to set them again."""
    read = lambda key: html.unescape(re.search(_HEAD[key], page).group(2))
    return {"desc": read("desc"), "ogTitle": read("ogTitle"), "ogDesc": read("ogDesc"), "player": PLAYER_DESC}


def shell_and_assets(page: str) -> tuple:
    """``(markup, styles, script)``: the page with its stylesheet and its
    script taken out into the files the markup then loads."""
    css = re.search(r"<style>\n?(.*?)</style>", page, re.S)
    js = re.search(r"<script>\n?(.*?)</script>", page, re.S)   # the page's own script: the one with no attributes
    shell = (page[:css.start()] + '<link rel="stylesheet" href="/app.css">'
             + page[css.end():js.start()] + '<script src="/app.js"></script>' + page[js.end():])
    return shell, css.group(1), js.group(1)


def player_html(shell: str, fid: int, name: str, fed: str) -> str:
    """A player's page: the main page's markup, already the player's.  Its head
    names the player, and its body opens on the player view with the heading
    filled in, as the script will set them (setPlayerHead in page.html)."""
    e = lambda text: html.escape(text, quote=True)
    who, url = parts(name, fed)[0], f"{SITE}/player/{fid}"
    desc = PLAYER_DESC.format(name=who)
    page = _swap(shell, _HEAD["title"], e(f"{who} · {SITE_NAME}"))
    page = _swap(page, _HEAD["desc"], e(desc) + f'">\n<link rel="canonical" href="{url}')
    page = _swap(page, _HEAD["ogTitle"], e(who))
    page = _swap(page, _HEAD["ogDesc"], e(desc))
    page = _swap(page, _HEAD["ogUrl"], url)
    page = _swap(page, r"(<body)()(>)", ' class="pview"')
    page = _swap(page, r'(<div class="eyebrow" id="p-eyebrow">)([^<]*)(</div>)',
                 e(" · ".join(x for x in (fed, f"FIDE ID {fid}") if x)))
    page = _swap(page, r'(<h1 id="p-name">)([^<]*)(</h1>)', e(who))
    return _swap(page, r'(<div class="plinks" id="p-links">)()(</div>)',
                 f'<a href="https://ratings.fide.com/profile/{fid}" target="_blank" rel="noopener">FIDE profile</a>')


def sitemap(paths: list) -> str:
    """sitemap.xml for the given paths.  No dates: the build has to come out
    the same from the same results, whenever it is run."""
    urls = "".join(f"  <url><loc>{SITE}{html.escape(path)}</loc></url>\n" for path in paths)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{urls}</urlset>\n'


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
    The first also holds ``(event id, spelling key)`` entries from event_pairings().

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
    ids.update(event_pairings(saveds, ids))
    return ids, listed


def event_pairings(saveds: list, ids: dict) -> dict:
    """Misspellings no name rule can catch, from the other side of the board:
    ``(event id, spelling key) -> FIDE id``, good for that event only.

    When two pool players are in the same event, each side's games record
    the other's rating.  A spelling in A's event is pool player B when none
    of A's games there is already B's, B's copy of the event has exactly as
    many games against A with the results the other way round, B's own
    rating in it is the rating A's games give, and A's own rating is the one
    B's games give.  So "Guskesh, D" in Ding's 2024 World Championship match
    is Gukesh.  (In a big open, someone else can share B's rating: that is
    why B must be missing from A's games.)"""
    by_event = {}
    for saved in saveds:
        for fid, info in saved["players"].items():
            for events in info["games"].values():
                for e in events:
                    if e.get("event_id") is not None:
                        by_event.setdefault(e["event_id"], {})[int(fid)] = e
    out = {}
    for eid, sides in by_event.items():
        for a, e in sides.items():
            unknown, linked = {}, set()
            for g in e["games"]:
                key = name_key(g["opponent"])
                if key in ids:
                    linked.add(ids[key])
                elif g["opponent_rating"]:
                    unknown.setdefault(key, []).append(g)
            for key, games in unknown.items():
                fits = []
                for b, f in sides.items():
                    back = [h for h in f["games"] if ids.get(name_key(h["opponent"])) == a]
                    if (b != a and b not in linked and len(back) == len(games)
                            and {g["opponent_rating"] for g in games} == {f.get("ro")}
                            and {h["opponent_rating"] for h in back} == {e.get("ro")}
                            and sum(g["result"] for g in games) + sum(h["result"] for h in back) == len(games)):
                        fits.append(b)
                if len(fits) == 1:
                    out[(eid, key)] = fits[0]
    return out


def event_games(e: dict, ids: dict, listed: dict) -> list:
    """Rated games of an event as [opponent, rating, result, capped, opponent's id or 0].
    An opponent who is a pool player goes by their listed name, however FIDE
    spelled them in this event."""
    out = []
    for g in e["games"]:
        if g["counted"] and g["opponent_rating"]:
            key = name_key(g["opponent"])
            oid = ids.get(key) or ids.get((e.get("event_id"), key), 0)
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

    # Names the page can't turn round by itself (perfrating/names.py).
    pool = {}
    for _, saved, _ in builds:
        for fid, info in saved["players"].items():
            pool.setdefault(int(fid), (info["name"], info["fed"]))
    names = exceptions(pool.values())

    # World Championship matches: a page each, and a line on the main page.
    matches = match_pages(builds, ids, pool)
    lines = match_lines(modes, matches, pages)
    events_dir = out.parent / "event"
    shutil.rmtree(events_dir, ignore_errors=True)
    for match in matches:
        (events_dir / match["slug"]).mkdir(parents=True)
        # pver: the players' summaries are cached for good, so their URL carries the build's version.
        page = match_html({**match, "pver": ver.hexdigest()[:10], "names": names})
        (events_dir / match["slug"] / "index.html").write_text(page, encoding="utf-8")

    # The rolling lists and the newest year go in the page; older years are
    # separate files, fetched on demand.
    # The file's hash goes in its URL, so browsers holding an older copy
    # fetch the new one after a rebuild.
    for m in modes[2:]:
        body = json.dumps({"lists": m.pop("lists")}, ensure_ascii=False, separators=(",", ":"))
        (data_dir / f"{m['id']}.json").write_text(body, encoding="utf-8")
        m["src"] = f"/data/{m['id']}.json?v={hashlib.sha1(body.encode()).hexdigest()[:10]}"
    shell, css, js = shell_and_assets(with_analytics(race.inline(TEMPLATE.read_text(encoding="utf-8"))))
    blob = json.dumps({"modes": modes, "people": people, "names": names, "matches": lines, "pver": ver.hexdigest()[:10],
                       "head": home_head(shell)}, ensure_ascii=False, separators=(",", ":"))
    js = js.replace("/*DATA*/null", blob)
    out.write_text(shell, encoding="utf-8")
    (out.parent / "app.css").write_text(css, encoding="utf-8")
    (out.parent / "app.js").write_text(js, encoding="utf-8")
    # Every player's own page.
    shutil.rmtree(out.parent / "player", ignore_errors=True)
    for fid in sorted(pages):
        (out.parent / "player" / str(fid)).mkdir(parents=True)
        (out.parent / "player" / str(fid) / "index.html").write_text(
            player_html(shell, fid, pages[fid]["name"], pages[fid]["fed"]), encoding="utf-8")
    (out.parent / "sitemap.xml").write_text(
        sitemap(["/"] + [href(m["year"]) for m in matches] + [f"/player/{fid}" for fid in sorted(pages)]), encoding="utf-8")
    lazy = sum(f.stat().st_size for f in data_dir.glob("y*.json"))
    print(f"wrote {out} ({len(shell) // 1024} KB, with app.css {len(css) // 1024} KB and app.js {len(js) // 1024} KB; modes: {', '.join(m['label'] for m in modes)})"
          + (f"; {len(modes) - 2} more in {data_dir}/ ({lazy // 1024} KB)" if len(modes) > 2 else "")
          + f"; {len(pages)} player pages ({sum(f.stat().st_size for f in players_dir.glob('*.json')) // 1024} KB"
          + f" + {sum(f.stat().st_size for f in players_dir.glob('*/*.json')) // 1024} KB by period)"
          + f"; {len(matches)} match pages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
