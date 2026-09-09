#!/usr/bin/env python3
"""Flag stimulus sets containing an image whose two halves are near-duplicates.

WHY
---
04_sample_sets.py scores a candidate set by the pairwise similarity of its k*k
COMPOSED images. It never compares one component to another, and the draw itself
is uniform over the 470-tangram pool with no constraint but "no index twice". So
nothing stops two near-duplicate tangrams being drawn into the same set -- and
when one lands in the top slot and the other in the bottom slot of the same
displayed image, that image is a shape stacked on itself.

The composite criterion is structurally blind to this. Its max is driven by pairs
that differ in exactly ONE component (04_sample_sets.py notes the two maxima
coincide ~100% of the time); two composites sharing no component are never the
closest pair. Measured: the within-image top-vs-bottom similarity across all
16,000 displayed images matches the unconstrained null almost exactly
(p50 .486 vs .498, max .981 vs .981). Zero selection pressure.

Set 4's J10 is 373_282.png -- an arrow-out-of-a-block over the same arrow with
notches -- and set 4 passed with max_full_cross_scored 0.772.

WHAT THIS SCREENS
-----------------
Only pairs that actually appear TOGETHER IN ONE DISPLAYED IMAGE (the training
shapes and the pre/post items). Top-vs-top and bottom-vs-bottom similarity is
already selected against by the composite criterion -- two similar tops make two
composites that differ in one component, which is exactly what its max measures.
The hole is specifically top-vs-bottom, so that is what this closes.

Component similarity is the exact "swap one slot" measure: mean over the other
slot of the cosine between composed embeddings, taken as the max over the two
roles (confusable in EITHER role counts). Computed once and cached.

THRESHOLD
---------
Default 0.7513 = the 99th percentile of all 110,215 component pairs. Same number
is used by 04_sample_sets.py --max-component-sim, so the screen and the generator
agree. At this cut 401 of the 500 sets are clean, which is far more than the 75
the study needs.

Usage:
    python3 scripts/flag_component_clashes.py                 # report
    python3 scripts/flag_component_clashes.py --write         # write the CSV
    python3 scripts/flag_component_clashes.py --threshold 0.78
"""

import argparse
import csv
import datetime
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETS = os.path.join(REPO, "experiments", "compositional-tangrams-v2", "server",
                    "src", "exp2_comp_sets.json")
EMB = os.path.join(REPO, "stimuli", "generate_tangrams", "data", "embeddings")
COMPOSED = os.path.join(EMB, "composed_embeddings.npy")
CACHE = os.path.join(EMB, "component_similarity.npy")
OUT = os.path.join(REPO, "data", "processed_data", "exp_2", "clashing_sets.csv")

# p99 of the component-pair distribution. Keep in step with 04_sample_sets.py.
DEFAULT_THRESHOLD = 0.7513


def component_similarity(n=470):
    """(n, n) exact component-vs-component similarity, cached.

    C[i, j] = max over role of mean_x <E[i, x], E[j, x]>, i.e. "if I swap
    tangram i for tangram j and hold the other half fixed, how little does the
    composed image change?" -- averaged over every possible other half. The max
    over the two roles is deliberate: a pair confusable in EITHER slot is a
    problem, because the sampler assigns roles by index order.

    ~2s and 450 MB of temporaries on a laptop, so it is cached rather than
    recomputed.
    """
    import numpy as np
    if os.path.exists(CACHE):
        return np.load(CACHE)
    if not os.path.exists(COMPOSED):
        sys.exit(f"need {COMPOSED} (run stimuli/generate_tangrams/03_merge_shards.py)")
    print(f"  computing {CACHE} (one-off, ~2s)...")
    E = np.asarray(np.load(COMPOSED, mmap_mode="r")).reshape(n, n, -1).astype(np.float32)
    A = E.reshape(n, -1)                                        # i as TOP
    B = np.ascontiguousarray(E.transpose(1, 0, 2).reshape(n, -1))   # i as BOTTOM
    C = np.maximum((A @ A.T) / n, (B @ B.T) / n)
    np.fill_diagonal(C, 0.0)
    np.save(CACHE, C)
    return C


def displayed_shapes(s):
    """Every image a participant actually sees in this set, deduplicated.

    pretest and posttest hold the same 20 items, so the image list repeats;
    dedupe on the image name to avoid double-reporting one clash.
    """
    out = {}
    for key in ("training_shapes", "pretest_items", "posttest_items"):
        for sh in s.get(key, []):
            out.setdefault(sh["image"],
                           (sh["top"], sh["bottom"], sh.get("cell", "training"),
                            sh["label"]))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                    help=f"flag an image whose halves reach this similarity "
                         f"(default {DEFAULT_THRESHOLD}, the p99 of all "
                         f"component pairs)")
    ap.add_argument("--write", action="store_true",
                    help="write clashing_sets.csv; otherwise just report")
    ap.add_argument("--show", type=int, default=25,
                    help="how many flagged images to print (default 25)")
    args = ap.parse_args()

    C = component_similarity()
    sets = sorted(json.load(open(SETS))["sets"], key=lambda s: s["set_id"])

    flagged = {}
    for s in sets:
        hits = []
        for img, (t, b, cell, lab) in displayed_shapes(s).items():
            v = float(C[t, b])
            if v >= args.threshold:
                hits.append((v, cell, lab, img))
        if hits:
            hits.sort(reverse=True)
            flagged[s["set_id"]] = hits

    n_img = sum(len(v) for v in flagged.values())
    print(f"  {len(sets)} sets, threshold {args.threshold:.4f}")
    print(f"  {len(flagged)} set(s) flagged, {n_img} image(s) "
          f"({len(sets) - len(flagged)} sets clean)")

    shown = 0
    for sid in sorted(flagged):
        for v, cell, lab, img in flagged[sid]:
            if shown >= args.show:
                break
            train = "TRAINING" if cell == "training" else ""
            print(f"    set{sid:<4} {v:.4f}  {cell:<26} {lab:<4} {img:<16} {train}")
            shown += 1
    if n_img > shown:
        print(f"    ... {n_img - shown} more")

    clean = [s["set_id"] for s in sets if s["set_id"] not in flagged]
    print(f"\n  first 75 clean set ids: {clean[:75]}")
    if len(clean) >= 75:
        print(f"  (a 75-set pool reaches set_id {clean[74]})")
    else:
        print(f"  WARNING: only {len(clean)} clean sets -- lower the threshold "
              f"or generate more with 04_sample_sets.py")

    if not args.write:
        print("\n  (report only -- pass --write to update clashing_sets.csv)")
        return

    today = datetime.date.today().isoformat()
    with open(OUT, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["setId", "max_similarity", "n_flagged_images",
                    "has_training_clash", "worst_cell", "worst_label",
                    "worst_image", "found"])
        for sid in sorted(flagged):
            hits = flagged[sid]
            v, cell, lab, img = hits[0]
            w.writerow([sid, f"{v:.4f}", len(hits),
                        "TRUE" if any(h[1] == "training" for h in hits) else "FALSE",
                        cell, lab, img, today])
    print(f"\n  wrote {len(flagged)} row(s) to {os.path.relpath(OUT, REPO)}")
    print("  this file is DERIVED -- regenerate it, do not hand-edit.")
    print("  has_training_clash marks sets whose bad image is a TRAINING target "
          "(48 rounds), not just a pre/post description item.")


if __name__ == "__main__":
    main()
