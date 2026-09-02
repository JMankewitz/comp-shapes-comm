#!/usr/bin/env python3
"""Pick the stimulus sets for the NEXT recruitment wave, from data already collected.

WHY THIS EXISTS
---------------
The cross-batch set tally lives in Empirica's global scope, i.e. inside
`tajriba.json`. That file grows ~0.5 MB/min and has to be wiped between waves to
manage disk, which destroys the tally -- so the next wave would restart at set 0
and re-collect sets that are already done.

The fix is to stop treating tajriba as the record of coverage. It is ephemeral
state for ONE wave. The durable record is the accumulated data exports, and that
is a strictly better source: the tally counts games *started*, whereas this counts
dyads that actually *completed*. A wave where a dyad timed out leaves that slot
genuinely open rather than falsely consumed.

WORKFLOW PER WAVE
-----------------
  1. `empirica export` on the VM, then `scripts/ingest_exports.py --into <study>`
  2. That ingests + preprocesses; or run analysis/exp2/00_preprocessing.R yourself
  3. python3 scripts/plan_next_wave.py --n-sets 8
     -> reports coverage so far, writes the next wave's schedule
  4. python3 scripts/deploy_exp2_images.py --set-ids <the ids it printed>
  5. Wipe tajriba.json, create fresh batches, recruit

Coverage counts a dyad as complete when BOTH players have completedStudy true.
That is the S4.8 unit: a set needs 2 such dyads per condition to yield the
between-dyad comparison (DV6), which is what makes DV1 and DV5 interpretable.
"""

import argparse
import csv
import re
import glob
import json
import os
import sys
from collections import defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROCESSED = os.path.join(REPO, "data", "processed_data", "exp_2")
SCHEDULE = os.path.join(
    REPO, "experiments", "compositional-tangrams-v2", "server", "src",
    "exp2_set_schedule.json",
)
CONDITIONS = ["comp-within", "comp-between", "noncomp"]


PROLIFIC_ID = re.compile(r"^[0-9a-f]{24}$")


def is_real_participant(pid):
    """True for a genuine Prolific ID, False for server-test players.

    Test runs use hand-typed keys ("test0", "test2") and reach completedStudy
    exactly like real dyads do, so without this they consume set slots -- a set
    would read as collected when only the experimenter had been through it.

    Prolific sometimes passes the ID in email form
    (69c2a1ca204d43b99f204424@email.prolific.com), so match on the local part.
    """
    pid = (pid or "").strip().split("@")[0].lower()
    return bool(PROLIFIC_ID.match(pid))


def load_excluded_games(path):
    """gameIDs that must not count as collected.

    Post-hoc exclusions (AI use, degenerate responses) are invisible to the
    completion test -- an AI-assisted dyad completes exactly like a real one. If
    they still count as coverage, the set reads as finished and the shortfall is
    only discovered at analysis time, after recruitment has closed. Feeding them
    back here turns the hole into a recruitment target instead.
    """
    if not path:
        return set()
    with open(path) as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return set()
    if "gameID" not in rows[0]:
        raise SystemExit(f"{path}: expected a gameID column, got {list(rows[0])}")
    return {r["gameID"].strip() for r in rows if r.get("gameID", "").strip()}


