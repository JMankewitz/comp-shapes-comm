"""
Step 4: sample candidate stimulus sets and rank them by pairwise similarity.

Generalizes Exp 1's procedure (similarity.py::gen_target_images: draw N random
sets, keep the best half) to a k+k component budget.

Method, per the 2026-08-19 decisions:
  - reject sampling, ranked -- no constructive search
  - roles assigned by index order, not optimized
  - threshold derived POST HOC from this design's own distribution, not
    imported from Exp 1. Larger matrices mechanically have larger maxima
    (more pairs = deeper tail); comparing raw values across budgets is
    meaningless. Selection quality is reported as a z-score and percentile
    against the observed distribution, which IS comparable.

Scoring is the full k x k cross: every pair among the k^2 composed shapes,
exactly as Exp 1 scored all 120 pairs among its 16. This is deliberately
independent of the display design, so the sets stay valid whatever foil
structure the experiment lands on.

    python 04_sample_sets.py --k 12 --n-draws 60000 --n-keep 50
    python 04_sample_sets.py --k 8  --n-draws 60000 --n-keep 50
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

import numpy as np

import config as cfg  # noqa: E402

HERE = Path(__file__).parent


def load_embeddings(n):
    """(n, n, 512) float32, indexed [top, bottom]. Prefers the merged array."""
    merged = cfg.EMBEDDINGS_DIR / "composed_embeddings.npy"
    if merged.exists():
        a = np.load(merged, mmap_mode="r")
        print(f"loaded merged {merged.name} {a.shape}")
        return np.ascontiguousarray(a).reshape(n, n, -1)
    shards = sorted(cfg.EMBEDDING_SHARDS.glob("shard_*.npy"))
    if len(shards) != n:
        raise SystemExit(
            f"expected {n} shards in {cfg.EMBEDDING_SHARDS}, found {len(shards)}.\n"
            f"Run 02_embed_shards.py first.")
    a = np.stack([np.load(p) for p in shards])
    print(f"loaded {len(shards)} shards -> {a.shape} ({a.nbytes / 1e6:.0f} MB)")
    return a


def component_similarity(E, n):
    """(n, n) component-vs-component similarity, cached next to the embeddings.

    C[i, j] = max over role of mean_x <E[i, x], E[j, x]>: "swap tangram i for
    tangram j, hold the other half fixed -- how little does the composed image
    change?", averaged over every possible other half. Max over the two roles,
    because a pair confusable in EITHER slot is a problem and roles here are
    assigned by index order.

    ~2s and ~450 MB of temporaries at n=470, so it is cached.
    """
    cache = cfg.EMBEDDINGS_DIR / "component_similarity.npy"
    if cache.exists():
        return np.load(cache)
    print(f"computing {cache.name} (one-off)...")
    A = E.reshape(n, -1)                                           # i as TOP
    B = np.ascontiguousarray(E.transpose(1, 0, 2).reshape(n, -1))  # i as BOTTOM
    C = np.maximum((A @ A.T) / n, (B @ B.T) / n).astype(np.float32)
    np.fill_diagonal(C, 0.0)
    np.save(cache, C)
    return C


def pair_index(k):
    """Precompute pair indices and the one-component mask; they depend only on k.

    Hoisted out of the per-set loop: at k=12 these are 10,296-element arrays
    that would otherwise be rebuilt for every one of N draws.
    """
    iu = np.triu_indices(k * k, 1)
    t1, b1 = iu[0] // k, iu[0] % k
    t2, b2 = iu[1] // k, iu[1] % k
    return iu, (t1 == t2) ^ (b1 == b2)


def score_set(E, tops, bots, iu, one_comp):
    """All pairwise similarities among the k*k composed shapes.

    Returns Exp 1's four summary stats plus the max restricted to pairs that
    differ in exactly ONE component. Empirically the two maxima coincide in
    100% of sets -- pairs sharing no component never drive the max -- so the
    one-component figure is a diagnostic, not a second criterion.
    """
    k = len(tops)
    X = E[np.ix_(tops, bots)].reshape(k * k, -1)   # row i*k+j = tops[i]_bots[j]
    v = (X @ X.T)[iu]
    return (float(v.min()), float(v.mean()), float(np.median(v)), float(v.max()),
            float(v[one_comp].max()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=12,
                    help="components per role (tops and bottoms each)")
    ap.add_argument("--n-draws", type=int, default=60000)
    ap.add_argument("--n-keep", type=int, default=50)
    ap.add_argument("--seed", type=int, default=20260819)
    ap.add_argument("--max-component-sim", type=float, default=0.7513,
                    help="reject a draw if any top-bottom component pair reaches "
                         "this similarity (default 0.7513 = p99 of all 110,215 "
                         "component pairs; same cut as "
                         "scripts/flag_component_clashes.py). ~25%% of draws "
                         "survive, and the test is far cheaper than score_set, "
                         "so rejection is nearly free.")
    ap.add_argument("--no-component-screen", action="store_true",
                    help="disable the screen and reproduce the pre-2026-09 draw "
                         "exactly. Rejection changes the RNG stream, so the "
                         "screen cannot be added without changing which sets "
                         "come out -- this flag exists to reproduce the old "
                         "candidate_sets_k*.json, not for normal use.")
    ap.add_argument("--csv-max-rows", type=int, default=100000,
                    help="cap on distribution rows written to CSV")
    ap.add_argument("--out-dir", default=str(cfg.SIMILARITY_RESULTS))
    args = ap.parse_args()

    n = cfg.N_TANGRAMS
    k = args.k
    if 2 * k > n:
        raise SystemExit(f"cannot draw {2 * k} disjoint components from {n}")

    E = load_embeddings(n)
    rs = np.random.default_rng(args.seed)

    # Component screen. The composite score below compares COMPOSED images to
    # each other and never one component to another, so nothing in it stops two
    # near-duplicate tangrams being drawn into the same set. When one lands in
    # the top slot and the other in the bottom slot of the same displayed image,
    # that image is a shape stacked on itself -- which is how 373_282.png
    # (set 4, J10) shipped while its set scored a clean max of 0.772.
    #
    # Only the TOP x BOTTOM block is screened. Two similar tops are already
    # selected against: they produce two composites differing in exactly one
    # component, which is precisely what the max below measures (and which it
    # equals ~100% of the time). Top-vs-bottom is the hole, so that is what this
    # closes -- and screening only the cross block keeps acceptance at ~25%
    # rather than ~8%.
    C = None if args.no_component_screen else component_similarity(E, n)
    if C is None:
        print("\nWARNING: component screen DISABLED -- reproduces the pre-2026-09 "
              "draw, including sets whose halves are near-duplicates.")
    else:
        print(f"\ncomponent screen ON: no top-bottom pair may reach "
              f"{args.max_component_sim} (p99 of all component pairs is 0.7513)")

    print(f"\nsampling {args.n_draws} sets at {k}+{k} "
          f"({k * k} shapes, {k * k * (k * k - 1) // 2} pairs each)")

    iu, one_comp = pair_index(k)

    draws = np.empty((args.n_draws, 2 * k), dtype=np.int32)
    stats = np.empty((args.n_draws, 5), dtype=np.float64)

    t0 = time.time()
    rejected = 0
    for i in range(args.n_draws):
        while True:
            s = rs.choice(n, 2 * k, replace=False)  # tops/bottoms disjoint by construction
            if C is None or C[np.ix_(s[:k], s[k:])].max() < args.max_component_sim:
                break
            rejected += 1
            if rejected > 500 * args.n_draws:
                raise SystemExit(
                    f"--max-component-sim {args.max_component_sim} is too tight: "
                    f"{rejected} rejections and counting. Raise it (p99 of the "
                    f"component-pair distribution is a sane floor).")
        draws[i] = s
        stats[i] = score_set(E, s[:k], s[k:], iu, one_comp)
        if (i + 1) % 10000 == 0:
            el = time.time() - t0
            print(f"  {i + 1}/{args.n_draws}  {(i + 1) / el:.0f} sets/s  "
                  f"eta {(args.n_draws - i - 1) / ((i + 1) / el) / 60:.1f}m", flush=True)
    el = time.time() - t0
    print(f"done in {el / 60:.1f} min ({args.n_draws / el:.0f} sets/s)")
    if C is not None:
        acc = args.n_draws / (args.n_draws + rejected)
        print(f"component screen: {rejected:,} draw(s) rejected, "
              f"{acc * 100:.1f}% accepted")

    mx = stats[:, 3]
    mean, sd, med = mx.mean(), mx.std(), np.median(mx)
    agree = float((stats[:, 3] == stats[:, 4]).mean())

    print(f"\nmax-similarity distribution at k={k}")
    print(f"  mean={mean:.4f}  sd={sd:.4f}  median={med:.4f}")
    print(f"  min={mx.min():.4f}  max={mx.max():.4f}")
    print(f"  below median (Exp 1's keep rule): {(mx < med).sum()}")
    print(f"  set max is a one-component-differs pair: {agree * 100:.1f}% of sets")

    order = np.argsort(mx)[:args.n_keep]
    kept = mx[order]
    print(f"\nkeeping best {args.n_keep}: max_sim {kept.min():.4f}-{kept.max():.4f}")
    print(f"  worst kept: z={(kept.max() - mean) / sd:+.2f}  "
          f"percentile={(mx <= kept.max()).mean() * 100:.4f}%")

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # distribution, in the existing set_summaries_*.csv column format.
    # Beyond --csv-max-rows the full draw list is subsampled: the CSV exists to
    # characterise the distribution, and a 100k subsample does that exactly as
    # well as 1.2M rows. Kept sets are always written in full, to the JSON.
    csv = out / f"set_summaries_k{k}.csv"
    if args.n_draws > args.csv_max_rows:
        sub = np.sort(rs.choice(args.n_draws, args.csv_max_rows, replace=False))
        print(f"\nn_draws > csv_max_rows: writing a {args.csv_max_rows} subsample "
              f"of the distribution (kept sets go to the JSON in full)")
    else:
        sub = np.arange(args.n_draws)
    with open(csv, "w") as f:
        f.write(",mean_similarity,min_similarity,max_similarity,median_similarity,"
                "max_one_component,set_id,set_type\n")
        for i in sub:
            mn, mu, md, mxi, oc = stats[i]
            f.write(f"{i},{mu},{mn},{mxi},{md},{oc},{i},comp{k}\n")
    print(f"wrote {csv} ({len(sub)} rows)")

    # ranked pool, spec 8.3 schema; roles by index order
    pool = []
    for rank, i in enumerate(order):
        s = draws[i]
        tops, bots = s[:k].tolist(), s[k:].tolist()
        mn, mu, md, mxi, oc = stats[i]
        pool.append({
            "set_id": rank,
            "draw_id": int(i),
            "trained_tops": tops[:4], "trained_bottoms": bots[:4],
            "untrained_tops": tops[4:], "untrained_bottoms": bots[4:],
            "max_sim": mxi, "mean_sim": mu, "min_sim": mn, "median_sim": md,
            "z_vs_distribution": (mxi - mean) / sd,
            "percentile": float((mx <= mxi).mean() * 100),
        })
    js = out / f"candidate_sets_k{k}.json"
    js.write_text(json.dumps({
        "k": k, "n_draws": args.n_draws, "seed": args.seed,
        "distribution": {"mean": mean, "sd": sd, "median": med,
                         "min": float(mx.min()), "max": float(mx.max())},
        "sets": pool,
    }, indent=2))
    print(f"wrote {js}  ({len(pool)} sets)")


if __name__ == "__main__":
    main()
