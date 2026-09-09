"""
Step 8: export search output as experiment-ready set files.

The search artifacts (candidate_sets_*.json, noncomp_candidate_sets_*.json)
carry search metadata and leave the design implicit. This resolves the design
against each set so the experiment code never re-derives it: every component is
named by its design 4.1 role, and training / pre-test / post-test item lists are
written out explicitly with image filenames.

Design resolved here (journal-revision-design.md, 2026-08 revision):

  comp     training  12 shapes = 4x4 trained crossing MINUS the diagonal
           pre/post  the same 20 items (4.4), free description, one at a time

  noncomp  training  16 wholes = 4 diagonal (A1 B2 C3 D4) + 12 filler,
                     minus 4 held-out filler = 12 trained  [matches comp]
           pre       8 items only, component-disjoint (4.6): A1 B2 C3 D4
                     I9 J10 K11 L12. Using the full 20 would demonstrate that
                     shapes decompose -- the exact structure this condition
                     lacks. This is arithmetic, not preference.
           post      the same 20 items as its comp parent

The 20 post-test items are IDENTICAL shapes across conditions; only the cell
labels on the first two cells swap, since comp trains the off-diagonal and
non-comp trains the diagonal. That is what makes the between-condition
comparison item-matched (4.6).

    python 08_export_experiment_sets.py
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

import numpy as np

import config as cfg  # noqa: E402

HERE = Path(__file__).parent
SERVER = HERE.parent.parent / "experiments/compositional-tangrams/server/src"

TOPS = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L"]
BOTS = [str(i) for i in range(1, 13)]


def load_embeddings(n):
    p = cfg.EMBEDDINGS_DIR / "composed_embeddings.npy"
    if not p.exists():
        raise SystemExit(f"missing {p} -- run 03_merge_shards.py")
    return np.ascontiguousarray(np.load(p, mmap_mode="r").reshape(n, n, -1))


def shape(comp, t, b, cell=None):
    d = {"label": f"{t}{b}", "top": comp[t], "bottom": comp[b],
         "image": f"{comp[t]}_{comp[b]}.png"}
    if cell:
        d["cell"] = cell
    return d


def whole(t, b, label, cell=None):
    d = {"label": label, "top": int(t), "bottom": int(b),
         "image": f"{int(t)}_{int(b)}.png"}
    if cell:
        d["cell"] = cell
    return d


def test_items(comp, condition):
    """The 20 items of design 4.4. Same shapes both conditions; the first two
    cell labels swap because non-comp trains the diagonal."""
    diagonal = [("A", "1"), ("B", "2"), ("C", "3"), ("D", "4")]
    offdiag = [("A", "2"), ("B", "3"), ("C", "4"), ("D", "1")]
    if condition == "comp":
        first, second = (offdiag, "trained_distribution"), (diagonal, "novel_combination")
    else:
        first, second = (diagonal, "trained_distribution"), (offdiag, "novel_combination")

    items = [shape(comp, t, b, first[1]) for t, b in first[0]]
    items += [shape(comp, t, b, second[1]) for t, b in second[0]]
    items += [shape(comp, t, b, "novel_top_familiar_bottom")
              for t, b in [("E", "1"), ("F", "2"), ("G", "3"), ("H", "4")]]
    items += [shape(comp, t, b, "familiar_top_novel_bottom")
              for t, b in [("A", "5"), ("B", "6"), ("C", "7"), ("D", "8")]]
    items += [shape(comp, t, b, "entirely_held_out")
              for t, b in [("I", "9"), ("J", "10"), ("K", "11"), ("L", "12")]]
    return items


def similarity_block(E, comp):
    T = [comp[t] for t in TOPS]
    B = [comp[b] for b in BOTS]
    tr = [(i, j) for i in range(4) for j in range(4) if i != j]
    X = np.stack([E[T[i], B[j]] for i, j in tr])
    iu = np.triu_indices(len(tr), 1)
    a = float((X @ X.T)[iu].max())

    U = E[np.ix_(T[4:], B[:4])]; Tr = E[np.ix_(T[:4], B[:4])]
    bt = float(np.einsum("ujd,ajd->uaj", U, Tr).max())
    U2 = E[np.ix_(T[:4], B[4:])].transpose(1, 0, 2)
    Tr2 = E[np.ix_(T[:4], B[:4])].transpose(1, 0, 2)
    bb = float(np.einsum("ujd,ajd->uaj", U2, Tr2).max())

    return {"max_trained_set": round(a, 6),
            "max_novelty_tops": round(bt, 6),
            "max_novelty_bottoms": round(bb, 6),
            "max_binding": round(max(a, bt, bb), 6)}


def build_comp(E, s):
    comp = {}
    tops = s["trained_tops"] + s["untrained_tops"]
    bots = s["trained_bottoms"] + s["untrained_bottoms"]
    for lab, v in zip(TOPS, tops):
        comp[lab] = int(v)
    for lab, v in zip(BOTS, bots):
        comp[lab] = int(v)

    training = [shape(comp, TOPS[i], BOTS[j])
                for i in range(4) for j in range(4) if i != j]
    items = test_items(comp, "comp")
    sim = similarity_block(E, comp)
    sim["max_full_cross_scored"] = round(s["max_sim"], 6)
    return {"set_id": s["set_id"], "condition": "comp", "components": comp,
            "training_shapes": training, "n_training_shapes": len(training),
            "pretest_items": items, "posttest_items": items,
            "similarity": sim}


def build_noncomp(E, s):
    comp = {}
    tops = s["trained_tops"] + s["untrained_tops"]
    bots = s["trained_bottoms"] + s["untrained_bottoms"]
    for lab, v in zip(TOPS, tops):
        comp[lab] = int(v)
    for lab, v in zip(BOTS, bots):
        comp[lab] = int(v)

    ft, fb = s["filler_tops"], s["filler_bottoms"]
    n_tr = s["n_filler_trained"]
    filler_trained = [whole(ft[i], fb[i], f"F{i + 1}") for i in range(n_tr)]
    filler_heldout = [whole(ft[i], fb[i], f"F{i + 1}") for i in range(n_tr, len(ft))]
    diagonal = [shape(comp, t, b) for t, b in
                [("A", "1"), ("B", "2"), ("C", "3"), ("D", "4")]]

    items = test_items(comp, "noncomp")
    pre_labels = {"A1", "B2", "C3", "D4", "I9", "J10", "K11", "L12"}

    sim = similarity_block(E, comp)
    sim["max_full_cross_scored"] = round(s["max_sim_comp"], 6)
    sim["max_filler"] = round(s["max_sim_filler"], 6)

    return {"set_id": s["set_id"], "condition": "noncomp",
            "comp_set_id": s["comp_set_id"], "components": comp,
            "training_shapes": diagonal + filler_trained,
            "n_training_shapes": len(diagonal) + len(filler_trained),
            "heldout_wholes": filler_heldout,
            # 8 items only -- see module docstring
            "pretest_items": [i for i in items if i["label"] in pre_labels],
            "posttest_items": items,
            "similarity": sim}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--comp", default=str(cfg.SIMILARITY_RESULTS / "candidate_sets_k12.json"))
    ap.add_argument("--noncomp", default=str(cfg.SIMILARITY_RESULTS / "noncomp_candidate_sets_k12.json"))
    ap.add_argument("--out-dir", default=str(SERVER))
    ap.add_argument("--n-sets", type=int, default=None)
    args = ap.parse_args()

    n = cfg.N_TANGRAMS
    E = load_embeddings(n)
    out = Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)

    header = {
        "schema_version": "exp2-1",
        "generated": date.today().isoformat(),
        "image_path_template": "/tangrams/{top}_{bottom}.png",
        "component_indices": "0-469, consistent with data/tangram_map.csv",
        "roles": {"trained": "A-D / 1-4", "novel_component": "E-H / 5-8",
                  "entirely_held_out": "I-L / 9-12"},
    }

    for kind, src, builder, note in [
        ("comp", args.comp, build_comp,
         "Training: 4x4 trained crossing minus the diagonal (12 shapes). "
         "Pre- and post-test are the same 20 items, free description, one shape "
         "at a time, no foils and no matcher."),
        ("noncomp", args.noncomp, build_noncomp,
         "Training: 4 diagonal wholes + 8 filler wholes = 12 shapes; 4 further "
         "filler wholes are held out. PRE-TEST IS 8 ITEMS, not 20 -- it must be "
         "component-disjoint or it demonstrates that shapes decompose. "
         "posttest_items are the same 20 shapes as the paired comp set "
         "(comp_set_id); only the trained_distribution / novel_combination cell "
         "labels swap."),
    ]:
        data = json.load(open(src))
        sets = data["sets"][:args.n_sets] if args.n_sets else data["sets"]
        built = [builder(E, s) for s in sets]
        doc = dict(header)
        doc.update({"condition": kind, "n_sets": len(built), "notes": note,
                    "source": Path(src).name, "sets": built})
        p = out / f"exp2_{kind}_sets.json"
        p.write_text(json.dumps(doc, indent=2))
        mb = p.stat().st_size / 1e6
        print(f"wrote {p.name}: {len(built)} sets, {mb:.1f} MB")
        b = built[0]
        print(f"   training={b['n_training_shapes']}  "
              f"pretest={len(b['pretest_items'])}  posttest={len(b['posttest_items'])}"
              f"  binding_sim={b['similarity']['max_binding']}")


if __name__ == "__main__":
    main()
