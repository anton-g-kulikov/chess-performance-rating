# Chess performance rating

An alternative to the FIDE rating. FIDE ratings accumulate: every result
carries forward, so a rating reflects years of play and barely moves for
players who rarely compete. These lists rank classical, rapid and blitz by
**recent performance only**. Older results don't count, and a player without
enough recent rated games isn't ranked at all, whatever their FIDE rating.

There are two modes, like tennis's ranking and race:

- **Rolling 12 months** ([`results/`](results/README.md)): every game rated in
  the last 12 FIDE lists. Nothing resets. Each month the oldest list drops out
  and the newest comes in.
- **Calendar-year race** ([`results/2026/`](results/2026/README.md)): games from
  events that ended in that year. Everyone starts again on January 1. An
  event belongs to the year it ended in, so the World Rapid & Blitz of late
  December 2025 counts for 2025 even though FIDE rated it in January 2026.
  While the year is in progress, the minimum number of games scales with
  the months played so far, never below half (10 of 12 in mid-November gives
  17 / 17 / 34).
  Finished years go back to 2013 (`results/2013/` … `results/2025/`), the
  first year covered by FIDE's archive of monthly rating lists.

Each list is in `results/…/{classical,rapid,blitz}.csv`. The web page,
[chesstpr.com](https://chesstpr.com), has both modes and every year, sortable
columns, search, side-by-side players and each player's events. Every player
in the pool also has a page, `chesstpr.com/player/<FIDE id>`, with their
results in every period and format, including those where they have too few
games to be ranked or finish outside the top 100, down to single games, and a
chart of their TPR over all games so far after each event. Each year race can
be replayed month by month: the top 10 at the end of each month, with the
minimum number of games scaled to the months played, but never below half.
The rolling ranking can be replayed over the past year: the top 10 of the
12-list window ending at each of the last 12 lists, from today's player pool.

## How it works

Both modes use the same calculation. They differ only in which games go in.

1. **Player pool.** Players come from FIDE's current open top-100 lists for
   classical, rapid and blitz, combined. For a finished year, they come from
   FIDE's archived lists instead: everyone in an open top 100 in any format
   at the start of each quarter of that year or in January of the next.
   Every player in the pool is ranked in all three formats.
2. **Games.** For each player, the builder downloads FIDE's game-by-game rating
   calculations (`ratings.fide.com`). Only games FIDE actually rated
   (opponent rated, `n = 1`) are used. Which games go in depends on the mode:
   - **Rolling 12 months:** every game rated on the last 12 monthly lists,
     whenever it was played. Selection is by rating period, so the
     December 2025 – November 2026 lists hold games mostly played from
     November 2025 to October 2026.
   - **Year race:** every game from events that *ended* in that year, whichever
     list FIDE rated them on. The builder reads that year's lists and the next
     January to April (FIDE rates some events a few months late), then keeps
     the events whose end date falls in the year.
3. **Performance.** All of a player's games in a format are pooled into a
   single event, as if they were one long tournament.
   - **TPR** (used for ranking) is the FIDE performance rating: the average
     opponent rating plus `dp` from FIDE table 8.1a for the percentage score,
     rounded to 0.01.
   - **True** is the rating at which the FIDE expected score against those exact
     opponents equals the actual score. It allows for the spread of opponent
     ratings, and isn't defined for 0% or 100% scores.
4. **Minimum games.** To qualify, a player needs at least 20 classical, 20 rapid
   or 40 blitz rated games in the window. A year in progress scales these by
   the share of the year covered so far, but never below half (10 / 10 / 20),
   so a couple of early wins can't top the list.

### Why a player's own rating doesn't carry over

A FIDE rating is a running total. Each rating period starts from the previous
rating and adds `K × (score − expected score)`, so today's rating still holds
every result back to a player's first rated game, with older results
gradually fading. A strong player who rarely plays, or plays poorly for a
while, keeps most of their rating.

These lists start from nothing in every window:

- **Results outside the window aren't read.** The rolling list sees only the
  last 12 lists; a year race sees only that year's events. Nothing carries
  from one window to the next.
- **The player's rating isn't in the formula.** TPR uses only the opponents'
  ratings and the player's score. Two players with the same opponents and
  the same score get the same TPR, whatever their own ratings. **True**
  works the same way.
- **Ranking is by TPR alone.** The **FIDE** column and **Δ** are shown for
  comparison and don't affect the order.

A player's own rating still matters in two places:

- **Who is in the pool.** Only players in an open top 100 are considered, and
  those lists are sorted by FIDE rating. The rating decides who is eligible,
  not where they finish.
- **FIDE's 400-point rule.** When an opponent is rated more than 400 points
  below the player, FIDE's calculation records that opponent as *player's
  rating − 400* (marked `*` on FIDE's site), and the builder uses the same
  value so the numbers match FIDE's. In these games the player's own rating
  sets the opponent's rating, and it's higher than the opponent's real rating,
  so TPR comes out higher. About 11% of all games used are affected. Among
  the top 20 of each list it usually touches only a few of a player's
  games, but it's common for players who play many open tournaments.

Opponents' ratings are FIDE ratings too, with their own history. That's
unavoidable: a performance rating measures results against the opponents'
ratings at the time.

### Notes and limitations

- The pool is limited to top-100 players. A player outside all three
  top-100 lists who had a great year won't appear.
- **FIDE** is the player's current rating from the top-100 list. If the player
  isn't on that format's list, it's the rating going into their most recent
  event in that format. For a finished year, it's the rating on that year's
  January list (or, failing that, going into their first event of the year).
- The **Δ** column is TPR minus that rating.
