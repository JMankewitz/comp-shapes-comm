#!/usr/bin/env python3
"""Embed the unique Exp 2 texts. One shard per file, resumable, GPU or CPU.

WHY EMBEDDINGS ARE THE DURABLE ARTEFACT
---------------------------------------
The obvious move is to materialise all pairwise similarities so any analysis can
read them off. At full-study size that is 54k texts -> 1.46 BILLION pairs: 17.5 GB
even as parquet with int32 ids, 292 GB in the Exp 1 CSV format (which stores both
texts in full on every row -- that is why message_similarities.csv is 205 MB for
under a million rows and will not load).

The same information is 221 MB of float32 embeddings. With L2-normalised vectors
cosine is a dot product, so ANY subset's similarity matrix is one matmul,
computed in milliseconds by 05_similarity.py. The embedding store is also
model-agnostic in a way a pair table is not: swapping encoders means re-running
this script, not invalidating a 17 GB derived file.

RESUMABILITY
------------
Each shard writes its own `emb_XXXX.npy` plus a sidecar `.ids.parquet`. A shard
whose output already exists is skipped, so a job killed at shard 19 of 27 resumes
at 19. That is also what lets shards be split across parallel nlprun jobs with
--start_shard/--end_shard; they never touch each other's files.

Usage (laptop, CPU, small corpus):
    python 04_embed.py --device cpu

Usage (cluster, one GPU):
    nlprun -q jag -g 1 -r 40G -c 4 -p low -a compshapes-nlp \\
        'cd /nlp/scr/jmank/comp-shapes && python analysis/exp2/04_embed.py'

Usage (cluster, split across jobs):
    ... 04_embed.py --start_shard 0 --end_shard 14
    ... 04_embed.py --start_shard 14 --end_shard 27
"""

import argparse
import glob
import json
import os
import sys
import time

import numpy as np
import pandas as pd
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))


def load_config(path):
    with open(path) as f:
        return yaml.safe_load(f)


