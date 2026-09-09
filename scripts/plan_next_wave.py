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
  4. Deploy images ONLY if step 3 says some are missing, and only for the ids it
     names. The schedule is deliberately longer than any one wave -- depth-first
     allocation stops partway down it -- so most of its sets will never be
     reached, and deploying their images is wasted work.
  5. Wipe tajriba.json, create fresh batches, recruit

Coverage counts a dyad as complete when BOTH players have completedStudy true.
That is the S4.8 unit: a set needs 2 such dyads per condition to yield the
between-dyad comparison (DV6), which is what makes DV1 and DV5 interpretable.

Two hand-maintained CSVs override that test in either direction, because it is
wrong in both: --exclude-games for dyads that completed but are unusable, and
--include-games for dyads with complete data whose player never clicked the
final exit step. Pass both every time; see load_game_ids().
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

EXP = os.path.join(REPO, "experiments", "compositional-tangrams-v2")
TANGRAMS = os.path.join(EXP, "client", "public", "tangrams")
SET_FILES = [os.path.join(EXP, "server", "src", f"exp2_{k}_sets.json")
             for k in ("comp", "noncomp")]


def undeployed_sets(set_ids):
    """Of `set_ids`, those with at least one image not yet in client/public/tangrams.

    Deploying images for sets the wave will never reach is wasted work -- the
    schedule is deliberately longer than any single wave, because depth-first
    allocation just stops partway down it. So report only what is actually
    missing, and stay silent when nothing is.

    Returns None if the set files or image directory are unavailable, so the
    caller can fall back to printing the full command rather than claiming
    nothing is needed.
    """
    if not os.path.isdir(TANGRAMS):
        return None
    try:
        have = {f for f in os.listdir(TANGRAMS) if f.endswith(".png")}
        needed = defaultdict(set)
        for path in SET_FILES:
            with open(path) as f:
                doc = json.load(f)
            for st in doc["sets"]:
                sid = st["set_id"]
                if sid not in set(set_ids):
                    continue
                for key in ("training_shapes", "pretest_items",
                            "posttest_items", "heldout_wholes"):
                    for item in st.get(key, []) or []:
                        needed[sid].add(item["image"])
    except (OSError, KeyError, ValueError):
        return None
    return [sid for sid in set_ids if needed.get(sid, set()) - have]


PROLIFIC_ID = re.compile(r"^[0-9a-f]{24}$")


def is_real_participant(pid):
    """True for a genuine Prolific ID, False for server-test players.

    Test runs use hand-typed keys ("test0", "test2") and reach completedStudy
    exactly like real dyads do, so without this they consume set slots -- a set
    would read as collected when only the experimenter had been through it.

    Prolific sometimes passes the ID in email form
    (<24-hex-id>@email.prolific.com), so match on the local part.
    """
    pid = (pid or "").strip().split("@")[0].lower()
    return bool(PROLIFIC_ID.match(pid))


def load_game_ids(paths):
    """Union of the gameID column across one or more override CSVs.

    Three of these exist, covering the two directions the automatic completion
    test can be wrong:

      excluded_games.csv -- collected but unusable, HAND-ADJUDICATED. Post-hoc
        exclusions (AI use, degenerate responses) are invisible to the
        completion test: an AI-assisted dyad completes exactly like a real one.
        If they still count as coverage the set reads as finished and the
        shortfall surfaces at analysis time, after recruitment has closed.
        Listing them turns the hole back into a recruitment target.

      timeout_games.csv -- collected but unusable, DERIVED. Regenerated by
        scripts/flag_timeout_games.py from the auto-submit rate. Kept separate
        so re-running the rule can never clobber a judgment call.

      included_games.csv -- usable but not marked complete. completedStudy is
        set on the final exit step, so a dyad that played all 48 rounds and
        submitted a full posttest still reads as incomplete if one player closed
        the tab before that last click. The data is there; without this the slot
        gets recruited a second time for nothing.
    """
    if not paths:
        return set()
    if isinstance(paths, str):
        paths = [paths]
    return set().union(*(_load_one(p) for p in paths))


