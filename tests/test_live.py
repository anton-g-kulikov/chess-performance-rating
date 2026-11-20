"""A World Championship match while it is being played: results from Lichess's
broadcast (perfrating/live.py) until FIDE's own data holds the match."""

import unittest
from datetime import date
from pathlib import Path

from perfrating.live import due, games, headers, time_format
from perfrating.matches import MATCHES, from_live, match_lines, match_pages

FIXTURES = Path(__file__).parent / "fixtures"
DING, GUKESH = 8603677, 46616543
SPEC = next(m for m in MATCHES if m["year"] == 2024)   # Ding (a) v Gukesh (b)


def broadcast_2024() -> list:
    """The 2024 match as Lichess broadcast it (the tag pairs only)."""
    tags = headers((FIXTURES / "broadcast_wch2024.pgn").read_text(encoding="utf-8"))
    return games(tags, DING, GUKESH, {})


def game(n, white, black, result, f="classical", day=None):
    rating = {DING: 2728, GUKESH: 2783}
    return {"f": f, "date": day or f"2024-11-{n + 10:02d}", "round": str(n), "white": white, "black": black,
            "white_rating": rating[white], "black_rating": rating[black], "result": result}


class LiveTest(unittest.TestCase):
    def test_time_controls_are_read_as_fide_formats(self):
        self.assertEqual(time_format("40/7200:1800+30"), "classical")
        self.assertEqual(time_format("5400+30"), "classical")
        self.assertEqual(time_format("900+10"), "rapid")
        self.assertEqual(time_format("180+2"), "blitz")
        self.assertEqual(time_format("", "rapid"), "rapid")

    def test_the_broadcast_gives_what_fide_gave_for_2024(self):
        g = broadcast_2024()
        self.assertEqual(len(g), 14)
        self.assertEqual((g[0]["white"], g[0]["result"], g[0]["date"]), (GUKESH, "0-1", "2024-11-25"))
        m = from_live(SPEC, {"games": g, "over": True, "url": "u"})
        # The numbers FIDE's own game-by-game data gives for the match.
        self.assertEqual(m["res"], [1, .5, 0, .5, .5, .5, .5, .5, .5, .5, 0, 1, .5, 0])
        self.assertEqual((m["a"], m["b"], m["win"]), (6.5, 7.5, "b"))
        self.assertEqual((m["start"], m["end"]), ("2024-11-25", "2024-12-12"))
        self.assertEqual(m["rating"], {"a": 2728, "b": 2783})
        self.assertEqual(m["tpr"], {"a": 2754, "b": 2757})
        self.assertTrue(m["live"]["over"])

    def test_part_way_through_nobody_has_won(self):
        g = broadcast_2024()[:5]
        m = from_live(SPEC, {"games": g, "over": False})
        self.assertEqual((m["a"], m["b"], m["win"], m["live"]["over"]), (2.5, 2.5, None, False))
        self.assertEqual(m["end"], "2024-11-30")
        # Unfinished games don't count, and a match with no finished game isn't shown as played.
        self.assertIsNone(from_live(SPEC, {"games": [{**g[0], "result": "*"}]}))

    def test_seven_and_a_half_decides_it_before_game_fourteen(self):
        g = [game(i, DING, GUKESH, "1-0") for i in range(1, 8)] + [game(8, GUKESH, DING, "1/2-1/2")]
        m = from_live(SPEC, {"games": g, "over": False})
        self.assertEqual((m["a"], m["win"], m["live"]["over"]), (7.5, "a", True))

    def test_a_level_match_waits_for_its_tiebreak(self):
        g = [game(i, DING, GUKESH, "1/2-1/2") for i in range(1, 15)]
        rapid = [game(15, DING, GUKESH, "0-1", "rapid", "2024-12-13"), game(16, GUKESH, DING, "1/2-1/2", "rapid", "2024-12-13")]
        m = from_live(SPEC, {"games": g + rapid, "over": False})
        self.assertEqual((m["a"], m["b"], m["win"]), (7, 7, None))
        self.assertEqual([(t["f"], t["res"]) for t in m["tb"]], [("rapid", [0, .5])])
        m = from_live(SPEC, {"games": g + rapid, "over": True})
        self.assertEqual((m["tsa"], m["tsb"], m["win"], m["end"]), (.5, 1.5, "b", "2024-12-13"))

    def test_fide_data_takes_over_from_the_broadcast(self):
        def player(name, opp, own, their, results):
            e = {"event_id": 9, "name": "WCh", "start": "2024-11-25", "end": "2024-12-12", "period": "2025-01-01",
                 "ro": own, "games": [{"opponent": opp, "opponent_rating": their, "result": r, "counted": True} for r in results]}
            return {"name": name, "fed": "X", "ratings": {}, "games": {"classical": [e]}}
        empty = {"players": {}}
        fide = {"players": {str(DING): player("Ding, Liren", "Gukesh D", 2728, 2783, [1] * 8),
                            str(GUKESH): player("Gukesh D", "Ding, Liren", 2783, 2728, [0] * 8)}}
        people = {DING: ("Ding, Liren", "CHN"), GUKESH: ("Gukesh D", "IND")}
        live = {2024: {"games": broadcast_2024()[:3], "over": False, "url": "u"}}
        roll = {"year": None, "periods": ["2025-12-01", "2026-11-01"]}
        from perfrating.web import opponent_ids
        ids, _ = opponent_ids([fide])

        def page(saved):
            ms = match_pages([(roll, empty, None), ({"year": 2024}, saved, None)], ids, people, live)
            return next(m for m in ms if m["year"] == 2024)
        m = page(empty)                                   # FIDE hasn't rated it yet: the broadcast
        self.assertEqual((m["played"]["res"], m["window"]["to"]), ([1, .5, 0], "2024-11-25"))
        self.assertIn("live", m["played"])
        # The main page keeps comparing the two on the rolling lists meanwhile.
        line = match_lines([{"id": "", "year": None}], [m], {})[""]
        self.assertEqual((line["label"], line["note"]), ("World Championship match", "classical TPR, last 12 months"))
        m = page(fide)                                    # FIDE's own data, once it is there
        self.assertNotIn("live", m["played"])
        self.assertEqual((m["played"]["a"], m["played"]["win"]), (8, "a"))

    def test_the_daily_run_only_fetches_while_a_match_is_on(self):
        spec = {**SPEC, "lichess": "x", "first_game": "2024-11-25"}
        self.assertFalse(due(spec, None, date(2024, 11, 20)))                     # not started
        self.assertTrue(due(spec, None, date(2024, 11, 25)))
        self.assertTrue(due(spec, {"games": broadcast_2024()[:5]}, date(2024, 11, 30)))
        self.assertFalse(due(spec, {"games": broadcast_2024(), "over": True}, date(2024, 12, 13)))   # over
        self.assertFalse(due(SPEC, None, date(2024, 11, 25)))                     # no broadcast


if __name__ == "__main__":
    unittest.main()
