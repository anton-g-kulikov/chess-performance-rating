"""How a player's name is shown.

FIDE files names family name first: "Carlsen, Magnus".  Turned round that gives
"Magnus Carlsen", which is right for most players but not for all:

* Chinese, Vietnamese and Korean names are said family name first: "Ding, Liren"
  is Ding Liren, not Liren Ding.
* Some Indian players are filed with no comma, in the order they are known by:
  "Gukesh D", "Erigaisi Arjun" (who is Arjun Erigaisi).
* FIDE marks a namesake with a trailing letter: "Li, Chao b".

A name is shown four ways, ``[full, surname, given, short]``: "Magnus Carlsen",
"Carlsen" (the bold line in the table and the name on a phone), "Magnus" (the
line under it) and "Magnus Carlsen" (charts' labels: first given name and
surname).  The page turns a "Family, Given" name round itself (``plain``); the
build sends it only the names that come out differently (``exceptions``).
"""

from __future__ import annotations

# Federations whose players' names are said family name first.
FAMILY_FIRST = {"CHN", "TPE", "HKG", "MAC", "VIE", "KOR", "PRK", "MGL"}

# Names that no rule gets right: FIDE's name -> (full, surname, given).
KNOWN = {
    "Erigaisi Arjun": ("Arjun Erigaisi", "Erigaisi", "Arjun"),
    "Gukesh D": ("Gukesh D", "Gukesh", "D"),
    "Praggnanandhaa R": ("Praggnanandhaa R", "Praggnanandhaa", "R"),
    "Narayanan S L": ("Narayanan S L", "Narayanan", "S L"),
    "Nihal Sarin": ("Nihal Sarin", "Sarin", "Nihal"),
    "Aryan Chopra": ("Aryan Chopra", "Chopra", "Aryan"),
    "Pranesh M": ("Pranesh M", "Pranesh", "M"),
    "Vidit, Santosh Gujrathi": ("Vidit Gujrathi", "Vidit", "Santosh Gujrathi"),
    "Aravindh, Chithambaram VR.": ("Aravindh Chithambaram", "Aravindh", "Chithambaram VR."),
    # Family name first, playing for a federation that doesn't say so.
    "Nguyen, Thai Dai Van": ("Nguyen Thai Dai Van", "Nguyen", "Thai Dai Van"),
    "Lai, Hing Ting": ("Lai Hing Ting", "Lai", "Hing Ting"),
}


def plain(name: str) -> list:
    """What the page makes of a name by itself: "Family, Given" turned round."""
    if ", " not in name:
        return [name, name, "", name]
    last, first = name.split(", ", 1)
    return [f"{first} {last}", last, first, f"{first.split(' ')[0]} {last}"]


def parts(name: str, fed: str = "") -> list:
    """``[full, surname, given, short]`` for a player."""
    if name in KNOWN:
        full, sur, given = KNOWN[name]
        return [full, sur, given, full]
    if ", " not in name:
        return plain(name)
    last, first = name.split(", ", 1)
    words = first.split(" ")
    if len(words) > 1 and len(words[-1]) == 1 and words[-1].islower():   # FIDE's namesake mark
        first = " ".join(words[:-1])
    if fed in FAMILY_FIRST:
        return [f"{last} {first}", last, first, f"{last} {first}"]
    return [f"{first} {last}", last, first, f"{first.split(' ')[0]} {last}"]


def exceptions(people) -> dict:
    """``FIDE name -> parts`` for the names the page would get wrong by itself.
    ``people`` yields ``(name, fed)``."""
    out = {}
    for name, fed in people:
        p = parts(name, fed)
        if p != plain(name):
            out[name] = p
    return out
