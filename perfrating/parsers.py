"""Parsers for the ratings.fide.com HTML used by the builder."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Dict, List, Optional


@dataclass
class Player:
    fide_id: int
    name: str
    fed: str
    rating: int


@dataclass
class Game:
    opponent: str
    opponent_rating: Optional[int]
    result: float
    counted: bool  # FIDE "n" column: 1 if the game was rated
    capped: bool = False  # rating shown with "*": FIDE's 400-point rule applied


@dataclass
class Tournament:
    name: str
    event_id: Optional[int]
    start: Optional[str]
    end: Optional[str]
    games: List[Game] = field(default_factory=list)
    # FIDE's own totals row for the event: average opponent (Rc), the
    # player's rating (Ro), score (w) and rated games (n).
    rc: Optional[float] = None
    ro: Optional[float] = None
    w: Optional[float] = None
    n: Optional[int] = None


_ROW = re.compile(r"<tr>(.*?)</tr>", re.S)
_PROFILE = re.compile(r"/profile/(\d+)>([^<]+)</a>")
_FED = re.compile(r"flag-wrapper\">\s*<img[^>]*>\s*([A-Z]{3})")
_RATING = re.compile(r"rating_column>\s*(\d+)")


def parse_top_list(page: str) -> List[Player]:
    """Players from an ``a_top.php?list=...`` fragment, in list order."""
    players = []
    for row in _ROW.findall(page):
        prof, rating = _PROFILE.search(row), _RATING.search(row)
        if not (prof and rating):
            continue
        fed = _FED.search(row)
        players.append(
            Player(
                fide_id=int(prof.group(1)),
                name=html.unescape(prof.group(2)).strip(),
                fed=fed.group(1) if fed else "",
                rating=int(rating.group(1)),
            )
        )
    return players


_ARRAY = re.compile(r"var (std|rapid|blitz)_array\s*=\s*\[([^\]]*)\]")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def parse_period_arrays(page: str) -> Dict[str, List[str]]:
    """Rating periods with games, per format, from ``calculations.phtml``.

    Returns ``{"std": [...], "rapid": [...], "blitz": [...]}``; a missing
    array means the page did not list that format at all.
    """
    return {kind: _DATE.findall(body) for kind, body in _ARRAY.findall(page)}


def _num(text: str) -> Optional[float]:
    text = text.replace("\xa0", " ").strip()
    try:
        return float(text)
    except ValueError:
        return None


class _CalcParser(HTMLParser):
    """Walks an ``a_indv_calculation.php`` fragment.

    The fragment holds one block per tournament: a ``<a class=head1>`` link
    with the event name, a line with two ``dates_span`` spans, then a
    ``calc_table`` whose game rows are ``<tr>`` elements with ``list4``
    cells: name, title, -, rating, fed, w, n, chg, K, K*chg.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tournaments: List[Tournament] = []
        self._in_head = False
        self._head_href = ""
        self._head_text: List[str] = []
        self._in_date = False
        self._date_text: List[str] = []
        self._row: Optional[List[str]] = None
        self._row_is_game = False
        self._cell: Optional[List[str]] = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class") or ""
        if tag == "a" and "head1" in cls.split():
            self._in_head, self._head_href, self._head_text = True, a.get("href", ""), []
        elif tag == "span" and "dates_span" in cls.split():
            self._in_date, self._date_text = True, []
        elif tag == "tr":
            self._row, self._row_is_game = [], False
        elif tag == "td" and self._row is not None:
            self._cell = []
            if "list4" in cls.split():
                self._row_is_game = True

    def handle_endtag(self, tag):
        if tag == "a" and self._in_head:
            self._in_head = False
            m = re.search(r"event=(\d+)", self._head_href)
            self.tournaments.append(
                Tournament(
                    name="".join(self._head_text).strip(),
                    event_id=int(m.group(1)) if m else None,
                    start=None,
                    end=None,
                )
            )
        elif tag == "span" and self._in_date:
            self._in_date = False
            if self.tournaments:
                t = self.tournaments[-1]
                d = "".join(self._date_text).strip() or None
                if t.start is None:
                    t.start = d
                elif t.end is None:
                    t.end = d
        elif tag == "td" and self._cell is not None and self._row is not None:
            self._row.append("".join(self._cell))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self._finish_row(self._row)
            self._row = None

    def handle_data(self, data):
        if self._in_head:
            self._head_text.append(data)
        if self._in_date:
            self._date_text.append(data)
        if self._cell is not None:
            self._cell.append(data)

    def _finish_row(self, cells: List[str]) -> None:
        if len(cells) < 10 or not self.tournaments:
            return
        t = self.tournaments[-1]
        if not self._row_is_game:
            rc, ro, w, n = _num(cells[0]), _num(cells[1]), _num(cells[5]), _num(cells[6])
            if None not in (rc, ro, w, n):
                t.rc, t.ro, t.w, t.n = rc, ro, w, int(n)
            return
        result = _num(cells[5])
        if result is None:
            return
        raw_rating = cells[3].replace("\xa0", " ")
        m = re.search(r"\d+", raw_rating)
        n = _num(cells[6])
        t.games.append(
            Game(
                opponent=cells[0].replace("\xa0", " ").strip(),
                opponent_rating=int(m.group(0)) if m else None,
                result=result,
                counted=bool(n),
                capped="*" in raw_rating,
            )
        )


def parse_calculation(page: str) -> List[Tournament]:
    """Tournaments and games from an ``a_indv_calculation.php`` fragment."""
    p = _CalcParser()
    p.feed(page)
    p.close()
    return p.tournaments