def pick_device(requested):
    if requested != "auto":
        return requested
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
        # Apple Silicon. Works, but slower than CPU for short strings at small
        # batch sizes because of transfer overhead -- fine for a pilot-sized run.
        if torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=os.path.join(HERE, "config.yaml"))
    ap.add_argument("--start_shard", type=int, default=0)
    ap.add_argument("--end_shard", type=int, default=None,
                    help="exclusive; default = all shards")
    ap.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda", "mps"])
    ap.add_argument("--model", default=None, help="override config model")
    ap.add_argument("--tag", default=None,
                    help="output subfolder name (default: model basename). Use "
                         "this to keep a second encoder's vectors alongside the "
                         "first for the robustness check.")
    ap.add_argument("--batch_size", type=int, default=None)
    ap.add_argument("--force", action="store_true", help="re-embed completed shards")
    args = ap.parse_args()

    cfg = load_config(args.config)
    ecfg = cfg["embedding"]
    model_id = args.model or ecfg["model"]
    tag = args.tag or model_id.split("/")[-1]
    batch_size = args.batch_size or int(ecfg["batch_size"])

    out = os.path.join(REPO, cfg["paths"]["out"])
    shard_dir = os.path.join(out, "text_shards")
    emb_dir = os.path.join(out, "embeddings", tag)
    os.makedirs(emb_dir, exist_ok=True)

    shards = sorted(glob.glob(os.path.join(shard_dir, "shard_*.parquet")))
    if not shards:
        sys.exit(f"No shards in {shard_dir}. Run 03_build_corpus.py first.")
    end = args.end_shard if args.end_shard is not None else len(shards)
    todo = shards[args.start_shard:end]
    print(f"model  : {model_id}")
    print(f"shards : {args.start_shard}..{end} of {len(shards)}")

    device = pick_device(args.device)
    print(f"device : {device}")

    # Imported late so --help works without torch installed.
    from sentence_transformers import SentenceTransformer

    t0 = time.time()
    model = SentenceTransformer(model_id, device=device)
    print(f"loaded in {time.time() - t0:.0f}s; dim={model.get_sentence_embedding_dimension()}")

    # Qwen3-Embedding takes an instruction prefix for ASYMMETRIC retrieval. Every
    # comparison in this project is description-to-description, so an instruction
    # applied to one side would bake a retrieval asymmetry into a measure that is
    # supposed to be symmetric. Config pins this to null; honour it explicitly.
    encode_kw = {}
    if ecfg.get("prompt_name"):
        encode_kw["prompt_name"] = ecfg["prompt_name"]
        print(f"WARNING: applying prompt_name={ecfg['prompt_name']} to ALL texts. "
              f"Only do this if both sides of every comparison get it.")

    # ---- content-addressed reuse ------------------------------------------
    # Re-running the referential classifier changes which messages get joined
    # into a round's description, which changes its text, which changes its sha1
    # -- but only for the rounds actually affected. Every other string is
    # unchanged and already has a vector.
    #
    # Without this, a filter revision means re-embedding the whole corpus,
    # because shard membership shifts when the unique-text set changes. With it,
    # a reclassification costs a GPU pass over the handful of new strings.
    cache = {}
    for idf in sorted(glob.glob(os.path.join(emb_dir, "emb_*.ids.parquet"))):
        vf = idf.replace(".ids.parquet", ".npy")
        if not os.path.exists(vf):
            continue
        try:
            old_ids = pd.read_parquet(idf)["text_sha1"].tolist()
            old_vecs = np.load(vf)
            if len(old_ids) == len(old_vecs):
                cache.update(zip(old_ids, old_vecs))
        except Exception as e:
            print(f"  ignoring unreadable {os.path.basename(vf)}: {e}")
    if cache:
        print(f"cache  : {len(cache):,} vectors already computed")

    n_done = 0
    for path in todo:
        sid = os.path.basename(path).replace("shard_", "").replace(".parquet", "")
        vec_path = os.path.join(emb_dir, f"emb_{sid}.npy")
        ids_path = os.path.join(emb_dir, f"emb_{sid}.ids.parquet")
        if os.path.exists(vec_path) and os.path.exists(ids_path) and not args.force:
            # Skip only if the stored ids still match the shard. After a corpus
            # rebuild a shard file can exist but hold the WRONG texts, and
            # skipping it would silently pair old vectors with new strings.
            try:
                stored = pd.read_parquet(ids_path)["text_sha1"].tolist()
                if stored == pd.read_parquet(path)["text_sha1"].tolist():
                    print(f"  shard {sid}: already done, skipping")
                    continue
                print(f"  shard {sid}: contents changed since last run, re-embedding")
            except Exception:
                pass

        df = pd.read_parquet(path)
        t = time.time()
        dim = model.get_sentence_embedding_dimension()
        dtype = ecfg.get("dtype", "float32")
        need = [i for i, h in enumerate(df["text_sha1"]) if h not in cache]
        vecs = np.zeros((len(df), dim), dtype=dtype)
        for i, h in enumerate(df["text_sha1"]):
            if h in cache:
                vecs[i] = cache[h]
        if need:
            new_vecs = model.encode(
                df["text"].iloc[need].tolist(),
                batch_size=batch_size,
                normalize_embeddings=bool(ecfg.get("normalize", True)),
                show_progress_bar=False,
                convert_to_numpy=True,
                **encode_kw,
            ).astype(dtype)
            vecs[need] = new_vecs
            for i, h in zip(need, df["text_sha1"].iloc[need]):
                cache[h] = vecs[i]
        reused = len(df) - len(need)

        # Write to a temp name then rename: a job killed mid-write must not leave
        # a truncated .npy that the resume logic would treat as complete.
        np.save(vec_path + ".tmp.npy", vecs)
        os.replace(vec_path + ".tmp.npy", vec_path)
        df[["text_sha1"]].to_parquet(ids_path + ".tmp", index=False)
        os.replace(ids_path + ".tmp", ids_path)

        n_done += 1
        note = f", {reused:,} reused from cache" if reused else ""
        print(f"  shard {sid}: {len(df):,} texts ({len(need):,} encoded{note}) "
              f"-> {vecs.shape} in {time.time() - t:.1f}s")

    meta = {
        "model": model_id,
        "tag": tag,
        "dim": int(model.get_sentence_embedding_dimension()),
        "dtype": ecfg.get("dtype", "float32"),
        "normalized": bool(ecfg.get("normalize", True)),
        "prompt_name": ecfg.get("prompt_name"),
        "n_shards_total": len(shards),
    }
    with open(os.path.join(emb_dir, "embedding_meta.json"), "w") as f:
        json.dump(meta, f, indent=2)
        f.write("\n")

    have = len(glob.glob(os.path.join(emb_dir, "emb_*.npy")))
    print(f"\n{n_done} shard(s) embedded this run; {have}/{len(shards)} complete in "
          f"{os.path.relpath(emb_dir, REPO)}")
    if have < len(shards):
        print("  (incomplete -- rerun, or launch the remaining --start_shard range)")


if __name__ == "__main__":
    main()
