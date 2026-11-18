"""FIDE's archived monthly rating lists, used to build past years.

FIDE publishes every monthly list as a zipped fixed-width text file, for
example ``standard_jan16frl.zip``.  The archive starts with January 2013.
Its columns move over the years (``FOA`` appears later), so they are read by
the positions of the header labels rather than fixed offsets.

A past year needs two things from these lists:

* its player pool: the open top 100s at points through the year;
* which months each player has games in (the ``Gms`` column), so only those
  months' game-by-game calculations are downloaded.

Each list is boiled down to the players rated 2200 or more and kept as a
small JSON summary; the zip itself is deleted.
"""

from __future__ import annotations

import json
import re
import time
import urllib.request
import zipfile
from datetime import date
from pathlib import Path
from typing import Dict, Iterable, List, NamedTuple

URL = "https://ratings.fide.com/download/{name}.zip"
KINDS = {"classical": "standard", "rapid": "rapid", "blitz": "blitz"}
MON = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
FIRST_ARCHIVED = date(2013, 1, 1)
KEEP_FROM = 2200  # summaries keep players rated at least this


class Rated(NamedTuple):
    fide_id: int
    name: str
    fed: str
    rating: int
    gms: int
    active: bool


def _columns(header: str) -> Dict[str, slice]:
    """Column slices from a header line, keyed by lower-case label.

    The rating column is labelled with the list month (``jan13``, ``JAN25``);
    it is returned as ``rating``.
    """
    labels = [(m.start(), m.group()) for m in re.finditer(r"ID Number|\S+", header)]
    cols = {}
    for i, (start, label) in enumerate(labels):
        end = labels[i + 1][0] if i + 1 < len(labels) else None
        key = label.lower()
        if re.fullmatch(r"[a-z]{3}\d{2}", key):
            key = "rating"
        cols[key] = slice(start, end)
    return cols


def parse_list(text: str) -> List[Rated]:
    lines = text.splitlines()
    cols = _columns(lines[0])
    out = []
    for line in lines[1:]:
        rating = line[cols["rating"]].strip()
        fid = line[cols["id number"]].strip()
        if not rating.isdigit() or not fid.isdigit():
            continue
        gms = line[cols["gms"]].strip()
        flag = line[cols["flag"]].strip() if "flag" in cols else ""
        out.append(Rated(int(fid), line[cols["name"]].strip(), line[cols["fed"]].strip(),
                         int(rating), int(gms) if gms.isdigit() else 0, "i" not in flag))
    return out


def list_name(fmt: str, month: date) -> str:
    return f"{KINDS[fmt]}_{MON[month.month - 1]}{month.year % 100:02d}frl"


class ListArchive:
    def __init__(self, cache_dir: Path = Path(".cache/fide/lists")) -> None:
        self.cache_dir = cache_dir
        cache_dir.mkdir(parents=True, exist_ok=True)
        self._loaded: Dict[str, List[Rated]] = {}
        self.downloaded = 0

    def _download(self, name: str) -> bytes:
        req = urllib.request.Request(URL.format(name=name), headers={"User-Agent": "chess-performance-rating"})
        for attempt in range(5):
            try:
                with urllib.request.urlopen(req, timeout=180) as resp:
                    return resp.read()
            except OSError:
                if attempt == 4:
                    raise
                time.sleep(2 ** attempt)
        raise AssertionError

    def rated(self, fmt: str, month: date) -> List[Rated]:
        """Players rated ``KEEP_FROM`` or more on one list."""
        if month < FIRST_ARCHIVED:
            raise ValueError(f"FIDE's list archive starts in {FIRST_ARCHIVED:%B %Y}")
        name = list_name(fmt, month)
        if name not in self._loaded:
            summary = self.cache_dir / f"{name}.json"
            if not summary.exists():
                zpath = self.cache_dir / f"{name}.zip"
                if not zpath.exists():
                    zpath.with_suffix(".part").write_bytes(self._download(name))
                    zpath.with_suffix(".part").rename(zpath)
                    self.downloaded += 1
                with zipfile.ZipFile(zpath) as z:
                    text = z.read(z.namelist()[0]).decode("latin-1")
                rows = [r for r in parse_list(text) if r.rating >= KEEP_FROM]
                summary.write_text(json.dumps([list(r) for r in rows], ensure_ascii=False, separators=(",", ":")))
                zpath.unlink()
            self._loaded[name] = [Rated(*r) for r in json.loads(summary.read_text())]
        return self._loaded[name]

    def top(self, fmt: str, month: date, n: int = 100) -> List[Rated]:
        """The open top ``n`` of a list: active players of any sex by rating."""
        active = [r for r in self.rated(fmt, month) if r.active]
        return sorted(active, key=lambda r: -r.rating)[:n]

    def by_id(self, fmt: str, month: date, ids: Iterable[int]) -> Dict[int, Rated]:
        wanted = set(ids)
        return {r.fide_id: r for r in self.rated(fmt, month) if r.fide_id in wanted}


def pool_months(year: int) -> List[date]:
    """Lists whose top 100s make up a past year's pool: the start of each
    quarter of ``year`` and January of the next year."""
    return [date(year, m, 1) for m in (1, 4, 7, 10)] + [date(year + 1, 1, 1)]
