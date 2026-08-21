#!/usr/bin/env python3
"""Pick the Experiment 2 stimulus-set pool and deploy only the images it needs.

Two steps, both reproducible:

  1. Choose `--n-sets` set_ids out of the 500 in exp2_{comp,noncomp}_sets.json and
     write them to server/src/exp2_set_schedule.json. callbacks.js reads that file
     to assign sets to dyads, so the pool is auditable and reruns are identical.

  2. Copy every image those sets reference (training_shapes, pretest_items,
     posttest_items, heldout_wholes -- both condition files) from the TRANSPARENT
     source pool into client/public/tangrams/.

Copying all 500 sets would be ~99 MB; the pilot needs 8 sets and the full study
~75 (design doc S4.8).

Comp set N and noncomp set N are paired (set_id == comp_set_id for all 500), and
their post-test items are the same 20 images. Selecting a set_id always deploys
both halves of the pair, so all three conditions post-test on identical shapes.

Usage:
    python3 scripts/deploy_exp2_images.py --n-sets 8              # pilot
    python3 scripts/deploy_exp2_images.py --n-sets 75             # full study
    python3 scripts/deploy_exp2_images.py --n-sets 8 --dry-run
    python3 scripts/deploy_exp2_images.py --n-sets 8 --select random --seed 20260821
"""

import argparse
import filecmp
import json
import random
import shutil
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EXP = REPO / "experiments" / "compositional-tangrams-v2"

COMP_SETS = EXP / "server" / "src" / "exp2_comp_sets.json"
NONCOMP_SETS = EXP / "server" / "src" / "exp2_noncomp_sets.json"
SCHEDULE_OUT = EXP / "server" / "src" / "exp2_set_schedule.json"

# The TRANSPARENT set is what the client renders. compositional-white is model
# input only -- do not deploy it.
DEFAULT_SOURCE = (
    REPO / "stimuli" / "generate_tangrams" / "data" / "processed_tangrams"
    / "compositional-transparent"
)
DEFAULT_DEST = EXP / "client" / "public" / "tangrams"

# Every key under a set object that holds a list of {image: ...} entries.
IMAGE_BEARING_KEYS = (
    "training_shapes",
    "pretest_items",
    "posttest_items",
    "heldout_wholes",  # noncomp only
)

# Present in both condition files; lower is less confusable.
QUALITY_CRITERION = "max_full_cross_scored"

SCHEMA_VERSION = "exp2-schedule-1"


def load_sets(path):
    with open(path) as f:
        doc = json.load(f)
    if doc.get("schema_version") != "exp2-1":
        sys.exit(f"{path.name}: expected schema_version 'exp2-1', got {doc.get('schema_version')!r}")
    return doc, {s["set_id"]: s for s in doc["sets"]}


def check_pairing(comp_by_id, noncomp_by_id):
    """The build depends on comp/noncomp set_ids lining up. Fail loudly if not."""
    if set(comp_by_id) != set(noncomp_by_id):
        sys.exit("comp and noncomp files do not cover the same set_ids")
    for sid, n in noncomp_by_id.items():
        if n.get("comp_set_id") != sid:
            sys.exit(f"noncomp set {sid} points at comp_set_id {n.get('comp_set_id')}, expected {sid}")
        c_imgs = {i["image"] for i in comp_by_id[sid]["posttest_items"]}
        n_imgs = {i["image"] for i in n["posttest_items"]}
        if c_imgs != n_imgs:
            sys.exit(f"set {sid}: noncomp post-test images differ from paired comp set")


def select_set_ids(comp_by_id, noncomp_by_id, n_sets, method, seed):
    all_ids = sorted(comp_by_id)
    if n_sets > len(all_ids):
        sys.exit(f"asked for {n_sets} sets, only {len(all_ids)} exist")

    if method == "random":
        rng = random.Random(seed)
        return sorted(rng.sample(all_ids, n_sets))

    # "best": least confusable first. Score a set_id by the worse (higher) of its
    # comp and noncomp similarity, so a pair is only as good as its weaker half.
    def score(sid):
        return max(
            comp_by_id[sid]["similarity"][QUALITY_CRITERION],
            noncomp_by_id[sid]["similarity"][QUALITY_CRITERION],
        )

    ranked = sorted(all_ids, key=lambda sid: (score(sid), sid))
    return sorted(ranked[:n_sets])


