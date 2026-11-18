import unittest
from decimal import Decimal
from pathlib import Path

from perfrating.build import build_rows, window
from perfrating.parsers import parse_calculation, parse_period_arrays, parse_top_list
from perfrating.performance import dp, performance, round_p, true_performance

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8-sig")


class PerformanceTest(unittest.TestCase):
    def test_dp_table(self):
        self.assertEqual(dp(Decimal("0.50")), 0)
        self.assertEqual(dp(Decimal("0.75")), 193)
        self.assertEqual(dp(Decimal("0.25")), -193)
        self.assertEqual(dp(Decimal("1.00")), 800)
        self.assertEqual(dp(Decimal("0.00")), -800)
        # symmetric
        for h in range(0, 101):
            p = Decimal(h) / 100
            self.assertEqual(dp(p), -dp(Decimal(1) - p))

    def test_round_half_up(self):
        self.assertEqual(round_p(4.5, 10), Decimal("0.45"))
        self.assertEqual(round_p(1, 8), Decimal("0.13"))  # 0.125 -> 0.13

    def test_performance(self):
        perf = performance([(2700, 1), (2700, 0.5), (2700, 0.5), (2700, 0)])
        self.assertEqual(perf.tpr, 2700)
        self.assertAlmostEqual(perf.true, 2700, places=3)
        perf = performance([(2600, 1), (2800, 0.5)])
        self.assertEqual(perf.avg_opp, 2700)
        self.assertEqual(perf.tpr, 2700 + 193)

    def test_true_performance_undefined_for_perfect_scores(self):
        self.assertIsNone(true_performance([2700, 2700], 2))
        self.assertIsNone(true_performance([2700, 2700], 0))


class ParserTest(unittest.TestCase):
    def test_standard_calculation_matches_fide_totals(self):
        (t,) = parse_calculation(fixture("calc_standard.html"))
        self.assertEqual(t.name, "Norway Chess 2026")
        self.assertEqual((t.start, t.end), ("2026-05-25", "2026-06-05"))
        self.assertEqual(len(t.games), 10)
        self.assertEqual(sum(g.result for g in t.games), t.w)
        self.assertEqual(len(t.games), t.n)
        self.assertEqual(t.games[0].opponent, "Firouzja, Alireza")
        self.assertEqual(t.games[0].opponent_rating, 2759)
        avg = sum(g.opponent_rating for g in t.games) / len(t.games)
        self.assertLess(abs(avg - t.rc), 1)

    def test_blitz_calculation_multiple_events_and_capped_ratings(self):
        events = parse_calculation(fixture("calc_blitz.html"))
        self.assertEqual(len(events), 3)
        for t in events:
            self.assertEqual(sum(g.result for g in t.games), t.w)
            self.assertEqual(len(t.games), t.n)
            avg = sum(g.opponent_rating for g in t.games) / len(t.games)
            self.assertLess(abs(avg - t.rc), 1)
        capped = [g for g in events[0].games if g.capped]
        self.assertEqual(len(capped), 3)
        self.assertTrue(all(g.opponent_rating == 2469 for g in capped))

    def test_empty_fragment(self):
        self.assertEqual(parse_calculation("﻿"), [])

    def test_top_list(self):
        page = """<table><tr>
            <td>1</td><td><a href=/profile/1503014>Carlsen, Magnus</a></td>
            <td class="flag-wrapper">
                <img src="/images/flags/no.svg" height=20> NOR
            </td><td class=rating_column>2801</td></tr></table>"""
        (p,) = parse_top_list(page)
        self.assertEqual((p.fide_id, p.name, p.fed, p.rating), (1503014, "Carlsen, Magnus", "NOR", 2801))

    def test_period_arrays(self):
        page = """var std_array = ["2026-07-01","2026-06-01"];
        var std_array_r = ["July 2026  (-17.8)","June 2026  (1.4)"];
        var rapid_array = [];"""
        self.assertEqual(parse_period_arrays(page), {"std": ["2026-07-01", "2026-06-01"], "rapid": []})


class BuildTest(unittest.TestCase):
    def test_window(self):
        from datetime import date
        w = window(date(2026, 11, 1), 12)
        self.assertEqual(w[0], "2025-12-01")
        self.assertEqual(w[-1], "2026-11-01")
        self.assertEqual(len(w), 12)

    def test_build_rows_filters_and_sorts(self):
        def ev(games):
            return [{"period": "2026-01-01", "end": None, "ro": None,
                     "games": [{"opponent_rating": r, "result": s, "counted": True} for r, s in games]}]
        pool = {1: {"name": "A", "fed": "X", "ratings": {"blitz": 2700}},
                2: {"name": "B", "fed": "Y", "ratings": {"blitz": 2750}},
                3: {"name": "C", "fed": "Z", "ratings": {"blitz": 2800}}}
        games = {1: {"blitz": ev([(2700, 1)] * 3)},
                 2: {"blitz": ev([(2700, 0.5)] * 3)},
                 3: {"blitz": ev([(2700, 1)] * 2)}}  # too few games
        rows = build_rows(pool, games, "blitz", min_games=3)
        self.assertEqual([r["name"] for r in rows], ["A", "B"])
        self.assertEqual(rows[0]["tpr"], 3500)
        self.assertEqual(rows[1]["tpr"], 2700)


if __name__ == "__main__":
    unittest.main()
