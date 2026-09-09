#!/usr/bin/env python3
"""Flag games where a player let the per-item clock run out on most of the phase.

WHY
---
Each description item has its own countdown (`describeSecondsPerItem`, currently
60s). When it expires the answer is saved as-is and flagged `autoSubmitted`. One
or two of those is a thorough writer running long. A player who does it on most
of their items was not at the keyboard while the clock ran -- reading the shape
off a second screen, tabbed away, or not engaging with the task -- and their
descriptions are not a measurement of what the design intends to measure.

This is the rule-based half of the exclusion story, kept SEPARATE from
excluded_games.csv on purpose:

  excluded_games.csv   hand-adjudicated. AI use, degenerate responses. Judgment.
  timeout_games.csv    derived. Recomputed from the data every time this runs.

Keeping them apart means re-running this can never clobber a judgment call, and
a threshold change is a re-run rather than a hand edit of curated rows.

The screen is PER PLAYER, not per game: one partner who was away contaminates
the dyad, and averaging the two would let an attentive partner mask them.

Usage:
    python3 scripts/flag_timeout_games.py                    # report only
    python3 scripts/flag_timeout_games.py --write            # write the CSV
    python3 scripts/flag_timeout_games.py --threshold 0.6    # try another cut

Then pass the result everywhere excluded_games.csv is passed:
    --exclude-games data/processed_data/exp_2/excluded_games.csv \\
                    data/processed_data/exp_2/timeout_games.csv
"""

import argparse
import csv
import datetime
import glob
import os
import sys
from collections import defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROCESSED = os.path.join(REPO, "data", "processed_data", "exp_2")
OUT = os.path.join(PROCESSED, "timeout_games.csv")

TRUTHY = ("TRUE", "T", "1")


def is_auto(row):
    return str(row.get("autoSubmitted", "")).strip().upper() in TRUTHY


def load_descriptions():
    """Every description row across every wave, deduplicated.

    Waves are re-exported (a full study export repeats earlier waves), so the
    same item appears in several folders. Keying on
    (playerID, phase, order, image) makes this idempotent -- counting rows would
    inflate both the numerator and the denominator unpredictably.
    """
    seen, rows = set(), []
    for path in sorted(glob.glob(os.path.join(PROCESSED, "**", "descriptions.csv"),
                                 recursive=True)):
        with open(path) as f:
            for r in csv.DictReader(f):
                key = (r.get("playerID"), r.get("phase"), r.get("order"), r.get("image"))
                if key in seen:
                    continue
                seen.add(key)
                rows.append(r)
    return rows


def game_meta():
    meta = {}
    for path in sorted(glob.glob(os.path.join(PROCESSED, "**", "games.csv"),
                                 recursive=True)):
        with open(path) as f:
            for r in csv.DictReader(f):
                meta.setdefault(r["gameID"], r)
    return meta


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--threshold", type=float, default=0.75,
                    help="flag a player whose auto-submitted share EXCEEDS this "
                         "(default 0.75)")
    ap.add_argument("--min-items", type=int, default=8,
                    help="ignore players with fewer items than this (default 8, "
                         "the shortest real phase). Without it a player who "
                         "abandoned after 2 items reads as 100%%.")
    ap.add_argument("--write", action="store_true",
                    help="write timeout_games.csv; otherwise just report")
    args = ap.parse_args()

    rows = load_descriptions()
    if not rows:
        sys.exit(f"no descriptions.csv under {PROCESSED}")
    if "autoSubmitted" not in rows[0]:
        sys.exit("descriptions.csv has no autoSubmitted column -- re-run "
                 "analysis/exp2/00_preprocessing.R")

    per_player = defaultdict(lambda: [0, 0])          # (gameID, playerID) -> [auto, n]
    for r in rows:
        slot = per_player[(r["gameID"], r["playerID"])]
        slot[1] += 1
        if is_auto(r):
            slot[0] += 1

    meta = game_meta()
    flagged = {}
    skipped_small = 0
    for (gid, pid), (auto, n) in sorted(per_player.items()):
        if n < args.min_items:
            if auto / n > args.threshold:
                skipped_small += 1
            continue
        share = auto / n
        if share <= args.threshold:
            continue
        # Worst player wins: the reason should name the one that tripped it.
        if gid not in flagged or share > flagged[gid][0]:
            flagged[gid] = (share, pid, auto, n)

    print(f"  {len(per_player)} player(s) across {len(meta)} game(s); "
          f"threshold >{args.threshold:.0%} auto-submitted, min {args.min_items} items")
    if skipped_small:
        print(f"  {skipped_small} player(s) over the threshold but under "
              f"--min-items, not flagged")
    if not flagged:
        print("  no games flagged.")
    for gid, (share, pid, auto, n) in sorted(flagged.items(),
                                             key=lambda kv: -kv[1][0]):
        g = meta.get(gid, {})
        print(f"  {gid}  {share:>4.0%}  ({auto}/{n})  {g.get('contextStructure','?')} "
              f"set{g.get('setId','?')}  {g.get('status','?')}/{g.get('endedReason','?')}")

    if not args.write:
        print("\n  (report only -- pass --write to update timeout_games.csv)")
        return

    today = datetime.date.today().isoformat()
    with open(OUT, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["gameID", "reason", "found"])
        for gid, (share, pid, auto, n) in sorted(flagged.items()):
            w.writerow([gid,
                        f"timed-out phase: player {pid} auto-submitted {auto} of "
                        f"{n} description items ({share:.0%}) at the per-item cap; "
                        f"screen is >{args.threshold:.0%} (flag_timeout_games.py)",
                        today])
    print(f"\n  wrote {len(flagged)} row(s) to {os.path.relpath(OUT, REPO)}")
    print("  this file is DERIVED -- regenerate it, do not hand-edit. "
          "Judgment calls belong in excluded_games.csv.")


if __name__ == "__main__":
    main()
