"""
Step 1: prove the refactored src/ still produces Experiment 1's numbers.

Sweeps the configurations the refactor introduced and compares each against the
frozen pristine reference from 00b_baseline_ref.py, elementwise on the embedding
tensors and on the six stored max_sim values.

  device      cpu / mps          -- was previously pinned to cpu unconditionally
  mode        train / eval       -- published numbers were produced in TRAIN mode
  batching    1 / 16 / 256       -- was one image at a time

Expectation: cpu/train/batch=1 must be bit-identical (0.00e+00). Everything else
is allowed to differ by float noise; the question this answers is how much, and
whether it is small enough to be irrelevant against a 0.778 threshold.

Run 00b_baseline_ref.py first.

    /opt/anaconda3/envs/compshape-sim/bin/python 01_validate_refactor.py
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

import torch

from config import PROCESSED_TANGRAMS_WHITE  # noqa: E402
from embedding import embed_paths, setup_pretrained_model  # noqa: E402

REF = Path(__file__).parent / "data" / "embeddings" / "_baseline_ref.pt"

REPO_ID = "lil-lab/kilogram-models"
FILE_PATHS = [
    "clip_controlled/whole+black/model0.pth",
    "clip_controlled/whole+black/model1.pth",
    "clip_controlled/whole+black/model2.pth",
]

# max_sim is reported to ~3 decimals and thresholds sit at 0.607-0.778, so
# anything below this is numerically irrelevant to the science.
SIG = 1e-5


def set_max_sims(emb, names, ref):
    """Recompute each Exp 1 set's max pairwise similarity from `emb`."""
    pos = {n: i for i, n in enumerate(names)}
    out = []
    for tops, bottoms in zip(ref["set_tops"], ref["set_bottoms"]):
        idx = [pos[f"{i}_{j}"] for i in tops for j in bottoms]
        sub = emb[idx]
        sim = torch.matmul(sub, sub.T)
        n = len(idx)
        iu = torch.triu_indices(n, n, offset=1)
        out.append(sim[iu[0], iu[1]].max().item())
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch-sizes", type=int, nargs="+", default=[1, 16, 256])
    ap.add_argument("--num-workers", type=int, default=0)
    args = ap.parse_args()

    if not REF.exists():
        raise SystemExit(f"missing {REF}\nRun 00b_baseline_ref.py first.")

    ref = torch.load(REF, weights_only=False)
    ref_emb = ref["embeddings"]
    names = ref["names"]
    paths = [PROCESSED_TANGRAMS_WHITE / f"{n}.png" for n in names]

    print("=" * 78)
    print("STEP 1  REFACTOR EQUIVALENCE")
    print("=" * 78)
    print(f"reference : {tuple(ref_emb.shape)} from git {ref['git_head'][:10]}, "
          f"device={ref['device']}, train_mode={ref['model_training_mode']}")
    print(f"stored max_sim : {[f'{v:.6f}' for v in ref['stored_max_sim']]}")

    devices = ["cpu"]
    if torch.backends.mps.is_available():
        devices.append("mps")
    else:
        print("\n!! MPS unavailable -- cpu only")

    configs = [(d, m, b) for d in devices for m in (False, True)
               for b in args.batch_sizes]

    print(f"\n{'device':>7} {'mode':>6} {'batch':>6} {'sec':>7} {'img/s':>8} "
          f"{'max|demb|':>11} {'max|dmax_sim|':>14}   verdict")
    print("-" * 78)

    loaded = {}
    results = []
    for device, eval_mode, bs in configs:
        key = (device, eval_mode)
        if key not in loaded:
            loaded[key] = setup_pretrained_model(
                REPO_ID, FILE_PATHS, device, eval_mode=eval_mode)
        model, _, dev = loaded[key]

        t0 = time.time()
        emb = embed_paths(paths, model, dev, batch_size=bs,
                          num_workers=args.num_workers)
        secs = time.time() - t0

        d_emb = (emb - ref_emb).abs().max().item()
        got = set_max_sims(emb, names, ref)
        d_sim = max(abs(a - b) for a, b in zip(got, ref["stored_max_sim"]))

        exact = (d_emb == 0.0)
        ok = d_sim < SIG
        verdict = "EXACT" if exact else ("ok" if ok else "*** DIVERGED ***")

        print(f"{device:>7} {'eval' if eval_mode else 'train':>6} {bs:>6} "
              f"{secs:>7.1f} {len(paths)/secs:>8.1f} {d_emb:>11.2e} "
              f"{d_sim:>14.2e}   {verdict}")
        results.append((device, eval_mode, bs, secs, d_emb, d_sim, ok))

    print("-" * 78)

    # --- the check that actually gates the refactor -------------------------
    baseline = [r for r in results
                if r[0] == "cpu" and r[1] is False and r[2] == 1]
    print("\nGATE 1  cpu / train / batch=1 must be bit-identical to pristine")
    if baseline and baseline[0][4] == 0.0:
        print("  PASS -- refactor changed no numerics on the original code path")
    elif baseline:
        print(f"  FAIL -- differs by {baseline[0][4]:.2e}. The refactor moved a "
              f"number it should not have.")
    else:
        print("  not run (batch size 1 not in --batch-sizes)")

    print(f"\nGATE 2  every config reproduces stored max_sim within {SIG:.0e}")
    bad = [r for r in results if not r[6]]
    if not bad:
        worst = max(r[5] for r in results)
        print(f"  PASS -- worst deviation {worst:.2e} across all "
              f"{len(results)} configs")
    else:
        for r in bad:
            print(f"  FAIL -- {r[0]}/{'eval' if r[1] else 'train'}/bs={r[2]}: "
                  f"{r[5]:.2e}")

    print("\nGATE 3  eval mode is numerically free (no dropout, LayerNorm only)")
    for device in devices:
        for bs in args.batch_sizes:
            tr = next((r for r in results if r[:3] == (device, False, bs)), None)
            ev = next((r for r in results if r[:3] == (device, True, bs)), None)
            if tr and ev:
                print(f"  {device}/bs={bs}: |train-eval| on max_sim = "
                      f"{abs(tr[5] - ev[5]):.2e}")

    # --- throughput ---------------------------------------------------------
    print("\nTHROUGHPUT  extrapolated to all 220,900 composed shapes")
    for r in sorted(results, key=lambda r: r[3]):
        rate = len(paths) / r[3]
        print(f"  {r[0]:>4}/{'eval' if r[1] else 'train':<5}/bs={r[2]:<4} "
              f"{rate:>7.1f} img/s -> {220900 / rate / 60:>6.1f} min")
    print("\n  (small-sample rates; model warmup inflates the first config and "
          "num_workers=0 leaves PNG decode single-threaded. "
          "Step 2 measures this properly.)")


if __name__ == "__main__":
    main()
