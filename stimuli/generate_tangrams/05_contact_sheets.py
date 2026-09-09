"""
Step 5: render similarity checks as image grids for visual inspection.

Two modes, both answering "does the number match what I see?"

  --sets <json>   For each shipped set, its N most-similar pairs of composed
                  shapes side by side. This is the post-hoc discriminability
                  check: if the worst pair in a set looks clearly different,
                  the set is fine regardless of its max-sim value.

  --duplicates    The globally most-confusable COMPONENT pairs in the 470-tangram
                  bank, shown both as raw components and composed against a
                  common partner. Some components are near-duplicates of each
                  other (246/300 at 0.96); this shows whether they are similar
                  enough to be worth excluding from sampling entirely.

    python 05_contact_sheets.py --sets outputs/similarity_results/candidate_sets_k12.json
    python 05_contact_sheets.py --duplicates
"""

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

import config as cfg  # noqa: E402

HERE = Path(__file__).parent
OUT = cfg.OUTPUT_DIR / "contact_sheets"
N = cfg.N_TANGRAMS


def embeddings():
    p = cfg.EMBEDDINGS_DIR / "composed_embeddings.npy"
    if not p.exists():
        raise SystemExit(f"missing {p} -- run 03_merge_shards.py")
    return np.load(p, mmap_mode="r").reshape(N, N, -1)


def composed(top, bottom):
    return Image.open(cfg.PROCESSED_TANGRAMS_WHITE / f"{top}_{bottom}.png")


def component(i):
    rows = list(csv.reader(open(cfg.MAPPING_FILE)))
    name = {int(r[1]): r[0].split("/")[-1] for r in rows}[i]
    return Image.open(cfg.PROCESSED_PNGS / name)


def worst_pairs(E, tops, bots, n_pairs):
    """The n most-similar pairs among this set's composed shapes."""
    k_t, k_b = len(tops), len(bots)
    shapes = [(t, b) for t in tops for b in bots]
    X = E[np.ix_(tops, bots)].reshape(k_t * k_b, -1)
    S = X @ X.T
    iu = np.triu_indices(len(shapes), 1)
    v = S[iu]
    order = np.argsort(v)[::-1][:n_pairs]
    return [(shapes[iu[0][o]], shapes[iu[1][o]], float(v[o])) for o in order]


def sheet_sets(args):
    data = json.load(open(args.sets))
    k = data["k"]
    pool = data["sets"]

    # --worst shows the bottom of the ranked pool, which is the informative end
    # once the pool is large: the top set is not what you are shipping against.
    if args.worst:
        start = max(0, len(pool) - args.n_sets)
    else:
        start = min(args.from_rank, max(0, len(pool) - 1))
    sets = pool[start:start + args.n_sets]
    end = start + len(sets)

    E = embeddings()
    rows, cols = len(sets), 2 * args.n_pairs
    fig, ax = plt.subplots(rows, cols, figsize=(2.0 * cols, 2.3 * rows))
    ax = np.atleast_2d(ax)

    for r, s_ in enumerate(sets):
        tops = s_["trained_tops"] + s_["untrained_tops"]
        bots = s_["trained_bottoms"] + s_["untrained_bottoms"]
        for p_, (a, b, sim) in enumerate(worst_pairs(E, tops, bots, args.n_pairs)):
            for c, shape in enumerate((a, b)):
                A = ax[r, 2 * p_ + c]
                A.imshow(composed(*shape)); A.axis("off")
                A.set_title(f"{shape[0]}_{shape[1]}", fontsize=7)
            ax[r, 2 * p_ + 1].text(1.04, 0.5, f"{sim:.3f}",
                                   transform=ax[r, 2 * p_ + 1].transAxes,
                                   fontsize=9, ha="left", va="center")
        ax[r, 0].text(-0.18, 0.5,
                      f"rank {s_['set_id']}\nmax {s_['max_sim']:.3f}\n"
                      f"z {s_['z_vs_distribution']:+.2f}",
                      transform=ax[r, 0].transAxes,
                      fontsize=8, ha="right", va="center")

    where = "WORST" if args.worst or start > 0 else "best"
    fig.suptitle(f"k={k}: {args.n_pairs} most-similar pairs in the {where} sets "
                 f"of the kept pool (ranks {start}-{end - 1} of {len(pool)})",
                 fontsize=12)
    fig.tight_layout(rect=[0.03, 0, 0.98, 0.96])
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"worst_pairs_k{k}_rank{start}-{end - 1}.png"
    fig.savefig(out, dpi=110); plt.close(fig)
    print(f"wrote {out}")


def sheet_duplicates(args):
    E = embeddings()
    rs = np.random.default_rng(0)
    J = rs.choice(N, 24, replace=False)

    X = np.ascontiguousarray(E[:, J, :])
    Stop = np.einsum("ijd,kjd->ik", X, X) / len(J)
    Y = np.ascontiguousarray(E[J, :, :]).transpose(1, 0, 2)
    Sbot = np.einsum("ijd,kjd->ik", Y, Y) / len(J)
    S = np.maximum(Stop, Sbot)
    np.fill_diagonal(S, -9)
    iu = np.triu_indices(N, 1)
    v = S[iu]
    order = np.argsort(v)[::-1][:args.n_pairs]

    partner = int(rs.choice(N))
    rows = len(order)
    fig, ax = plt.subplots(rows, 4, figsize=(9, 2.2 * rows))
    ax = np.atleast_2d(ax)
    for r, o in enumerate(order):
        a, b = int(iu[0][o]), int(iu[1][o])
        for c, img, lab in [(0, component(a), f"component {a}"),
                            (1, component(b), f"component {b}"),
                            (2, composed(a, partner), f"{a}_{partner}"),
                            (3, composed(b, partner), f"{b}_{partner}")]:
            ax[r, c].imshow(img); ax[r, c].axis("off")
            ax[r, c].set_title(lab, fontsize=8)
        ax[r, 0].text(-0.2, 0.5, f"{v[o]:.3f}", transform=ax[r, 0].transAxes,
                      fontsize=10, ha="right", va="center")

    fig.suptitle(f"Most-confusable component pairs in the 470-tangram bank\n"
                 f"(raw components, then each composed with tangram {partner})",
                 fontsize=12)
    fig.tight_layout(rect=[0.03, 0, 1, 0.95])
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / "confusable_components.png"
    fig.savefig(p, dpi=110); plt.close(fig)
    print(f"wrote {p}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sets", help="candidate_sets_k*.json from 04_sample_sets.py")
    ap.add_argument("--duplicates", action="store_true")
    ap.add_argument("--worst", action="store_true",
                    help="show the bottom of the ranked pool")
    ap.add_argument("--from-rank", type=int, default=0)
    ap.add_argument("--n-sets", type=int, default=8)
    ap.add_argument("--n-pairs", type=int, default=3)
    args = ap.parse_args()
    if not args.sets and not args.duplicates:
        ap.error("pass --sets <json> and/or --duplicates")
    if args.sets:
        sheet_sets(args)
    if args.duplicates:
        sheet_duplicates(args)


if __name__ == "__main__":
    main()
