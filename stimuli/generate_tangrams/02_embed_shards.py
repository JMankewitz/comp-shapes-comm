"""
Step 2: embed the 220,900 composed shapes into resumable per-top shards.

One shard = one top index = the 470 composed shapes {top}_{0..469}, saved as a
(470, 512) float32 .npy. 470 shards, ~962 KB each, ~452 MB total.

Why shard by top: it gives 470 independent units of work, so a killed job loses
at most one shard, and --start-shard/--end-shard fans out across cluster nodes
the same way llm_wordsense does. Shards are merged into a single contiguous
memmap by 03_merge_shards.py -- that merged array, not these shards, is what the
set search consumes.

IMPORTANT structural note: a single DataLoader streams the entire shard range,
and shards are sliced out of that stream as they fill. Do not "simplify" this
into one loader per shard. Worker processes cost seconds to fork (each inherits
torch + CLIP), so a loader covering only 470 images spends more time starting
workers than decoding -- benchmarked at 4x SLOWER with 8 workers than with 0.

Resumption is by shard-file existence. Writes go to a .tmp and are renamed, so an
interrupted write can never leave a half-shard that looks complete.

    # smoke test: sweep worker counts, writes nothing
    python 02_embed_shards.py --end-shard 24 --benchmark

    # full local run
    python 02_embed_shards.py

    # one slice on the cluster
    python 02_embed_shards.py --start-shard 0 --end-shard 120
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

import numpy as np
import torch
import yaml

import config as cfg  # noqa: E402
from embedding import embed_stream, setup_pretrained_model  # noqa: E402

HERE = Path(__file__).parent


def load_config(path):
    with open(path) as f:
        c = yaml.safe_load(f)
    c["image_dir"] = Path(c["image_dir"]) if c.get("image_dir") else cfg.PROCESSED_TANGRAMS_WHITE
    c["shard_dir"] = Path(c["shard_dir"]) if c.get("shard_dir") else cfg.EMBEDDING_SHARDS
    return c


def shard_path(shard_dir, top):
    return shard_dir / f"shard_{top:04d}.npy"


def write_shard(shard_dir, top, arr):
    """Atomic write: .tmp then rename, so a kill can't leave a partial shard."""
    final = shard_path(shard_dir, top)
    tmp = final.with_suffix(".npy.tmp")
    # np.save appends ".npy" when handed a PATH that lacks it, which would make
    # this "shard_NNNN.npy.tmp.npy" and break the rename. A file object is
    # written verbatim.
    with open(tmp, "wb") as f:
        np.save(f, arr)
    os.replace(tmp, final)