def load_coverage(runs, excluded_games=frozenset()):
    """(condition, setId) -> number of dyads with BOTH players completed.

    Everything is keyed on the Empirica ULIDs (gameID, playerID), which are unique
    per game/player for all time. That makes this idempotent: exporting the same
    wave twice, or re-processing an old run alongside a new one, cannot inflate
    coverage. Counting player ROWS instead would be unsafe -- a double export of a
    game where only one partner finished would count as two and falsely mark the
    dyad complete.
    """
    per_game = {}                              # gameID -> (condition, setId)
    excluded = set()                           # test prolificIDs seen
    completed_players = defaultdict(set)       # gameID -> {playerID, ...}

    for run in runs:
        gpath = os.path.join(PROCESSED, run, "games.csv")
        ppath = os.path.join(PROCESSED, run, "players.csv")
        if not (os.path.exists(gpath) and os.path.exists(ppath)):
            print(f"  skipping {run}: no processed games.csv/players.csv", file=sys.stderr)
            continue
        with open(gpath) as f:
            for row in csv.DictReader(f):
                try:
                    per_game[row["gameID"]] = (row["contextStructure"], int(float(row["setId"])))
                except (KeyError, ValueError):
                    continue
        with open(ppath) as f:
            for row in csv.DictReader(f):
                if str(row.get("completedStudy", "")).strip().upper() not in ("TRUE", "1"):
                    continue
                if not is_real_participant(row.get("prolificID", "")):
                    excluded.add(row.get("prolificID", ""))
                    continue
                pid = row.get("playerID") or row.get("id")
                if pid:
                    completed_players[row.get("gameID")].add(pid)

    coverage = defaultdict(int)
    dropped = 0
    for gid, (cond, sid) in per_game.items():
        if gid in excluded_games:
            dropped += 1
            continue
        # a dyad counts only if BOTH players finished
        if len(completed_players.get(gid, ())) >= 2:
            coverage[(cond, sid)] += 1
    if dropped:
        print(f"  excluded {dropped} game(s) listed in --exclude-games; "
              f"their slots read as open", file=sys.stderr)
    if excluded:
        print(f"  excluded {len(excluded)} test participant(s): "
              f"{', '.join(sorted(excluded))}", file=sys.stderr)
    return coverage, per_game, completed_players


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n-sets", type=int, default=8,
                    help="how many sets the next wave should cover")
    ap.add_argument("--per-set", type=int, default=2,
                    help="target dyads per condition per set (default 2, per S4.8)")
    ap.add_argument("--pool", type=int, default=500,
                    help="size of the full candidate pool to draw from")
    ap.add_argument("--runs", nargs="*", default=None,
                    help="processed run folders to count (default: all exp2_*)")
    ap.add_argument("--write", action="store_true",
                    help="write the new schedule; otherwise just report")
    ap.add_argument("--exclude-games", default=None,
                    help="CSV with a gameID column; those dyads do not count as "
                         "collected. Use for games excluded post hoc (AI use, "
                         "degenerate responses) so the shortfall they leave is "
                         "recruited back rather than silently lost.")
    args = ap.parse_args()

    # Every run folder under data/processed_data/exp_2/. No naming convention is
    # required: coverage is deduplicated by ULID, so overlapping or re-exported
    # runs cannot inflate counts.
    # Any folder containing games.csv, at any depth under processed_data/exp_2.
    # The layout is <study>/<wave> (e.g. pilot_v1/run_1) but nothing here depends
    # on that: coverage is deduplicated by ULID, so extra or overlapping folders
    # are harmless.
    runs = args.runs or sorted(
        os.path.relpath(os.path.dirname(g), PROCESSED)
        for g in glob.glob(os.path.join(PROCESSED, "**", "games.csv"), recursive=True)
    )
    if not runs:
        print("No processed runs found under data/processed_data/exp_2. Nothing collected yet; "
              "the current schedule stands.", file=sys.stderr)
        return

    print(f"counting coverage across: {', '.join(runs)}")
    coverage, per_game, completed = load_coverage(
        runs, load_excluded_games(args.exclude_games))
    print(f"  {len(per_game)} distinct games, "
          f"{sum(len(v) for v in completed.values())} distinct completed players "
          f"(deduplicated by ULID -- re-exports are safe)\n")

    # A set is DONE when every condition has its full complement.
    touched = sorted({sid for (_, sid) in coverage})
    done, partial = [], []
    for sid in touched:
        counts = {c: coverage.get((c, sid), 0) for c in CONDITIONS}
        (done if all(v >= args.per_set for v in counts.values()) else partial).append((sid, counts))

    print(f"{'set':>5}  " + "  ".join(f"{c:>13}" for c in CONDITIONS) + "   status")
    for sid, counts in sorted(done + partial):
        status = "COMPLETE" if all(v >= args.per_set for v in counts.values()) else "partial"
        print(f"{sid:>5}  " + "  ".join(f"{counts[c]:>13}" for c in CONDITIONS) + f"   {status}")

    finished = {sid for sid, _ in done}
    # Finish partially-collected sets before opening new ones -- same depth-first
    # logic the runtime allocator uses, and for the same reason: a set with one
    # dyad contributes nothing to the between-dyad comparison.
    resume = [sid for sid, _ in sorted(partial)]
    fresh = [s for s in range(args.pool) if s not in finished and s not in set(resume)]
    next_sets = (resume + fresh)[: args.n_sets]

    print(f"\n  complete sets: {len(finished)}   partially collected: {len(resume)}")
    print(f"\n  NEXT WAVE ({args.n_sets} sets): {next_sets}")
    if resume:
        print(f"    (resuming {len([s for s in next_sets if s in set(resume)])} partially-collected "
              f"set(s) first, so pairs get finished rather than scattered)")
    still_needed = {
        c: sum(max(0, args.per_set - coverage.get((c, s), 0)) for s in next_sets)
        for c in CONDITIONS
    }
    print("\n  dyads still needed next wave: " +
          ", ".join(f"{c} {n}" for c, n in still_needed.items()) +
          f"  (total {sum(still_needed.values())})")

    print(f"\n  deploy their images with:\n"
          f"    python3 scripts/deploy_exp2_images.py --set-ids {','.join(map(str, next_sets))}")

    if not args.write:
        print("\n  (report only -- pass --write to update exp2_set_schedule.json)")
        return

    # Per-(condition, set) targets: how many dyads each cell STILL needs, rather
    # than one flat number for every cell. Without this a set that is short by a
    # single dyad -- a timeout, or a dyad excluded post hoc -- gets recruited as
    # if it were empty, and a set that is finished keeps attracting arrivals.
    #
    # 0 means "done, do not assign here"; the set stays in set_ids so set_index
    # remains stable across waves.
    targets = {}
    for cond in CONDITIONS:
        targets[cond] = {
            str(sid): max(0, args.per_set - coverage.get((cond, sid), 0))
            for sid in next_sets
        }

    with open(SCHEDULE) as f:
        sched = json.load(f)
    sched["schema_version"] = "exp2-schedule-2"
    sched["set_ids"] = next_sets
    sched["targets"] = targets
    sched["selection"] = {"method": "uncollected", "n_sets": args.n_sets,
                          "derived_from_runs": runs}
    sched["notes"] = ("Set ids for THIS wave only, derived from completed dyads in prior "
                      "runs. tajriba.json is ephemeral and may be wiped between waves; "
                      "coverage is tracked in the data exports, not the runtime tally. "
                      "`targets` gives the REMAINING dyads per condition per set; 0 means "
                      "that cell is finished. Requires a server bundle that understands "
                      "exp2-schedule-2 -- an older one throws on load rather than "
                      "ignoring the targets.")
    with open(SCHEDULE, "w") as f:
        json.dump(sched, f, indent=2)
        f.write("\n")
    print(f"\n  wrote {os.path.relpath(SCHEDULE, REPO)}")


if __name__ == "__main__":
    main()
