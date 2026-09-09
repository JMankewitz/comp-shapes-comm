"""
Step 0: validate the EXISTING pipeline before any refactor.

Runs against src/embedding.py and src/similarity.py exactly as committed -- no
device fix, no batching, no config-path fix. The point is to establish a
ground-truth number that the refactor must reproduce bit-for-bit.

Answers two questions:
  Q1. Are FTCLIP embeddings L2-normalized? (i.e. is the similarity matrix
      diagonal 1.0, making the commented-out normalization line redundant
      rather than missing?)
  Q2. Do we reproduce the stored max_sim values in comp_sets.json?

Nothing is written to disk. Run from stimuli/generate_tangrams/.

    /opt/anaconda3/envs/compshape-sim/bin/python 00_validate_baseline.py
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

import torch

from config import MAPPING_FILE, PROCESSED_TANGRAMS_WHITE  # noqa: E402
from embedding import setup_pretrained_model  # noqa: E402
from similarity import ImageSet  # noqa: E402

REPO_ID = "lil-lab/kilogram-models"
FILE_PATHS = [
    "clip_controlled/whole+black/model0.pth",
    "clip_controlled/whole+black/model1.pth",
    "clip_controlled/whole+black/model2.pth",
]

COMP_SETS = (
    Path(__file__).parent.parent.parent
    / "experiments/compositional-tangrams/server/src/comp_sets.json"
)

# Exp 1 shipped sets span max_sim 0.607-0.778. Sample across that range rather
# than taking the first n, so a reproduction failure that is threshold-dependent
# shows up as a pattern instead of a constant offset.
def pick_sets(sets, n):
    ordered = sorted(sets, key=lambda s: s["max_sim"])
    if n >= len(ordered):
        return ordered
    step = (len(ordered) - 1) / (n - 1) if n > 1 else 1
    return [ordered[round(i * step)] for i in range(n)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-sets", type=int, default=6,
                    help="how many Exp 1 sets to re-derive")
    ap.add_argument("--device", default=None,
                    help="passed through to setup_pretrained_model; note that "
                         "FTCLIP hardcodes its own device internally, so this "
                         "currently has no effect on where the forward pass runs")
    ap.add_argument("--tol", type=float, default=1e-5,
                    help="max abs diff vs stored max_sim to count as reproduced")
    args = ap.parse_args()

    print("=" * 70)
    print("STEP 0 BASELINE VALIDATION (unmodified src/)")
    print("=" * 70)

    print(f"\ntorch {torch.__version__}")
    print(f"cuda available : {torch.cuda.is_available()}")
    print(f"mps available  : {torch.backends.mps.is_available()} "
          f"(built={torch.backends.mps.is_built()})")
    print(f"images         : {PROCESSED_TANGRAMS_WHITE}")
    print(f"images exist   : {PROCESSED_TANGRAMS_WHITE.is_dir()}")
    print(f"mapping        : {MAPPING_FILE} (exists={MAPPING_FILE.exists()})")
    print(f"comp_sets.json : {COMP_SETS} (exists={COMP_SETS.exists()})")

    print("\nloading FTCLIP (merging 3 .pth parts)...")
    t0 = time.time()
    model, preprocess, device = setup_pretrained_model(REPO_ID, FILE_PATHS, args.device)
    print(f"loaded in {time.time() - t0:.1f}s")
    print(f"setup_pretrained_model returned device : {device!r}")
    print(f"FTCLIP internal self._device           : {model._device!r}")
    print(f"model.training (True means .eval() was never called) : {model.training}")

    sets = json.load(open(COMP_SETS))
    chosen = pick_sets(sets, args.n_sets)
    print(f"\n{len(sets)} sets in comp_sets.json; validating {len(chosen)} "
          f"spanning max_sim "
          f"{chosen[0]['max_sim']:.4f}-{chosen[-1]['max_sim']:.4f}")

    # ---------------- Q1: normalization ----------------
    print("\n" + "-" * 70)
    print("Q1  NORMALIZATION")
    print("-" * 70)

    first = chosen[0]
    paths = [PROCESSED_TANGRAMS_WHITE / f"{i}_{j}.png"
             for i in first["top_tangrams"] for j in first["bottom_tangrams"]]
    probe = ImageSet(-1, paths, "comp")
    t0 = time.time()
    probe.extract_embeddings(model, preprocess, device)
    embed_secs = time.time() - t0
    probe.compute_cosine_similarities()

    emb = probe.embeddings
    norms = emb.norm(dim=1)
    diag = torch.diagonal(probe.similarity_matrix)

    print(f"embedding shape  : {tuple(emb.shape)}")
    print(f"embedding dtype  : {emb.dtype}")
    print(f"L2 norms         : min={norms.min():.8f}  max={norms.max():.8f}")
    print(f"sim diagonal     : min={diag.min():.8f}  max={diag.max():.8f}")
    print(f"max |diag - 1.0| : {(diag - 1.0).abs().max():.3e}")

    normalized = bool((diag - 1.0).abs().max() < 1e-4)
    if normalized:
        print("\n  => embeddings ARE L2-normalized (FTCLIP.forward calls compute_norm).")
        print("     The commented-out line in compute_cosine_similarities is")
        print("     REDUNDANT, not missing. Published values are true cosines.")
        print("     No threshold re-derivation needed.")
    else:
        print("\n  => embeddings are NOT normalized. Published 'cosine similarities'")
        print("     are dot products. STOP and report before changing anything.")

    print(f"\n  16 images embedded one-at-a-time in {embed_secs:.1f}s "
          f"({embed_secs / 16 * 1000:.0f} ms/image)")
    print(f"  extrapolated to 220,900 images: "
          f"{embed_secs / 16 * 220900 / 3600:.1f} hours unbatched on this device")

    # ---------------- Q2: Exp 1 reproduction ----------------
    print("\n" + "-" * 70)
    print("Q2  EXP 1 REPRODUCTION")
    print("-" * 70)
    print(f"{'set_id':>7} {'stored':>10} {'recomputed':>12} {'abs diff':>11}   ok")

    diffs = []
    for s in chosen:
        paths = [PROCESSED_TANGRAMS_WHITE / f"{i}_{j}.png"
                 for i in s["top_tangrams"] for j in s["bottom_tangrams"]]
        missing = [p for p in paths if not p.exists()]
        if missing:
            print(f"{s['set_id']:>7}  MISSING {len(missing)} images, e.g. {missing[0].name}")
            continue

        iset = ImageSet(s["set_id"], paths, "comp")
        iset.extract_embeddings(model, preprocess, device)
        iset.compute_cosine_similarities()
        got = iset.get_summary_stats()["max_similarity"]
        d = abs(got - s["max_sim"])
        diffs.append(d)
        print(f"{s['set_id']:>7} {s['max_sim']:>10.6f} {got:>12.6f} {d:>11.2e}"
              f"   {'YES' if d < args.tol else 'NO'}")

    print("\n" + "=" * 70)
    print("VERDICT")
    print("=" * 70)
    if not diffs:
        print("no sets evaluated -- check the paths printed above")
    else:
        worst = max(diffs)
        print(f"normalization    : {'L2-normalized, cosine is correct' if normalized else 'NOT NORMALIZED -- STOP'}")
        print(f"worst abs diff   : {worst:.2e}  (tolerance {args.tol:.0e})")
        if worst < args.tol:
            print("reproduction     : PASS -- pipeline has not drifted, thresholds stand")
        else:
            print("reproduction     : FAIL -- pipeline drifted; every threshold in the")
            print("                   spec is suspect. Stop here and report.")


if __name__ == "__main__":
    main()
