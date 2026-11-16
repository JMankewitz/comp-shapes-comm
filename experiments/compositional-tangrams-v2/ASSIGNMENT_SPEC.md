# Spec: pair ready players across games ("matchmaker")

Status: PROPOSAL, 2026-11-16. Nothing here is implemented. It changes how the live
experiment runs, so it needs your sign-off and the test plan below before any wave.
Written from the Empirica 1.12.1 source (`admin/classic/classic.ts`, `lobby.ts`,
`models.ts`) and the 2026-11-16 datastore.

## 1. The problem, precisely

- A player is assigned to ONE game the moment they connect (before the intro).
- A game starts only when enough of ITS OWN assigned players finish the intro
  (`introDoneCheck`). Ready players in different games are never paired.
- Players who never finish the intro (left, stuck, slow) therefore hold a seat. The
  ready partner waits out the 10-minute lobby and is kicked.
- 2026-11-16: 6 games started (12 players). Most of the other players who got in were
  lost this way, or to the overbooking and reshuffling described in the runbook.

## 2. Options

| | What | Size | Risk |
|---|---|---|---|
| A | No code. Start all batches in creation order, 3 batches, process rules (already in the runbook). | none | none, but ghost seats and cross-game stranding remain |
| **B** | **Add one listener that moves a newly-ready player into the game of a ready player who is waiting alone.** Empirica's own assignment stays in charge. | ~40 lines in `callbacks.js` | low: additive, fails open |
| C | Turn off Empirica's assignment (`disableAssignment`, `disableIntroCheck`) and write all of it ourselves. | 200+ lines | high: we would re-implement starting, unassigning, "no more games", batch-open logic |

Recommendation: A for the next wave, B only after the test plan passes. C is not
recommended: it is the "brittle" path, and B gets nearly all the benefit.

## 3. Design of option B

It does not replace anything. Classic's default assignment, game creation, batches, the
lobby timer, and the start logic all stay exactly as they are. B only adds a second
chance for a player who just became ready and has no ready partner.

Trigger: `player` attribute `introDone` becomes true. (Our listener is registered
after Classic and Lobby in `index.js`, so Classic's start check and the lobby timer
setup for that same event have already run.)

```
on introDone(player):
  player.set("readyAt", now)                         // for ordering + timeout safety
  g = player.currentGame
  if !g or g.hasStarted or g.isStarting: return       // Classic already started it
  if ready(g).length >= playerCount(g): return        // Classic starts it; nothing to do

  waiters = players p where
      p != player and p.introDone and not p.ended
      and p.currentGame = g2 is in a RUNNING batch, not started/starting/ended
      and g2 != g and ready(g2).length == 1          // p is waiting ALONE
      and now - p.readyAt < 9 min                    // skip anyone about to time out
  if waiters is empty: return                        // today's behaviour, unchanged

  W = waiter with the earliest readyAt               // closest to timing out
  try:
      await W.currentGame.assignPlayer(player)       // Empirica's own move + unassign
      player.set("replayGameReadyCheck", true)       // Empirica re-runs its start check
  catch e:
      log, do nothing                                // fails open = today's behaviour
```

Where `ready(g)` = `g.players.filter(p => p.get("introDone") && !p.get("ended"))`, the
same expression Classic uses.

Why this is the smaller change:
- `assignPlayer` is what Classic itself uses to reassign players (it also removes the
  player from the old game); `replayGameReadyCheck` is Classic's own hook to re-run the
  start check. We call two existing features, not new machinery.
- All callbacks run through one lock, so our listener cannot interleave with another
  callback. No two players can be moved at once.
- When no waiter exists, or anything throws, the player stays put, which is exactly
  today's behaviour.
- A leftover seat-holder in the target game is bumped by Classic's own logic when the
  game starts with two ready players (that is the existing "REASSIGNING" path).

## 4. What it does NOT fix, and side effects

- **Ghosts still exist.** Their seats are simply no longer able to strand a ready player.
- **Players can change condition.** `assignPlayer` overwrites the player's treatment. The
  intro and quiz do not depend on condition (I checked `client/src/intro-exit`), and
  every player attribute is set at game start, so this is safe for the content. It does
  mean condition follows "whose game had a waiter", so condition balance is by arrival
  order. It is still random with respect to participant. Empirica logs a WARN per move
  ("reassigning player ... with different treatment"); expect these in the log.
- **Lobby timers.** The individual timer is tied to (player, game). A moved player's old
  timer is ignored and no new one starts. That is harmless if the game starts right away
  (the normal case) but a player stranded in the target game would wait with no timeout.
  Mitigation: the `readyAt < 9 min` rule makes the target waiter safe from timing out
  mid-move; and the monitor/admin will show any game with a ready player and no start.
- **Set allocation** happens at game start (`onGameStart` tally), so moves do not affect
  it.

## 5. Test plan (all before any wave)

On the VM with test treatments, or locally with `loadtest/` bots (extend a bot so its intro
can be stalled or never finished):

1. Normal path: two players finish intro in the same game. Starts. No move, no WARN.
2. Ghost: A and ghost G in the same game; B in another. A ready, then B ready -> B moves
   to A's game and it starts. G is reassigned or "no more games", not a crash.
3. Waiter at the boundary: A ready 9.5 min ago, B arrives -> no move (A will time out).
4. Three ready at once: pairs form, third waits, none is lost or double-assigned.
5. Different conditions: the pair plays the target game's condition and the exp2 set
   allocation log line shows the right set/slot.
6. Throw path: make `assignPlayer` fail (simulate) -> player stays, log line, no crash.
7. Export + `00_preprocessing.R` run cleanly on the test data; moved players' rows are
   correct (gameID, treatment).
8. Load: repeat the 10-game bot run; no slower per round (round times from `t=`).

Pass = all of the above. Any failure -> do not ship.

## 6. Rollout and rollback

- Ship as its own commit, separate from other changes, on a wave where `monitor` is
  watched live. First wave: 3 batches only.
- Rollback = revert the commit and rebundle (before a wave; never mid-wave).
- Kill switch worth adding: a `MATCHMAKER=off` environment variable read once at server
  start. It lets you turn the feature off by restarting BEFORE a wave, without
  reverting the code.

## 7. Decisions for you

1. Is cross-condition moving acceptable? (If you want to keep players within the
   condition they were assigned, restrict waiters to the same treatment; fewer matches.)
2. The 9-minute cutoff: keep, or use a shorter one (more conservative)?
3. Do you want the kill switch?
4. Is a test of the full bot harness (8 scenarios) worth the time before the next wave,
   or do you prefer to run option A first and decide with a second wave's data?
