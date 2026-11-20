import json
import unittest
from decimal import Decimal
from pathlib import Path

from datetime import date

from perfrating.build import (build_rows, event_year, scaled_minimum, window,
                              year_fraction, year_periods)
from perfrating.parsers import parse_calculation, parse_period_arrays, parse_top_list
from perfrating.performance import dp, performance, round_p, true_performance
from perfrating.race import race_frames, rolling_frames
from perfrating.web import name_key, opponent_ids, player_entries, progress, split_page

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


class YearModeTest(unittest.TestCase):
    def test_event_year_uses_end_date(self):
        # World Blitz 2025 is rated in the January 2026 list but belongs to 2025.
        self.assertEqual(event_year({"start": "2025-12-29", "end": "2025-12-30", "period": "2026-01-01"}), 2025)
        self.assertEqual(event_year({"start": "2025-12-28", "end": "2026-01-04", "period": "2026-02-01"}), 2026)
        self.assertEqual(event_year({"start": None, "end": None, "period": "2026-01-01"}), 2025)

    def test_year_periods(self):
        cur = year_periods(2026, date(2026, 11, 1))
        self.assertEqual((cur[0], cur[-1], len(cur)), ("2026-01-01", "2026-11-01", 11))
        full = year_periods(2025, date(2026, 11, 1))
        self.assertEqual((full[0], full[-1], len(full)), ("2025-01-01", "2026-04-01", 16))

    def test_year_fraction_and_minimum(self):
        self.assertAlmostEqual(year_fraction(2026, window(date(2026, 11, 1), 11)), 10 / 12)
        self.assertEqual(year_fraction(2025, window(date(2026, 4, 1), 16)), 1.0)
        self.assertEqual(scaled_minimum({"classical": 20, "blitz": 40}, 10 / 12), {"classical": 17, "blitz": 34})
        self.assertEqual(scaled_minimum({"classical": 20, "blitz": 40}, 1 / 12), {"classical": 10, "blitz": 20})
        self.assertEqual(scaled_minimum({"classical": 20}, 7 / 12), {"classical": 12})
        self.assertEqual(scaled_minimum({"classical": 20}, 0.0), {"classical": 10})


