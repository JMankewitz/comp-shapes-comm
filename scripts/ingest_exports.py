#!/usr/bin/env python3
"""Pull any new Empirica exports off the VM and unpack each into its own folder.

WHY
---
Organising zips into "the right" run folder by hand is fiddly, and the pressure to
get it right discourages exporting often -- which means participants wait for
payment until a whole wave finishes.

You do not have to get it right. `plan_next_wave.py` deduplicates coverage by
Empirica ULID, so overlapping exports, re-exports of the same wave, and one folder
per export are all safe. That makes the correct policy the easy one: **export as
often as you like, ingest everything, pay people promptly.**

So this names folders automatically from the export timestamp already in the zip
filename (compShapesV1-2026-08-25-02-21-47.zip -> exp_2/pilot_v1/2026-08-25-02-21-47),
which is unique, sortable, and needs no decisions. Already-ingested zips are
skipped, so re-running is cheap and idempotent.

NAMING
------
Layout is `exp_2/<study>/<wave>`, and the two levels carry different jobs:

  <study>  semantic, chosen by you, free-form: pilot_v1, full_v1, full_v2.
           This is what records which PHASE a wave belongs to. Rename these
           freely -- nothing parses them.
  <wave>   the export timestamp. Unique, sortable, and taken from the zip name
           rather than invented, so "newest" is unambiguous.

Resist putting phase information in the wave name. Mixing semantic and
timestamped names at the same level is what broke "latest" ordering before
(`run_1` sorted above `2026-08-25-...`) and caused a wave to be paid twice.

Usage:
    python3 scripts/ingest_exports.py --into pilot_v1
    python3 scripts/ingest_exports.py --into pilot_v1 --dry-run
    python3 scripts/ingest_exports.py --into full_v1 --preprocess
    python3 scripts/ingest_exports.py --into pilot_v1 --no-fetch --preprocess
"""

import argparse
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(REPO, "data", "raw_data", "exp_2")
PROJECT = "hs-social-interaction-lab"
HOST = "social-interaction-lab-small-runs"
ZONE = "us-central1-f"
REMOTE_DIR = "~/comp-shapes-comm/experiments/compositional-tangrams-v2"
STAMP = re.compile(r"compShapesV1-(\d{4}-\d\d-\d\d-\d\d-\d\d-\d\d)\.zip$")


def sh(cmd, **kw):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, **kw)


def remote_zips():
    r = sh(f'gcloud compute ssh {HOST} --zone={ZONE} --project={PROJECT} '
           f'--ssh-flag="-o ConnectTimeout=20" --command="ls -1 {REMOTE_DIR}/*.zip 2>/dev/null"')
    if r.returncode != 0:
        sys.exit(f"could not list exports on the VM:\n{r.stderr.strip()}")
    return [os.path.basename(l.strip()) for l in r.stdout.splitlines() if l.strip().endswith(".zip")]


def folder_for(zipname):
    m = STAMP.search(zipname)
    if not m:
        return None
    return m.group(1)   # e.g. 2026-08-25-02-21-47


def ingested_under(folder):
    """The study folder this export is ALREADY ingested under, or None.

    An export timestamp is globally unique -- it names one moment on one server
    -- so the same zip must never land in two study folders. The check has to
    span ALL studies, not just the target one: on the day pilot_v1 gave way to
    full_sample, every pilot zip was still sitting on the VM and looked brand new
    to a per-study check, so all six were re-downloaded into the new study.
    """
    if not os.path.isdir(RAW):
        return None
    for study in sorted(os.listdir(RAW)):
        d = os.path.join(RAW, study, folder)
        if os.path.isdir(d) and any(f.endswith(".csv") for f in os.listdir(d)):
            return study
    return None


def processed_dir(study, folder):
    return os.path.join(REPO, "data", "processed_data", "exp_2", study, folder)


