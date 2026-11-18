# Chess performance rating

Rating lists for classical, rapid and blitz, ranked by each player's
**performance over the last 12 FIDE rating periods only**. Older results and
long-standing reputations don't count.

**Current lists: [`results/README.md`](results/README.md)**, with the full
tables in `results/{classical,rapid,blitz}.csv`.

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
python -m unittest discover -s tests -t .        # tests
```

Responses are cached in `.cache/fide/`, so re-runs are fast. Raw games are
written to `data/games.json` and the lists to `results/`. Pass `--exhaustive`
to fetch every period instead of relying on FIDE's index of periods that have
games. It's slower, and the two modes matched in spot checks.
