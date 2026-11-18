# Chess performance rating

An alternative to the FIDE rating. FIDE ratings accumulate: every result
carries forward, so a rating reflects years of play and barely moves for
players who rarely compete. These lists rank classical, rapid and blitz by
**performance over the last 12 FIDE rating periods only**. Older results don't
count, and a player without enough recent rated games isn't ranked at all,
whatever their FIDE rating.

There are two modes, like tennis's ranking and race:

- **Rolling 12 months** ([`results/`](results/README.md)): every game rated in
  the last 12 FIDE lists. Nothing resets. Each month the oldest list drops out
  and the newest comes in.
- **Calendar-year race** ([`results/2026/`](results/2026/README.md)): games from
  events that ended in that year. Everyone starts again on January 1. An
  event belongs to the year it ended in, so the World Rapid & Blitz of late
  December 2025 counts for 2025 even though FIDE rated it in January 2026.
  While the year is in progress, the minimum number of games scales with
  the months played so far (10 of 12 in mid-November gives 17 / 17 / 34).

Each list is in `results/…/{classical,rapid,blitz}.csv`. `site/index.html`
is a self-contained web page with both modes, sortable columns, search and
each player's events.

## How it works

1. **Player pool.** Players come from FIDE's current open top-100 lists for
   classical, rapid and blitz, combined. Every player in the pool is ranked in
   all three formats.
2. **Games.** For each player, the builder downloads FIDE's game-by-game rating
   calculations (`ratings.fide.com`) for the last 12 rating periods in each
   format. Only games FIDE actually rated (opponent rated, `n = 1`) are used.
3. **Performance.** All games in a format are pooled into a single event.
   - **TPR** (used for ranking) is the FIDE performance rating: the average
     opponent rating plus `dp` from FIDE table 8.1a for the percentage score,
     rounded to 0.01.
   - **True** is the rating at which the FIDE expected score against those exact
     opponents equals the actual score. It allows for the spread of opponent
     ratings, and isn't defined for 0% or 100% scores.
4. **Minimum games.** To qualify, a player needs at least 20 classical, 20 rapid
   or 40 blitz rated games in the window.

### Notes and limitations

- The window covers rating periods, not calendar dates. For example, the
  December 2025 – November 2026 lists cover games rated in those periods,
  which were mostly played from November 2025 to October 2026.
- When an opponent is rated more than 400 points below the player, FIDE's
  calculation records that opponent as *player's rating − 400* (marked `*`
  on FIDE's site). The builder uses the same capped value, so these
  performances match FIDE's own arithmetic.
- The pool is limited to current top-100 players. A player outside all three
  top-100 lists who had a great year won't appear.
- **Rating** is the player's current rating from the top-100 list. If the player
  isn't on that format's list, it's the rating going into their most recent
  event in that format.
- The **Δ** column is TPR minus that rating.

## Running it

Python 3.9+ is needed; there are no third-party dependencies.

```sh
python -m perfrating.build                       # latest FIDE list, 12 periods
python -m perfrating.build --end 2026-11 --months 12 --min-games 20,20,40
python -m perfrating.build --year 2026            # calendar-year race -> results/2026/
python -m perfrating.build --from-data           # re-rank saved games, no fetching
python -m perfrating.web                         # web page -> site/index.html
python -m unittest discover -s tests -t .        # tests
```

Responses are cached in `.cache/fide/`, so re-runs are fast. Raw games are
written to `data/games.json` (`data/games-YEAR.json` for a race) and the
lists to `results/` (`results/YEAR/`). A finished year reads FIDE lists
through April of the next year, to catch late-reported events. Pass `--exhaustive`
to fetch every period instead of relying on FIDE's index of periods that have
games. It's slower, and the two modes matched in spot checks.