def load_set_ids(paths):
    """setIds the study pool must step over, from any CSV with a setId column.

    Written by scripts/flag_component_clashes.py: sets containing a displayed
    image whose top and bottom halves are near-duplicate tangrams. The set
    sampler never compared components to each other, so these got through; see
    that script for the mechanism.

    Skipping is the right response even for a set that already has partial data.
    Collecting the rest of a set whose training target is a shape stacked on
    itself just buys more contaminated dyads -- the sunk cost is sunk either way.
    """
    if not paths:
        return set()
    if isinstance(paths, str):
        paths = [paths]
    out = set()
    for path in paths:
        with open(path) as f:
            rows = list(csv.DictReader(f))
        if rows and "setId" not in rows[0]:
            raise SystemExit(f"{path}: expected a setId column, got {list(rows[0])}")
        for r in rows:
            v = (r.get("setId") or "").strip()
            if v:
                out.add(int(float(v)))
    return out


def _load_one(path):
    with open(path) as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return set()
    if "gameID" not in rows[0]:
        raise SystemExit(f"{path}: expected a gameID column, got {list(rows[0])}")
    return {r["gameID"].strip() for r in rows if r.get("gameID", "").strip()}


def load_coverage(runs, excluded_games=frozenset(), included_games=frozenset()):
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
    forced = 0
    for gid, (cond, sid) in per_game.items():
        # Exclusion wins over inclusion: a game listed in both is unusable, and
        # the safe reading of a contradiction is "recruit it again".
        if gid in excluded_games:
            dropped += 1
            continue
        # a dyad counts only if BOTH players finished, unless it is on the
        # manual include list (complete data, missing final exit click)
        if len(completed_players.get(gid, ())) >= 2:
            coverage[(cond, sid)] += 1
        elif gid in included_games:
            coverage[(cond, sid)] += 1
            forced += 1
    if dropped:
        print(f"  excluded {dropped} game(s) listed in --exclude-games; "
              f"their slots read as open", file=sys.stderr)
    if forced:
        print(f"  counted {forced} game(s) listed in --include-games that the "
              f"completedStudy test missed", file=sys.stderr)
    if excluded:
        print(f"  excluded {len(excluded)} test participant(s): "
              f"{', '.join(sorted(excluded))}", file=sys.stderr)
    return coverage, per_game, completed_players


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n-sets", type=int, default=8,
                    help="SIZE OF THE STUDY POOL: total distinct sets the whole "
                         "study will use, including ones already complete. The "
                         "schedule written is this pool minus the finished sets, "
                         "so it shrinks as collection proceeds and never pulls "
                         "in sets beyond the pool.")
    ap.add_argument("--per-set", type=int, default=2,
                    help="target dyads per condition per set (default 2, per S4.8)")
    ap.add_argument("--pool", type=int, default=500,
                    help="(unused; the candidate pool is the 500 sets in the "
                         "stimulus files and --n-sets selects from its front)")
    ap.add_argument("--runs", nargs="*", default=None,
                    help="processed run folders to count (default: all exp2_*)")
    ap.add_argument("--write", action="store_true",
                    help="write the new schedule; otherwise just report")
    ap.add_argument("--exclude-games", nargs="*", default=None,
                    help="one or more CSVs with a gameID column; those dyads do "
                         "not count as collected. Use for games excluded post "
                         "hoc (AI use, degenerate responses, timed-out phases) "
                         "so the shortfall they leave is recruited back rather "
                         "than silently lost. Pass excluded_games.csv AND "
                         "timeout_games.csv.")
    ap.add_argument("--include-games", nargs="*", default=None,
                    help="CSV with a gameID column; those dyads count as "
                         "collected even though completedStudy is not true for "
                         "both players. Use for games with complete data whose "
                         "player never clicked the final exit step, so the slot "
                         "is not recruited a second time for nothing.")
    ap.add_argument("--skip-sets", nargs="*", default=None,
                    help="one or more CSVs with a setId column; those sets are "
                         "stepped over when building the study pool, so the "
                         "pool still holds --n-sets USABLE sets. Written by "
                         "scripts/flag_component_clashes.py.")
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
        runs,
        load_game_ids(args.exclude_games),
        load_game_ids(args.include_games))
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
    # --n-sets is the size of the STUDY POOL: the total number of distinct sets
    # the whole study will ever use, INCLUDING ones already finished. It is not
    # "how many more to collect".
    #
    # That distinction matters for disk. Treating it as "75 still to collect"
    # slides the window forward every time a set completes (0-74, then 3-77,
    # then 5-79...), so each wave pulls in sets never seen before and each needs
    # its images deployed -- unbounded growth for no scientific gain. A fixed
    # pool is deployed once and never grows.
    #
    # Skipped sets are stepped OVER, not counted: --n-sets 75 always means 75
    # USABLE sets, so the pool walks 0, 1, 2, ... skipping flagged ids until it
    # has that many. Counting them would silently shrink the study.
    skip = load_set_ids(args.skip_sets)
    study_pool, sid = [], 0
    while len(study_pool) < args.n_sets:
        if sid not in skip:
            study_pool.append(sid)
        sid += 1
        if sid > 100000:                       # the set file is finite
            raise SystemExit("ran out of set ids building the study pool")
    if skip:
        skipped_in_range = sorted(s for s in skip if s < study_pool[-1])
        print(f"\n  skipping {len(skipped_in_range)} flagged set(s) below the pool "
              f"ceiling: {skipped_in_range}", file=sys.stderr)
        print(f"  pool therefore runs 0-{study_pool[-1]} to reach {args.n_sets} "
              f"usable sets", file=sys.stderr)
        stranded = sorted(s for s, _ in partial if s in skip)
        if stranded:
            print(f"  NOTE: {len(stranded)} skipped set(s) already have partial "
                  f"data and will never be finished: {stranded}", file=sys.stderr)

    partial_ids = {sid for sid, _ in partial}

    # Finish partially-collected sets before opening new ones -- same depth-first
    # logic the runtime allocator uses, and for the same reason: a set with one
    # dyad contributes nothing to the between-dyad comparison.
    resume = [s for s in study_pool if s in partial_ids]
    fresh = [s for s in study_pool if s not in finished and s not in partial_ids]
    next_sets = resume + fresh

    if not next_sets:
        print(f"\n  ALL {args.n_sets} sets in the study pool are COMPLETE. "
              f"Collection is finished -- widen --n-sets only if you want a "
              f"bigger corpus.")
        return

    in_pool = set(study_pool)
    print(f"\n  complete sets: {len([s for s in finished if s in in_pool])}"
          f"   partially collected: {len(resume)}")
    print(f"\n  STUDY POOL: {args.n_sets} sets "
          f"({study_pool[0]}-{study_pool[-1]}"
          + (f", {len([s for s in skip if s < study_pool[-1]])} skipped" if skip else "")
          + f"); {len([s for s in finished if s in in_pool])} complete, "
          + f"{len(next_sets)} still open")
    print(f"  NEXT WAVE schedule ({len(next_sets)} sets): {next_sets}")
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

    # Only ever suggest deploying sets whose images are actually missing.
    missing = undeployed_sets(next_sets)
    if missing is None:
        print(f"\n  could not check deployed images; if any of these sets are new:\n"
              f"    python3 scripts/deploy_exp2_images.py --set-ids {','.join(map(str, next_sets))}")
    elif missing:
        print(f"\n  {len(missing)} of these {len(next_sets)} sets have images missing. "
              f"Deploy just those:\n"
              f"    python3 scripts/deploy_exp2_images.py --set-ids {','.join(map(str, missing))}")
    else:
        print(f"\n  images: all {len(next_sets)} sets already deployed -- nothing to do.")

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
