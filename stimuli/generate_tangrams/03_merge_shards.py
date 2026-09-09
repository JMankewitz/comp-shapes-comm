"""
Step 3: merge per-top shards into one contiguous array, and validate it.

Output: data/embeddings/composed_embeddings.npy, (470*470, 512) float32, ~452 MB.
Row for shape {top}_{bottom} is at index top * 470 + bottom -- computable, so no
key file is needed. That layout makes a bottom-held-constant comparison (spec
6B, the novelty constraint) a contiguous slice and a top-held-constant one a
regular stride.

Validation, in increasing order of strength:
  1. all shards present, right shape and dtype
  2. every embedding is unit-norm (FTCLIP L2-normalizes; anything else means a
     corrupt or truncated shard)
  3. no all-zero or non-finite rows
  4. the six Exp 1 sets still reproduce their stored max_sim

Check 4 is the one that matters. Run with --validate-only to re-check an
existing merged array without rewriting it.

    python 03_merge_shards.py
    python 03_merge_shards.py --validate-only
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

import numpy as np
import yaml

import config as cfg  # noqa: E402

HERE = Path(__file__).parent
COMP_SETS = (
    HERE.parent.parent
    / "experiments/compositional-tangrams/server/src/comp_sets.json"
)
SIG = 1e-5
DIM = 512


def load_config(path):
    with open(path) as f:
        c = yaml.safe_load(f)
    c["shard_dir"] = Path(c["shard_dir"]) if c.get("shard_dir") else cfg.EMBEDDING_SHARDS
    c["out_path"] = (c["shard_dir"].parent / "composed_embeddings.npy")
    return c


def row(top, bottom, n):
    return top * n + bottom


def merge(c):
    n = c["n_tangrams"]
    shard_dir = c["shard_dir"]

    present, missing = [], []
    for t in range(n):
        p = shard_dir / f"shard_{t:04d}.npy"
        (present if p.exists() else missing).append(t)

    print(f"shards present : {len(present)}/{n}")
    if missing:
        rng = f"{missing[0]}..{missing[-1]}" if len(missing) > 1 else str(missing[0])
        print(f"MISSING {len(missing)} shards ({rng})")
        print("Re-run 02_embed_shards.py; it skips shards that already exist.")
        raise SystemExit(1)

    stray = list(shard_dir.glob("*.npy.tmp"))
    if stray:
        print(f"WARNING: {len(stray)} .tmp files -- an interrupted write. "
              f"Safe to delete; they are not read.")

    out = np.lib.format.open_memmap(
        c["out_path"], mode="w+", dtype=np.float32, shape=(n * n, DIM))

    t0 = time.time()
    for t in range(n):
        arr = np.load(shard_dir / f"shard_{t:04d}.npy")
        if arr.shape != (n, DIM):
            raise SystemExit(f"shard {t}: shape {arr.shape}, expected ({n}, {DIM})")
        if arr.dtype != np.float32:
            raise SystemExit(f"shard {t}: dtype {arr.dtype}, expected float32")
        out[t * n:(t + 1) * n] = arr
        if (t + 1) % 100 == 0:
            print(f"  merged {t + 1}/{n}", flush=True)
    out.flush()
    print(f"wrote {c['out_path']} in {time.time() - t0:.1f}s "
          f"({c['out_path'].stat().st_size / 1e6:.0f} MB)")
    return out


def validate(emb, c):
    n = c["n_tangrams"]
    ok = True

    print("\n" + "-" * 66)
    print("VALIDATION")
    print("-" * 66)
    print(f"shape / dtype  : {emb.shape} {emb.dtype}")

    # sample rather than scan 220,900 rows of memmap for the cheap checks
    rs = np.random.default_rng(0)
    idx = np.unique(np.concatenate([
        np.arange(64), rs.integers(0, n * n, 4096), np.arange(n * n - 64, n * n)]))
    sample = np.asarray(emb[idx], dtype=np.float64)

    finite = np.isfinite(sample).all()
    zero_rows = int((np.abs(sample).sum(axis=1) == 0).sum())
    norms = np.linalg.norm(sample, axis=1)
    print(f"finite         : {finite}")
    print(f"all-zero rows  : {zero_rows} of {len(idx)} sampled")
    print(f"L2 norm        : min={norms.min():.8f} max={norms.max():.8f}")

    if not finite or zero_rows:
        ok = False
    if abs(norms - 1.0).max() > 1e-4:
        print("  !! not unit-norm -- shards are corrupt or from another model")
        ok = False

    # row-index convention: shard t row b must equal merged row t*n+b
    t_chk = 137
    shard = np.load(c["shard_dir"] / f"shard_{t_chk:04d}.npy")
    same = np.array_equal(shard, np.asarray(emb[t_chk * n:(t_chk + 1) * n]))
    print(f"row layout     : shard {t_chk} matches rows "
          f"[{t_chk * n}, {(t_chk + 1) * n}) -> {same}")
    if not same:
        ok = False

    # --- the check that matters ---
    print("\nExp 1 reproduction (stored max_sim in comp_sets.json)")
    sets = json.load(open(COMP_SETS))
    ordered = sorted(sets, key=lambda s: s["max_sim"])
    chosen = [ordered[round(i * (len(ordered) - 1) / 5)] for i in range(6)]

    print(f"{'set_id':>7} {'stored':>10} {'merged':>12} {'abs diff':>11}   ok")
    worst = 0.0
    for s in chosen:
        rows = [row(i, j, n) for i in s["top_tangrams"] for j in s["bottom_tangrams"]]
        sub = np.asarray(emb[rows], dtype=np.float32)
        sim = sub @ sub.T
        iu = np.triu_indices(len(rows), k=1)
        got = float(sim[iu].max())
        d = abs(got - s["max_sim"])
        worst = max(worst, d)
        print(f"{s['set_id']:>7} {s['max_sim']:>10.6f} {got:>12.6f} {d:>11.2e}"
              f"   {'YES' if d < SIG else 'NO'}")
    if worst >= SIG:
        ok = False

    # timing for the 470-component similarity the report asks about
    print("\nTiming")
    t0 = time.time()
    comp = np.asarray(emb[[row(t, 0, n) for t in range(n)]], dtype=np.float32)
    _ = comp @ comp.T
    print(f"  470x470 similarity (one held-constant slice) : "
          f"{(time.time() - t0) * 1000:.1f} ms")

    t0 = time.time()
    for b in range(n):
        sl = np.asarray(emb[b::n], dtype=np.float32)   # all tops, bottom b fixed
        _ = sl @ sl.T
    print(f"  all 470 bottom-held-constant slices          : "
          f"{time.time() - t0:.1f} s")

    print("\n" + "=" * 66)
    print(f"VERDICT: {'PASS' if ok else 'FAIL'}   (worst max_sim diff {worst:.2e})")
    print("=" * 66)
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(HERE / "config.yaml"))
    ap.add_argument("--validate-only", action="store_true")
    args = ap.parse_args()

    c = load_config(args.config)
    print(f"shards : {c['shard_dir']}")
    print(f"output : {c['out_path']}")

    if args.validate_only:
        if not c["out_path"].exists():
            raise SystemExit(f"no merged array at {c['out_path']}")
        emb = np.load(c["out_path"], mmap_mode="r")
    else:
        emb = merge(c)

    ok = validate(emb, c)
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
