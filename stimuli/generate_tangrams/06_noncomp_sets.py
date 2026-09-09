"""
Step 6: build non-compositional partner sets for the compositional pool.

Construction (design doc 4.6, "inverted matrix"), decided 2026-08-19:

A non-comp set reuses a comp set's 12+12 recombining components verbatim, so
post-test items are IDENTICAL across conditions -- which 4.6 requires for the
between-condition comparison -- and adds 12 filler tops + 12 filler bottoms
paired 1:1 into 12 standalone wholes.

                      comp                     non-comp
  diagonal A1..D4     held out (test items)    TRAINED (familiar items)
  off-diag A2,B3..    trained                  never seen (test items)
  training set        12 off-diagonal cells    4 diagonal + 8 filler wholes
  held out            --                       4 filler wholes

  16 training wholes = 4 diagonal + 12 filler; minus 4 held out = 12 trained,
  matching comp's 12 trained shapes on shape-level exposure.

Filler components appear in exactly one whole each and are shared with nothing,
so every filler-involving pair is share-nothing (median ~0.26). Only those pairs
are searched; the comp part is fixed and its max is carried through.

Non-comp exposure is NOT component-matched to comp, and cannot be -- a
non-compositional environment has no recurring components by definition. See
4.6; report it, do not try to fix it.

    python 06_noncomp_sets.py --comp-sets outputs/similarity_results/candidate_sets_k12.json
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
    p = cfg.EMBEDDINGS_DIR / "composed_embeddings.npy"
    if not p.exists():
        raise SystemExit(f"missing {p} -- run 03_merge_shards.py")
    return np.load(p, mmap_mode="r").reshape(n, n, -1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--comp-sets", required=True,
                    help="candidate_sets_k*.json from 04_sample_sets.py")
    ap.add_argument("--n-sets", type=int, default=500,
                    help="how many comp sets to build partners for")
    ap.add_argument("--n-draws", type=int, default=3000,
                    help="filler candidates evaluated per comp set")
    ap.add_argument("--n-filler", type=int, default=12)
    ap.add_argument("--seed", type=int, default=20260819)
    ap.add_argument("--out-dir", default=str(cfg.SIMILARITY_RESULTS))
    args = ap.parse_args()

    n = cfg.N_TANGRAMS
    nf = args.n_filler
    E = load_embeddings(n)
    rs = np.random.default_rng(args.seed)

    data = json.load(open(args.comp_sets))
    k = data["k"]
    comp_sets = data["sets"][:args.n_sets]
    print(f"comp pool: k={k}, using {len(comp_sets)} sets from {args.comp_sets}")
    print(f"filler: {nf}+{nf} per set, {args.n_draws} candidates each\n")

    out_sets = []
    t0 = time.time()
    for si, cs in enumerate(comp_sets):
        ctops = cs["trained_tops"] + cs["untrained_tops"]
        cbots = cs["trained_bottoms"] + cs["untrained_bottoms"]
        used = set(ctops) | set(cbots)
        avail = np.array([i for i in range(n) if i not in used])

        # all comp shapes, fixed for this set: the full k x k cross, matching
        # 04's design-independent scoring
        C = np.ascontiguousarray(E[np.ix_(ctops, cbots)]).reshape(k * k, -1)

        best = None
        for _ in range(args.n_draws):
            pick = rs.choice(len(avail), 2 * nf, replace=False)
            ft, fb = avail[pick[:nf]], avail[pick[nf:]]
            # filler wholes are 1:1 -- component i appears only in whole i
            W = np.ascontiguousarray(E[ft, fb])          # (nf, 512)

            ff = W @ W.T                                  # filler x filler
            iu = np.triu_indices(nf, 1)
            fc = W @ C.T                                  # filler x comp
            m = max(float(ff[iu].max()), float(fc.max()))
            if best is None or m < best[0]:
                best = (m, ft.copy(), fb.copy())

        fmax, ft, fb = best
        total = max(fmax, cs["max_sim"])
        out_sets.append({
            "set_id": len(out_sets),
            "comp_set_id": cs["set_id"],
            # shared with the comp set -- post-test items are item-identical
            "trained_tops": cs["trained_tops"], "trained_bottoms": cs["trained_bottoms"],
            "untrained_tops": cs["untrained_tops"], "untrained_bottoms": cs["untrained_bottoms"],
            # filler wholes: zip(filler_tops, filler_bottoms); [0:8] trained, [8:12] held out
            "filler_tops": ft.tolist(), "filler_bottoms": fb.tolist(),
            "n_filler_trained": nf - 4, "n_filler_heldout": 4,
            "max_sim_comp": cs["max_sim"],
            "max_sim_filler": fmax,
            "max_sim": total,
        })

        if (si + 1) % 50 == 0:
            el = time.time() - t0
            print(f"  {si + 1}/{len(comp_sets)}  {(si + 1) / el:.1f} sets/s  "
                  f"eta {(len(comp_sets) - si - 1) / ((si + 1) / el) / 60:.1f}m",
                  flush=True)

    el = time.time() - t0
    fm = np.array([s["max_sim_filler"] for s in out_sets])
    cm = np.array([s["max_sim_comp"] for s in out_sets])
    tm = np.array([s["max_sim"] for s in out_sets])

    print(f"\ndone in {el / 60:.1f} min")
    print(f"  filler max : median={np.median(fm):.4f}  range {fm.min():.4f}-{fm.max():.4f}")
    print(f"  comp max   : median={np.median(cm):.4f}  range {cm.min():.4f}-{cm.max():.4f}")
    print(f"  set max    : median={np.median(tm):.4f}  range {tm.min():.4f}-{tm.max():.4f}")
    print(f"  filler is the binding constraint in {100 * (fm > cm).mean():.1f}% of sets")
    print("  (Exp 1 noncomp shipped at max_sim median 0.602, but over 16 wholes")
    print("   sharing no components -- not comparable to a set containing a")
    print("   recombining 12x12 matrix.)")

    out = Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)
    p = out / f"noncomp_candidate_sets_k{k}.json"
    p.write_text(json.dumps({
        "k": k, "n_filler": nf, "n_draws": args.n_draws, "seed": args.seed,
        "source_comp_sets": str(args.comp_sets),
        "sets": out_sets,
    }, indent=2))
    print(f"\nwrote {p}  ({len(out_sets)} sets)")


if __name__ == "__main__":
    main()