def images_for(set_ids, by_id):
    imgs = set()
    for sid in set_ids:
        s = by_id[sid]
        for key in IMAGE_BEARING_KEYS:
            for item in s.get(key, []):
                imgs.add(item["image"])
    return imgs


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--n-sets", type=int, required=True, help="8 for the pilot, ~75 for the full study")
    p.add_argument("--select", choices=("best", "random"), default="best",
                   help="'best' = lowest max similarity (default); 'random' = seeded uniform sample")
    p.add_argument("--seed", type=int, default=20260821, help="only used with --select random")
    p.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    p.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    p.add_argument("--schedule-out", type=Path, default=SCHEDULE_OUT)
    p.add_argument("--no-overwrite-mismatched", action="store_true",
                   help="leave already-deployed images alone even if they are not the "
                        "transparent variant (produces a visually mixed pool -- not recommended)")
    p.add_argument("--dry-run", action="store_true", help="report what would be copied, copy nothing")
    args = p.parse_args()

    if not args.source.is_dir():
        sys.exit(f"source pool not found: {args.source}")
    args.dest.mkdir(parents=True, exist_ok=True)

    comp_doc, comp_by_id = load_sets(COMP_SETS)
    noncomp_doc, noncomp_by_id = load_sets(NONCOMP_SETS)
    check_pairing(comp_by_id, noncomp_by_id)
    print(f"loaded {len(comp_by_id)} paired sets, pairing verified")

    set_ids = select_set_ids(comp_by_id, noncomp_by_id, args.n_sets, args.select, args.seed)
    print(f"selected {len(set_ids)} set_ids via --select {args.select}: {set_ids}")

    comp_imgs = images_for(set_ids, comp_by_id)
    noncomp_imgs = images_for(set_ids, noncomp_by_id)
    needed = comp_imgs | noncomp_imgs
    print(f"images referenced: {len(comp_imgs)} comp + {len(noncomp_imgs)} noncomp "
          f"= {len(needed)} distinct")

    available = {p.name for p in args.source.iterdir() if p.suffix == ".png"}
    missing_at_source = needed - available
    if missing_at_source:
        sys.exit(f"{len(missing_at_source)} images missing from source pool, e.g. "
                 f"{sorted(missing_at_source)[:5]}")

    already = {p.name for p in args.dest.iterdir() if p.suffix == ".png"}
    missing = sorted(needed - already)

    # Experiment 1 deployed the compositional-WHITE variant under these same
    # filenames. Skipping any name that merely exists would leave a mixed pool --
    # some shapes white-baked, some transparent -- so replace the ones that do
    # not match the transparent source.
    mismatched = sorted(
        n for n in (needed & already)
        if not filecmp.cmp(args.source / n, args.dest / n, shallow=False)
    )

    to_copy = missing + ([] if args.no_overwrite_mismatched else mismatched)
    total_bytes = sum((args.source / n).stat().st_size for n in to_copy)
    print(f"already correct: {len(needed & already) - len(mismatched)}   "
          f"missing: {len(missing)}   "
          f"mismatched (non-transparent): {len(mismatched)}")
    if mismatched and args.no_overwrite_mismatched:
        print(f"  WARNING: leaving {len(mismatched)} non-transparent images in place "
              f"(--no-overwrite-mismatched); the deployed pool will be visually mixed")
    print(f"to copy: {len(to_copy)} ({total_bytes / 1e6:.1f} MB)")

    if args.dry_run:
        print("--dry-run: nothing written")
        return

    for name in to_copy:
        shutil.copy2(args.source / name, args.dest / name)
    print(f"copied {len(to_copy)} images into {args.dest} "
          f"({len(missing)} new, {len(to_copy) - len(missing)} replaced)")

    schedule = {
        "schema_version": SCHEMA_VERSION,
        "generated": date.today().isoformat(),
        "source_schema_version": comp_doc["schema_version"],
        "selection": {
            "method": args.select,
            "n_sets": args.n_sets,
            "seed": args.seed if args.select == "random" else None,
            "criterion": QUALITY_CRITERION if args.select == "best" else None,
        },
        # S4.8: 2 dyads per condition per set. callbacks.js wraps past this
        # rather than turning players away, recording `replicate` so dyads stay
        # pairable in the analysis.
        "dyads_per_condition_per_set": 2,
        "conditions": ["comp-within", "comp-between", "noncomp"],
        "set_ids": set_ids,
        "notes": (
            "Only these set_ids have images deployed to client/public/tangrams. "
            "Re-run scripts/deploy_exp2_images.py before widening the pool."
        ),
    }
    with open(args.schedule_out, "w") as f:
        json.dump(schedule, f, indent=2)
        f.write("\n")
    print(f"wrote schedule -> {args.schedule_out.relative_to(REPO)}")


if __name__ == "__main__":
    main()