class PlayerPageTest(unittest.TestCase):
    def test_name_key_matches_list_and_calculation_spellings(self):
        self.assertEqual(name_key("Gukesh D"), name_key("Gukesh, D"))
        self.assertEqual(name_key("Aravindh, Chithambaram VR."), name_key("Aravindh, Chithambaram VR"))
        self.assertNotEqual(name_key("So, Wesley"), name_key("So, Wesley b"))

    def test_opponent_spellings_resolve_to_one_pool_player(self):
        def player(name, rating, opponents):
            return {"name": name, "fed": "X", "ratings": {"classical": rating},
                    "games": {"classical": [{"games": [{"opponent": o, "opponent_rating": r} for o, r in opponents]}]}}
        saved = {"players": {
            "1": player("Praggnanandhaa R", 2750, []),
            "2": player("Niemann, Hans Moke", 2730, []),
            "3": player("Flores, Diego", 2600, []),
            "4": player("Keymer, Vincent", 2760, [
                ("Praggnanandhaa, R", 2750), ("Rameshbabu, Praggnanandhaa", 2750), ("R, Praggnanandhaa", 2750),
                ("Niemann, Hans", 2725), ("Flores Quillas, Diego Saul Rodri", 2398), ("Niemann, Bob", 2100),
                ("Flores, D", 2150)]),
        }}
        ids, listed = opponent_ids([saved])
        for spelling in ("Praggnanandhaa, R", "Rameshbabu, Praggnanandhaa", "R, Praggnanandhaa"):
            self.assertEqual(ids[name_key(spelling)], 1)   # word order and initials
        self.assertEqual(ids[name_key("Niemann, Hans")], 2)  # a name left out, ratings agree
        self.assertNotIn(name_key("Flores Quillas, Diego Saul Rodri"), ids)  # a namesake 200 points away
        self.assertNotIn(name_key("Niemann, Bob"), ids)
        self.assertNotIn(name_key("Flores, D"), ids)  # initials fit, but a namesake 450 points away
        self.assertEqual(listed[1], "Praggnanandhaa R")

    def test_a_misspelt_opponent_is_found_from_the_other_side_of_the_board(self):
        def player(name, ro, games):
            return {"name": name, "fed": "X", "ratings": {"classical": ro}, "games": {"classical": [
                {"event_id": 7, "ro": ro, "games": [{"opponent": o, "opponent_rating": r, "result": w} for o, r, w in games]}]}}
        saved = {"players": {
            "1": player("Ding, Liren", 2728, [("Guskesh, D", 2783, 1), ("Guskesh, D", 2783, 0), ("Guskesh, D", 2783, .5),
                                              ("Someone, Else", 2650, 1)]),
            "2": player("Gukesh D", 2783, [("Ding, Liren", 2728, 0), ("Ding, Liren", 2728, 1), ("Ding, Liren", 2728, .5)]),
            # Played Ding under the right name; "Someone, Else" only shares the rating.
            "3": player("Rated, Same", 2650, [("Ding, Liren", 2728, 0)]),
        }}
        saved["players"]["1"]["games"]["classical"][0]["games"].append(
            {"opponent": "Rated, Same", "opponent_rating": 2650, "result": 1})
        ids, listed = opponent_ids([saved])
        self.assertNotIn(name_key("Guskesh, D"), ids)        # no name rule fits
        self.assertEqual(ids[(7, name_key("Guskesh, D"))], 2)  # but the match does
        self.assertNotIn((7, name_key("Someone, Else")), ids)  # player 3 is already in Ding's games

    def test_a_played_match_is_found_with_its_tiebreak_and_the_year_before_it(self):
        from perfrating.matches import before, match_lines, played

        def ev(eid, start, end, ro, games, fmt="classical"):
            return fmt, {"event_id": eid, "name": f"E{eid}", "start": start, "end": end, "period": end, "ro": ro,
                         "games": [{"opponent": o, "opponent_rating": r, "result": w, "counted": True} for o, r, w in games]}

        def player(name, *events):
            games = {}
            for fmt, e in events:
                games.setdefault(fmt, []).append(e)
            return {"name": name, "fed": "X", "ratings": {}, "games": games}
        saved = {"players": {
            "1": player("Nepo, Ian",
                        ev(1, "2022-03-01", "2022-03-10", 2770, [("Other, A", 2700, 1)]),        # 13 months before: out
                        ev(2, "2022-12-01", "2022-12-10", 2790, [("Other, A", 2700, 1), ("Other, B", 2750, .5)]),
                        ev(3, "2023-04-09", "2023-04-29", 2795, [("Ding, Liren", 2788, r) for r in (1, .5, 0, .5)]),
                        ev(4, "2023-04-30", "2023-04-30", 2780, [("Ding, Liren", 2790, r) for r in (.5, 0)], "rapid")),
            "2": player("Ding, Liren",
                        ev(3, "2023-04-09", "2023-04-29", 2788, [("Nepo, Ian", 2795, r) for r in (0, .5, 1, .5)]),
                        ev(4, "2023-04-30", "2023-04-30", 2790, [("Nepo, Ian", 2780, r) for r in (.5, 1)], "rapid")),
        }}
        from perfrating.web import opponent_ids
        ids, _ = opponent_ids([saved])
        m = played(saved, 1, 2, ids)
        self.assertEqual((m["start"], m["res"], m["a"], m["b"]), ("2023-04-09", [1, .5, 0, .5], 2, 2))
        self.assertEqual([(t["f"], t["res"]) for t in m["tb"]], [("rapid", [.5, 0])])
        self.assertEqual(m["win"], "b")                                   # level, then the tiebreak
        self.assertEqual(m["rating"], {"a": 2795, "b": 2788})
        self.assertIsNone(played(saved, 1, 3, ids))                       # no such match in the data
        b = before([saved], 1, m["start"])
        self.assertEqual((b["games"], b["score"]), (2, 1.5))              # event 2 only: 1 is too old, 3 is the match
        # The main page's line: the match of the year picked, or the newest on the rolling list.
        matches = [{"year": 2023, "played": m, "a": {"id": 1, "short": "Nepo"}, "b": {"id": 2, "short": "Ding"}}]
        pages = {1: {"modes": {"y2023": {"classical": {"tpr": 2748}}}}, 2: {"modes": {"y2023": {"classical": {"tpr": 2734}}}}}
        lines = match_lines([{"id": "", "year": None}, {"id": "y2023", "year": 2023}, {"id": "y2022", "year": 2022}], matches, pages)
        self.assertEqual(lines["y2023"]["a"], ["Nepo", 2748])
        self.assertEqual(lines["y2023"]["href"], "/event/world-championship-2023")
        self.assertNotIn("y2022", lines)

    def test_names_are_shown_the_way_players_are_known(self):
        from perfrating.names import exceptions, parts, plain
        self.assertEqual(parts("Carlsen, Magnus", "NOR"), ["Magnus Carlsen", "Carlsen", "Magnus", "Magnus Carlsen"])
        self.assertEqual(parts("Ding, Liren", "CHN")[0], "Ding Liren")          # family name first
        self.assertEqual(parts("Li, Chao b", "CHN")[0], "Li Chao")              # FIDE's namesake mark dropped
        self.assertEqual(parts("Erigaisi Arjun", "IND")[:2], ["Arjun Erigaisi", "Erigaisi"])
        self.assertEqual(parts("Gukesh D", "IND")[1], "Gukesh")
        # Only what the page can't work out itself goes to it.
        self.assertEqual(set(exceptions([("Carlsen, Magnus", "NOR"), ("Wei, Yi", "CHN")])), {"Wei, Yi"})
        self.assertEqual(plain("So, Wesley"), ["Wesley So", "So", "Wesley", "Wesley So"])

    def test_player_entries_cover_ranked_and_unranked_players(self):
        def ev(name, start, games):
            return {"name": name, "start": start, "end": start, "period": "2026-01-01",
                    "games": [{"opponent": o, "opponent_rating": r, "result": s, "counted": True, "capped": c}
                              for o, r, s, c in games]}
        saved = {"players": {
            "1": {"name": "A", "fed": "X", "ratings": {"blitz": 2700},
                  "games": {"blitz": [ev("Old", "2025-12-01", [("B", 2700, 1, False)]),
                                      ev("New", "2026-01-05", [("B", 2700, 1, False), ("Z, Q", 2300, 0.5, True)])]}},
            "2": {"name": "B", "fed": "Y", "ratings": {"blitz": 2750},
                  "games": {"blitz": [ev("New", "2026-01-05", [("A", 2700, 0, False)])], "rapid": []}},
        }}
        rows = {"classical": [], "rapid": [],
                "blitz": [{"fide_id": 1, "rank": 1, "games": 3, "score": 2.5, "pct": 83.0,
                           "avg_opp": 2567, "tpr": 2840, "true_perf": 2850}]}
        out = player_entries(saved, rows, {name_key("B"): 2})
        a = out[1]["formats"]["blitz"]
        self.assertEqual((a["rank"], a["of"], a["tpr"], a["rating"]), (1, 1, 2840, 2700))
        self.assertEqual([e[1] for e in a["ev"]], ["New", "Old"])  # newest first
        self.assertEqual(a["ev"][0][8], [["B", 2700, 1, 0, 2], ["Z, Q", 2300, 0.5, 1, 0]])
        b = out[2]["formats"]
        self.assertEqual(list(b), ["blitz"])  # formats without games are left out
        self.assertEqual((b["blitz"]["rank"], b["blitz"]["games"], b["blitz"]["tpr"]), (None, 1, 1900))

    def test_a_match_page_names_itself_for_search_engines(self):
        from perfrating.web import match_head, sitemap
        match = {"year": 2026, "place": "Geneva", "played": None,
                 "a": {"full": "Gukesh D", "short": "Gukesh"}, "b": {"full": "Conor O'Brien", "short": "O'Brien"}}
        title, tags = match_head(match)
        self.assertEqual(title, "Gukesh vs O&#x27;Brien, World Championship 2026 · Chess Performance Ratings")
        self.assertIn('<link rel="canonical" href="https://chesstpr.com/event/world-championship-2026">', tags)
        self.assertIn("How Gukesh D and Conor O&#x27;Brien have played over the last 12 months", tags)
        _, tags = match_head({**match, "played": {"res": [1.0]}})
        self.assertIn("The match game by game", tags)
        # The sitemap gives the same address the page gives for itself.
        self.assertIn("<loc>https://chesstpr.com/event/world-championship-2026</loc>",
                      sitemap(["/", "/event/world-championship-2026", "/player/1503014"]))

    def test_pages_carry_the_analytics_script_only_with_a_token(self):
        from perfrating.web import with_analytics
        page = "</script>\n<!--ANALYTICS-->\n"
        self.assertEqual(with_analytics(page, ""), "</script>\n")
        self.assertIn("""data-cf-beacon='{"token": "abc123"}'""", with_analytics(page, "abc123"))

    def test_split_page_keeps_numbers_in_the_summary_and_events_by_period(self):
        page = {"id": 7, "name": "A", "fed": "X", "modes": {
            "": {"blitz": {"rank": 1, "tpr": 2800, "ev": [["2026-01", "Open"]]}},
            "y2025": {"rapid": {"rank": None, "tpr": 2600, "ev": [["2025-05", "Cup"]]},
                      "blitz": {"rank": 3, "tpr": 2700, "ev": []}},
        }}
        summary, files = split_page(page)
        self.assertEqual(summary["modes"]["y2025"]["rapid"], {"rank": None, "tpr": 2600})
        self.assertEqual(sorted(summary["files"]), ["", "y2025"])
        self.assertTrue(summary["files"][""].startswith("r12-"))
        self.assertEqual(json.loads(files[summary["files"]["y2025"]]),
                         {"rapid": [["2025-05", "Cup"]], "blitz": []})
        # A period's file name follows its content alone.
        page["modes"][""]["blitz"]["ev"].append(["2026-02", "Rapid"])
        again, _ = split_page(page)
        self.assertNotEqual(again["files"][""], summary["files"][""])
        self.assertEqual(again["files"]["y2025"], summary["files"]["y2025"])

    def test_progress_is_tpr_to_date_oldest_first(self):
        def ev(start, ro, games):
            return {"start": start, "end": start, "period": "2026-01-01", "ro": ro,
                    "games": [{"opponent_rating": r, "result": x, "counted": True} for r, x in games]}
        events = [ev("2026-03-01", 2710, [(2700, 0)]), ev("2026-01-01", 2700, [(2700, 1)])]  # newest first
        self.assertEqual(progress(events), [[2710, 2700, 2], [2700, 3500, 1]])

    def test_race_frames_scale_the_minimum_and_end_on_the_list(self):
        def ev(end, n, result):
            return {"start": end, "end": end, "period": "2026-01-01",
                    "games": [{"opponent_rating": 2700, "result": result, "counted": True}] * n}
        saved = {"year": 2026, "players": {
            "1": {"name": "A", "fed": "X", "ratings": {}, "games": {"blitz": [ev("2026-01-10", 25, 1), ev("2026-02-10", 40, 0.5)]}},
            "2": {"name": "B", "fed": "Y", "ratings": {}, "games": {"blitz": [ev("2026-01-20", 4, 1), ev("2026-02-20", 40, 0.6)]}},
        }}
        frames = race_frames(saved, "blitz", 2, final_min=7)
        # January's scaled minimum (40 / 12 = 4) is floored at half the full one (20),
        # so B's 4 straight wins don't count yet; the last frame uses the list's minimum.
        self.assertEqual([(f["m"], f["min"], f["q"]) for f in frames], [(1, 20, 1), (2, 7, 2)])
        self.assertEqual(frames[0]["rows"], [[1, 3500, 25, None]])
        self.assertEqual([r[0] for r in frames[1]["rows"]], [1, 2])

    def test_rolling_frames_slide_the_window_over_the_history(self):
        def ev(period, n, result):
            return {"start": period, "end": period, "period": period,
                    "games": [{"opponent_rating": 2700, "result": result, "counted": True}] * n}
        # A three-list window (Mar-May) with two lists of history (Jan, Feb).
        saved = {"periods": ["2026-03-01", "2026-04-01", "2026-05-01"],
                 "history": {"periods": ["2026-01-01", "2026-02-01"],
                             "players": {"1": {"blitz": [ev("2026-01-01", 2, 1)]}}},
                 "players": {
                     "1": {"name": "A", "fed": "X", "ratings": {}, "games": {"blitz": [ev("2026-04-01", 2, 0.5)]}},
                     "2": {"name": "B", "fed": "Y", "ratings": {}, "games": {"blitz": [ev("2026-05-01", 2, 1)]}},
                 }}
        frames = rolling_frames(saved, "blitz", 2)
        self.assertEqual([(f["y"], f["m"], f["q"]) for f in frames], [(2026, 3, 1), (2026, 4, 1), (2026, 5, 2)])
        # Jan-Mar: only A's January wins.  Feb-Apr: those drop out, A's April draws remain.
        self.assertEqual(frames[0]["rows"], [[1, 3500, 2, None]])
        self.assertEqual(frames[1]["rows"], [[1, 2700, 2, None]])
        # The last frame is the published window: B's wins, then A's draws.
        self.assertEqual([r[0] for r in frames[2]["rows"]], [2, 1])


if __name__ == "__main__":
    unittest.main()
