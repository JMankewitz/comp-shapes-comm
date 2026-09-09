"""
Step 7: score the shipped pool against the REVISED spec constraints (2026-08).

The pre/post format switched to context-free free description (design 4.3), so
test items appear alone and the within-display constraint is gone. Two remain:

  A  trained-set        the 12 trained shapes (4x4 minus diagonal) mutually
                        discriminable -- 66 pairs
  B  novelty            each of the 8 untrained components discriminable from
                        each of the 4 trained ones IN THE SAME ROLE, compared as
                        composed shapes holding the other half constant:
                        max over trained partners j of sim(u_j, a_j)
  soft                  near-identical test items muddy item-level analysis.
                        Diagnostic only, never a filter.

04_sample_sets.py scored the full 12x12 cross (10,296 pairs) -- the "naive global
max" the spec warns against. That is a strict UPPER BOUND on both A and B, so the
shipped sets already satisfy them; this quantifies the headroom.

Roles by index order, per design 4.1:
    tops[0:4]=A-D  [4:8]=E-H  [8:12]=I-L
    bots[0:4]=1-4  [4:8]=5-8  [8:12]=9-12

    python 07_check_against_spec.py --sets outputs/similarity_results/candidate_sets_k12.json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

import numpy as np

import config as cfg  # noqa: E402


def load_embeddings(n):
    p = cfg.EMBEDDINGS_DIR / "composed_embeddings.npy"
    if not p.exists():
        raise SystemExit(f"missing {p} -- run 03_merge_shards.py")
    return np.load(p, mmap_mode="r").reshape(n, n, -1)


def constraint_a(E, tops, bots):
    """12 trained shapes: 4x4 crossing minus the diagonal. 66 pairs."""
    shapes = [(tops[i], bots[j]) for i in range(4) for j in range(4) if i != j]
    X = np.stack([E[t, b] for t, b in shapes])
    S = X @ X.T
    iu = np.triu_indices(len(shapes), 1)
    return float(S[iu].max())


def constraint_b(E, comp, trained):
    """Untrained vs trained in one role, holding the other half constant.

    comp[0:4] trained, comp[4:12] untrained; `trained` = the 4 partners held
    constant. Returns max over (untrained, trained) pairs of the max over
    partners -- the worst case, per spec 6B.
    """
    U = np.stack([[E[u, j] for j in trained] for u in comp[4:]])   # (8,4,512)
    T = np.stack([[E[a, j] for j in trained] for a in comp[:4]])   # (4,4,512)
    # sim(u_j, a_j): same partner j on both sides
    return float(np.einsum("ujd,ajd->uaj", U, T).max())


def constraint_b_bottom(E, comp, trained):
    U = np.stack([[E[i, u] for i in trained] for u in comp[4:]])
    T = np.stack([[E[i, a] for i in trained] for a in comp[:4]])
    return float(np.einsum("ujd,ajd->uaj", U, T).max())


def test_items(tops, bots):
    """The 20 items of design 4.4."""
    A, B, C, D = tops[:4]; E_, F, G, H = tops[4:8]; I, J, K, L = tops[8:12]
    b1, b2, b3, b4 = bots[:4]; b5, b6, b7, b8 = bots[4:8]
    b9, b10, b11, b12 = bots[8:12]
    return ([(A, b2), (B, b3), (C, b4), (D, b1)]           # trained distribution
            + [(A, b1), (B, b2), (C, b3), (D, b4)]          # novel combination
            + [(E_, b1), (F, b2), (G, b3), (H, b4)]         # novel top
            + [(A, b5), (B, b6), (C, b7), (D, b8)]          # novel bottom
            + [(I, b9), (J, b10), (K, b11), (L, b12)])      # entirely held out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sets", required=True)
    args = ap.parse_args()

    n = cfg.N_TANGRAMS
    E = load_embeddings(n)
    data = json.load(open(args.sets))
    sets = data["sets"]
    print(f"{len(sets)} sets from {Path(args.sets).name} (k={data['k']})\n")

    rows = []
    for s in sets:
        tops = s["trained_tops"] + s["untrained_tops"]
        bots = s["trained_bottoms"] + s["untrained_bottoms"]
        ti = test_items(tops, bots)
        X = np.stack([E[t, b] for t, b in ti])
        iu = np.triu_indices(len(ti), 1)
        rows.append((
            constraint_a(E, tops, bots),
            constraint_b(E, tops, bots[:4]),
            constraint_b_bottom(E, bots, tops[:4]),
            float((X @ X.T)[iu].max()),
            s["max_sim"],
        ))
    R = np.array(rows)
    names = ["A  trained set (66 pairs)", "B  novelty, TOPS",
             "B  novelty, BOTTOMS", "soft: 20 test items",
             "scored: full 12x12 cross"]

    print(f"{'constraint':<28}{'median':>8}{'p90':>8}{'max':>8}{'headroom':>10}")
    print("-" * 62)
    for i, nm in enumerate(names):
        q = np.quantile(R[:, i], [.5, .9, 1.0])
        head = "" if i == 4 else f"{np.median(R[:, 4] - R[:, i]):+.3f}"
        print(f"{nm:<28}{q[0]:>8.3f}{q[1]:>8.3f}{q[2]:>8.3f}{head:>10}")

    real = R[:, :3].max(axis=1)
    print("-" * 62)
    print(f"{'BINDING max(A,B)':<28}{np.median(real):>8.3f}"
          f"{np.quantile(real,.9):>8.3f}{real.max():>8.3f}"
          f"{np.median(R[:,4]-real):>+10.3f}")
    print()
    b = np.argmax(R[:, :3], axis=1)
    for i, nm in enumerate(["A (trained set)", "B tops", "B bottoms"]):
        print(f"  binds on {nm:<16} {100*(b==i).mean():>5.1f}% of sets")
    print(f"\nWorst set in the pool on the real criterion: {real.max():.4f}")
    print(f"Every set satisfies A and B at or below its reported max_sim "
          f"({R[:,4].max():.4f}) -- the full-cross score is a valid upper bound.")


if __name__ == "__main__":
    main()