# The LAST file 00_preprocessing.R writes. Using the last output as the sentinel
# means a folder processed by an older version of the script -- which stopped
# before this file existed -- is correctly seen as needing another pass. Gating
# on games.csv instead would call those folders done and silently skip them.
DONE_MARKER = "payments.csv"


def needs_preprocess(study, folder):
    """True unless the processed folder holds a COMPLETE preprocessing run.

    Preprocessing creates its output directory before it writes, so a run that
    failed leaves an empty directory behind. Testing for the directory would
    call that done; test for the last file it writes.
    """
    return not os.path.exists(os.path.join(processed_dir(study, folder), DONE_MARKER))


def run_preprocess(study, folder):
    # 00_preprocessing.R takes the run name from a variable at the top; override
    # it for this folder without editing the file. It must be the path RELATIVE
    # TO exp_2/, i.e. <study>/<wave> -- the script uses the same string for both
    # raw and processed, so a bare timestamp silently reads a nonexistent raw
    # folder and leaves an empty processed one behind.
    script = os.path.join(REPO, "analysis", "exp2", "00_preprocessing.R")
    r = sh(f'cd "{REPO}" && Rscript -e '
           f'\'target_experiment_name <- "{study}/{folder}"; '
           f'source("{script}", echo = FALSE)\'')
    tail = [l for l in r.stdout.splitlines() + r.stderr.splitlines()
            if l.startswith("games:") or l.startswith("descriptions:")]
    # Check the marker FIRST. Those log lines are printed partway through, so a
    # run that crashed after them would otherwise be reported as a success.
    if not needs_preprocess(study, folder):
        print(f"    {folder}: " + ("; ".join(tail) if tail else "preprocessed"))
    else:
        err = [l for l in (r.stderr or r.stdout).strip().splitlines()
               if l.startswith("Error") or "not found" in l or "does not exist" in l]
        if not err:
            err = (r.stderr or r.stdout).strip().splitlines()
        print(f"    {folder}: FAILED -- {err[-1][:160] if err else 'no output'}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    # Deliberately NO default. The study folder is the only thing recording
    # which phase a wave belongs to -- the timestamp cannot tell pilot from full
    # study. A default means the first full-study export where the flag is
    # forgotten lands silently in pilot_v1 and the two become unseparable.
    ap.add_argument("--into", required=True, metavar="STUDY",
                    help="study subfolder under data/raw_data/exp_2/ "
                         "(layout is exp_2/<study>/<wave>), e.g. pilot_v1, full_v1")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-fetch", action="store_true",
                    help="skip the VM entirely and work from raw folders already "
                         "on disk (use with --preprocess to backfill)")
    ap.add_argument("--reprocess", action="store_true",
                    help="re-run preprocessing even for waves that already have "
                         "complete output (use after changing 00_preprocessing.R)")
    ap.add_argument("--preprocess", action="store_true",
                    help="run analysis/exp2/00_preprocessing.R for each new folder")
    args = ap.parse_args()

    # A typo in --into silently opens a new study rather than failing, which
    # would scatter one wave's data across two folders. Requiring the flag stops
    # the wrong-default problem; announcing new folders stops the typo problem.
    base = os.path.join(RAW, args.into)
    if not os.path.isdir(base):
        existing = sorted(d for d in (os.listdir(RAW) if os.path.isdir(RAW) else [])
                          if os.path.isdir(os.path.join(RAW, d)))
        print(f"NOTE: '{args.into}' is a new study folder"
              + (f" (existing: {', '.join(existing)})" if existing else "")
              + "\n      If that was a typo, ctrl-C now.\n")

    if args.no_fetch:
        # Work from what is already on disk. Re-preprocessing an old wave should
        # not depend on the VM still being up, or on its zips still being there.
        base = os.path.join(RAW, args.into)
        have = sorted(
            d for d in (os.listdir(base) if os.path.isdir(base) else [])
            if os.path.isdir(os.path.join(base, d))
            and any(f.endswith(".csv") for f in os.listdir(os.path.join(base, d)))
        )
        new = []
        print(f"--no-fetch: {len(have)} ingested wave(s) on disk under exp_2/{args.into}")
        for f in have:
            print(f"  ok {f}")
    else:
        zips = remote_zips()
        if not zips:
            print("No exports found on the VM. Run `empirica export` there first "
                  "(from ~/comp-shapes-comm/experiments/compositional-tangrams-v2).")
            return
        print(f"exports on the VM: {len(zips)}")

        new, have = [], []
        for z in sorted(zips):
            folder = folder_for(z)
            if not folder:
                print(f"  ?  {z}  (unrecognised name, skipping)")
                continue
            dest = os.path.join(RAW, args.into, folder)
            # Already ingested ANYWHERE, not just under --into.
            where = ingested_under(folder)
            if where == args.into:
                print(f"  ok {z}  -> {folder} (already ingested)")
                have.append(folder)
                continue
            if where is not None:
                print(f"  -- {z}  already ingested under '{where}', skipping "
                      f"(would duplicate it into '{args.into}')")
                continue
            print(f"  NEW {z}  -> data/raw_data/exp_2/{args.into}/{folder}")
            new.append((z, folder, dest))

    # Ingesting and preprocessing are tracked separately. A folder can be fully
    # ingested but unprocessed -- that is exactly what happens when preprocessing
    # errors, or when it ran before a bug in how it was invoked was fixed -- and
    # in that state coverage silently reads as zero.
    stale = [f for f in have if needs_preprocess(args.into, f)]

    if not new and not (args.preprocess and (stale or args.reprocess)):
        print("\nNothing new. Coverage is deduplicated by ULID, so re-ingesting "
              "would have been harmless anyway.")
        if stale:
            print(f"\nBUT {len(stale)} ingested wave(s) have no processed games.csv, so "
                  f"they count as zero coverage:\n  " + "\n  ".join(stale) +
                  "\n\nRe-run with --preprocess to fill them in.")
        return
    if args.dry_run:
        print(f"\n--dry-run: would ingest {len(new)}")
        if args.preprocess:
            todo = stale + [f for _, f, _ in new]
            print(f"--dry-run: would preprocess {len(todo)}: {todo}")
        return

    ingested = []
    for z, folder, dest in new:
        os.makedirs(dest, exist_ok=True)
        print(f"\n==> {folder}")
        r = sh(f'gcloud compute scp --zone={ZONE} --project={PROJECT} '
               f'"{HOST}:{REMOTE_DIR}/{z}" "{dest}/"')
        if r.returncode != 0:
            print(f"    scp FAILED: {r.stderr.strip()[:200]}")
            continue
        r = sh(f'cd "{dest}" && unzip -o -q "{z}"')
        if r.returncode != 0:
            print(f"    unzip FAILED: {r.stderr.strip()[:200]}")
            continue
        csvs = sorted(f for f in os.listdir(dest) if f.endswith(".csv"))
        print(f"    unpacked {len(csvs)} csvs")
        ingested.append(folder)

    if args.preprocess:
        # Everything lacking a processed games.csv, whether it arrived just now
        # or in an earlier run. Preprocessing is idempotent, so the only cost of
        # including an older wave is a few seconds.
        if args.reprocess:
            todo = sorted(set(have) | set(ingested))
        else:
            todo = stale + [f for f in ingested if needs_preprocess(args.into, f)]
        if not todo:
            print("\nAll ingested waves already preprocessed.")
        else:
            print(f"\npreprocessing {len(todo)} wave(s):")
            for folder in todo:
                run_preprocess(args.into, folder)

    print("\nNext:")
    print("  payments: the paste-ready lists are printed above by preprocessing,")
    print("            and the full table is payments.csv in each processed folder")
    print("  python3 scripts/plan_next_wave.py --n-sets 75  # coverage across ALL runs")


if __name__ == "__main__":
    main()
