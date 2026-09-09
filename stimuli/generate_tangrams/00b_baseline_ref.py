"""
Step 0b: freeze a reference of the pristine pipeline's actual embeddings.

Step 0 proved the pipeline reproduces comp_sets.json bit-exactly, but max_sim is
one scalar per set -- weak evidence that a refactor preserves the embeddings
themselves. This dumps the raw embedding tensors so 01_validate_refactor.py can
compare elementwise.

Reconstructs src/ from git HEAD into .pristine_src/ rather than importing the
working tree, so it stays valid after src/ has been refactored and can be re-run
at any point to regenerate the reference.

    /opt/anaconda3/envs/compshape-sim/bin/python 00b_baseline_ref.py
"""

import json
import subprocess
import sys
from pathlib import Path

import torch

HERE = Path(__file__).parent
PRISTINE = HERE / ".pristine_src"
OUT = HERE / "data" / "embeddings" / "_baseline_ref.pt"

COMP_SETS = (
    HERE.parent.parent
    / "experiments/compositional-tangrams/server/src/comp_sets.json"
)

REPO_ID = "lil-lab/kilogram-models"
FILE_PATHS = [
    "clip_controlled/whole+black/model0.pth",
    "clip_controlled/whole+black/model1.pth",
    "clip_controlled/whole+black/model2.pth",
]

N_SETS = 6          # same 6 as step 0
N_EXTRA = 128       # extra composed shapes for breadth
SEED = 20260817


def materialize_pristine():
    """Pull src/*.py at git HEAD into .pristine_src/.

    Placed one level under generate_tangrams/ so config.py's
    `Path(__file__).parent.parent` still resolves to the real data root.
    """
    PRISTINE.mkdir(exist_ok=True)
    rel = "stimuli/generate_tangrams/src"
    files = ["config.py", "embedding.py", "similarity.py"]
    root = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=HERE, capture_output=True, text=True, check=True,
    ).stdout.strip()
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=HERE, capture_output=True, text=True, check=True,
    ).stdout.strip()

    for f in files:
        blob = subprocess.run(
            ["git", "show", f"HEAD:{rel}/{f}"],
            cwd=root, capture_output=True, check=True,
        ).stdout
        (PRISTINE / f).write_bytes(blob)

    print(f"materialized pristine src/ from HEAD {head[:10]} -> {PRISTINE}")
    return head


def pick_sets(sets, n):
    ordered = sorted(sets, key=lambda s: s["max_sim"])
    step = (len(ordered) - 1) / (n - 1) if n > 1 else 1
    return [ordered[round(i * step)] for i in range(n)]


def main():
    head = materialize_pristine()
    sys.path.insert(0, str(PRISTINE))

    from config import PROCESSED_TANGRAMS_WHITE
    from embedding import setup_pretrained_model
    from similarity import ImageSet

    sets = json.load(open(COMP_SETS))
    chosen = pick_sets(sets, N_SETS)

    # deterministic image list: the 6 sets' shapes, then extra random pairs
    names = []
    for s in chosen:
        for i in s["top_tangrams"]:
            for j in s["bottom_tangrams"]:
                names.append(f"{i}_{j}")

    g = torch.Generator().manual_seed(SEED)
    extra = torch.randint(0, 470, (N_EXTRA, 2), generator=g)
    for t, b in extra.tolist():
        names.append(f"{t}_{b}")

    # dedupe, preserving order
    seen, ordered_names = set(), []
    for n in names:
        if n not in seen:
            seen.add(n)
            ordered_names.append(n)

    print(f"embedding {len(ordered_names)} unique composed shapes "
          f"({len(chosen)} Exp 1 sets + {N_EXTRA} random)")

    model, preprocess, device = setup_pretrained_model(REPO_ID, FILE_PATHS, None)
    print(f"device={device}  model.training={model.training}")

    paths = [PROCESSED_TANGRAMS_WHITE / f"{n}.png" for n in ordered_names]
    missing = [p for p in paths if not p.exists()]
    if missing:
        raise SystemExit(f"{len(missing)} images missing, e.g. {missing[0]}")

    iset = ImageSet(-1, paths, "comp")
    iset.extract_embeddings(model, preprocess, device)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "git_head": head,
            "torch_version": torch.__version__,
            "device": str(device),
            "model_training_mode": model.training,
            "names": ordered_names,
            "embeddings": iset.embeddings.contiguous(),
            "set_ids": [s["set_id"] for s in chosen],
            "stored_max_sim": [s["max_sim"] for s in chosen],
            "set_tops": [s["top_tangrams"] for s in chosen],
            "set_bottoms": [s["bottom_tangrams"] for s in chosen],
        },
        OUT,
    )

    e = iset.embeddings
    print(f"\nsaved {tuple(e.shape)} {e.dtype} -> {OUT}")
    print(f"norms: min={e.norm(dim=1).min():.8f} max={e.norm(dim=1).max():.8f}")
    print(f"checksum (sum of all elements): {e.double().sum().item():.12f}")


if __name__ == "__main__":
    main()