def embed_tops(tops, c, model, device, batch_size, num_workers, on_shard):
    """Embed every shape for each top in `tops`, calling on_shard(top, arr).

    One DataLoader for the whole list; shards are cut out of the stream as the
    buffer fills. on_shard fires the moment a top's 470 rows are complete, so
    progress is durable even though the loader spans many shards.
    """
    n = c["n_tangrams"]
    paths = [c["image_dir"] / f"{t}_{b}.png" for t in tops for b in range(n)]

    buf = []
    filled = 0
    k = 0
    for _, feats in embed_stream(paths, model, device, batch_size, num_workers,
                                 c.get("prefetch_factor", 2)):
        buf.append(feats)
        filled += feats.shape[0]
        while filled >= n and k < len(tops):
            rows = torch.cat(buf) if len(buf) > 1 else buf[0]
            arr = rows[:n].numpy().astype(np.float32, copy=False)
            if arr.shape != (n, 512):
                raise RuntimeError(f"shard {tops[k]}: got {arr.shape}, want ({n}, 512)")
            on_shard(tops[k], arr)
            k += 1
            rest = rows[n:]
            buf = [rest] if rest.shape[0] else []
            filled = rest.shape[0]

    if k != len(tops):
        raise RuntimeError(f"stream ended after {k}/{len(tops)} shards")
    if filled:
        raise RuntimeError(f"{filled} rows left over -- image list is malformed")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(HERE / "config.yaml"))
    ap.add_argument("--start-shard", type=int, default=0)
    ap.add_argument("--end-shard", type=int, default=None,
                    help="exclusive; defaults to n_tangrams")
    ap.add_argument("--device", default=None, help="overrides config")
    ap.add_argument("--batch-size", type=int, default=None)
    ap.add_argument("--num-workers", type=int, default=None)
    ap.add_argument("--force", action="store_true",
                    help="re-embed shards that already exist")
    ap.add_argument("--benchmark", action="store_true",
                    help="sweep num_workers over the selected range and exit "
                         "without writing anything")
    args = ap.parse_args()

    c = load_config(args.config)
    device = args.device or c["device"]
    batch_size = args.batch_size or c["batch_size"]
    num_workers = c["num_workers"] if args.num_workers is None else args.num_workers

    n = c["n_tangrams"]
    start = args.start_shard
    end = args.end_shard if args.end_shard is not None else n
    if not (0 <= start < end <= n):
        raise SystemExit(f"bad shard range [{start}, {end}) for n_tangrams={n}")

    print("=" * 72)
    print(f"EMBED SHARDS  run={c['run_name']}")
    print("=" * 72)
    print(f"images     : {c['image_dir']}")
    print(f"shards     : {c['shard_dir']}")
    print(f"range      : [{start}, {end})  of {n}")
    print(f"batch/work : {batch_size} / {num_workers}")

    if not c["image_dir"].is_dir():
        raise SystemExit(f"image dir does not exist: {c['image_dir']}")

    print("\nloading FTCLIP...")
    t0 = time.time()
    model, _, device = setup_pretrained_model(
        c["repo_id"], c["model_files"], device, eval_mode=c["eval_mode"])
    print(f"loaded in {time.time() - t0:.1f}s  device={device}  "
          f"training={model.training}")

    # ---------------- benchmark ----------------
    if args.benchmark:
        tops = list(range(start, end))
        n_img = len(tops) * n
        print(f"\nBENCHMARK -- nothing written; {len(tops)} shards "
              f"({n_img} images) per config")
        print("warming up...")
        embed_tops(tops[:1], c, model, device, batch_size, 0, lambda t, a: None)

        print(f"\n{'workers':>8} {'batch':>6} {'sec':>8} {'img/s':>9} "
              f"{'full 220,900':>14}")
        print("-" * 50)
        best = None
        for w in [0, 4, 8]:
            for bs in sorted({batch_size, 128}):
                t0 = time.time()
                embed_tops(tops, c, model, device, bs, w, lambda t, a: None)
                secs = time.time() - t0
                rate = n_img / secs
                print(f"{w:>8} {bs:>6} {secs:>8.1f} {rate:>9.1f} "
                      f"{n * n / rate / 60:>13.1f}m", flush=True)
                if best is None or rate > best[0]:
                    best = (rate, w, bs)
        print("-" * 50)
        print(f"\nfastest: num_workers={best[1]} batch_size={best[2]} "
              f"({best[0]:.0f} img/s, full run ~{n * n / best[0] / 60:.0f} min)")
        print("Set those in config.yaml, then re-run without --benchmark.")
        return

    # ---------------- real run ----------------
    c["shard_dir"].mkdir(parents=True, exist_ok=True)

    todo = [t for t in range(start, end)
            if args.force or not shard_path(c["shard_dir"], t).exists()]
    done_already = (end - start) - len(todo)
    print(f"\n{len(todo)} shards to embed, {done_already} already present")
    if not todo:
        print("nothing to do")
        return

    t_run = time.time()
    state = {"k": 0, "imgs": 0}

    def on_shard(top, arr):
        write_shard(c["shard_dir"], top, arr)
        state["k"] += 1
        state["imgs"] += arr.shape[0]
        elapsed = time.time() - t_run
        rate = state["imgs"] / elapsed
        eta = (len(todo) - state["k"]) * (elapsed / state["k"])
        print(f"[{state['k']:>4}/{len(todo)}] shard {top:>3}  "
              f"{rate:>6.1f} img/s  elapsed {elapsed / 60:>5.1f}m  "
              f"eta {eta / 60:>5.1f}m", flush=True)

    embed_tops(todo, c, model, device, batch_size, num_workers, on_shard)

    elapsed = time.time() - t_run
    print(f"\ndone: {state['imgs']} images in {elapsed / 60:.1f} min "
          f"({state['imgs'] / elapsed:.1f} img/s)")

    manifest = {
        "run_name": c["run_name"],
        "repo_id": c["repo_id"],
        "model_files": c["model_files"],
        "device": str(device),
        "eval_mode": c["eval_mode"],
        "batch_size": batch_size,
        "num_workers": num_workers,
        "torch_version": torch.__version__,
        "shard_range": [start, end],
        "n_shards_written": state["k"],
        "n_images": state["imgs"],
        "seconds": round(elapsed, 1),
        "dtype": "float32",
    }
    mpath = c["shard_dir"] / f"manifest_{start}_{end}.json"
    mpath.write_text(json.dumps(manifest, indent=2))
    print(f"manifest -> {mpath}")


if __name__ == "__main__":
    main()
