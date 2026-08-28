#!/usr/bin/env python3
"""Materialise the analysis pair tables from the embedding store.

WHY NOT ALL PAIRS
-----------------
At full-study size the corpus is ~54k texts, so the full cross product is 1.46
BILLION pairs -- 17.5 GB as parquet, 292 GB in the Exp 1 CSV layout. Almost all of
it is meaningless: one dyad's description of shape A against another dyad's
description of shape Z, which no analysis ever asks for.

The five tables below are the structured subsets the DVs actually use. Together
they are smaller than Exp 1's single message_similarities.csv. Anything not
covered here is one matmul away -- `load_store()` and `pair_frame()` are the
public helpers, and a notebook can compute an ad-hoc block in milliseconds
without regenerating anything.

TEXT IS NEVER WRITTEN INTO A PAIR TABLE
---------------------------------------
Exp 1's CSV stored text1 and text2 in full on every row: ~180 bytes of duplicated
string per 8-byte similarity, which is why 970k rows became 205 MB and will not
load. These tables carry unit_id pairs only; join back to corpus.parquet for text.

Usage:
    python 05_similarity.py                       # every table in config
    python 05_similarity.py --tables pre_post partner_alignment
    python 05_similarity.py --tag MiniLM-L6-v2    # a different encoder's vectors
"""

import argparse
import glob
import itertools
import json
import os
import sys

import numpy as np
import pandas as pd
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))


def load_config(path):
    with open(path) as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

def load_store(cfg, tag):
    """corpus rows + a matrix whose row i is the embedding of corpus row i.

    The embedding files are keyed by text_sha1 (unique strings). Corpus rows are
    occurrences, so several rows share a vector. Rather than materialise a
    (n_units x dim) copy, map each unit to its row in the unique matrix and index
    through that -- numpy fancy-indexing on demand is cheaper than the copy.
    """
    out = os.path.join(REPO, cfg["paths"]["out"])
    corpus = pd.read_parquet(os.path.join(out, "corpus.parquet"))

    emb_dir = os.path.join(out, "embeddings", tag)
    vec_files = sorted(glob.glob(os.path.join(emb_dir, "emb_*.npy")))
    id_files = sorted(glob.glob(os.path.join(emb_dir, "emb_*.ids.parquet")))
    if not vec_files:
        sys.exit(f"No embeddings in {emb_dir}. Run 04_embed.py first.")
    if len(vec_files) != len(id_files):
        sys.exit(f"{emb_dir}: {len(vec_files)} vector files but {len(id_files)} id "
                 f"files -- a shard wrote one and not the other. Rerun 04_embed.py.")

    vecs = np.concatenate([np.load(f) for f in vec_files], axis=0)
    ids = pd.concat([pd.read_parquet(f) for f in id_files], ignore_index=True)
    if len(vecs) != len(ids):
        sys.exit(f"{emb_dir}: {len(vecs)} vectors vs {len(ids)} ids")

    row_of = pd.Series(np.arange(len(ids)), index=ids["text_sha1"].values)
    missing = ~corpus["text_sha1"].isin(row_of.index)
    if missing.any():
        sys.exit(f"{int(missing.sum())} corpus texts have no embedding. The corpus "
                 f"was rebuilt after embedding; rerun 04_embed.py.")
    corpus = corpus.copy()
    corpus["vec_row"] = row_of.reindex(corpus["text_sha1"].values).values

    # Cosine == dot product only if the vectors are unit length. 04_embed.py
    # normalises, but a hand-made store might not; check rather than assume.
    norms = np.linalg.norm(vecs[: min(1000, len(vecs))], axis=1)
    if not np.allclose(norms, 1.0, atol=1e-3):
        print("  normalising embeddings (stored vectors were not unit length)")
        vecs = vecs / np.clip(np.linalg.norm(vecs, axis=1, keepdims=True), 1e-12, None)
    return corpus, vecs


def analysable(corpus, drop_excluded=True, drop_chitchat=True):
    """Game-level exclusions.

    Chit-chat is NOT handled here any more. Because the surviving messages are
    concatenated into one description per round, filtering has to happen before
    the join -- 03_build_corpus.py drops filler messages and emits no unit at all
    for a round whose director said nothing referential. `drop_chitchat` is kept
    as a no-op argument so the CLI flag and call sites stay stable.
    """
    m = pd.Series(True, index=corpus.index)
    if drop_excluded:
        m &= ~corpus["excluded_game"].astype(bool)
    return corpus[m]


def pair_frame(df_a, df_b, vecs, keys, same=False):
    """Cosine between two sets of corpus rows, as a long frame.

    `same=True` means df_a is df_b and only the upper triangle is wanted (cosine
    is symmetric, so storing both directions doubles the file for no information).
    """
    if len(df_a) == 0 or len(df_b) == 0:
        return pd.DataFrame()
    A = vecs[df_a["vec_row"].values]
    B = vecs[df_b["vec_row"].values]
    S = A @ B.T
    if same:
        ia, ib = np.triu_indices(len(df_a), k=1)
    else:
        ia, ib = (np.repeat(np.arange(len(df_a)), len(df_b)),
                  np.tile(np.arange(len(df_b)), len(df_a)))
    if len(ia) == 0:
        return pd.DataFrame()
    out = {"similarity": S[ia, ib].astype("float32")}
    for k in keys:
        if k in df_a.columns:
            out[f"{k}_a"] = df_a[k].values[ia]
            out[f"{k}_b"] = df_b[k].values[ib]
    return pd.DataFrame(out)


def grouped_pairs(df, group_cols, keys, split_col=None):
    """Within each group, all pairs (or all cross-`split_col` pairs)."""
    frames = []
    for gvals, g in df.groupby(group_cols, dropna=True, observed=True):
        if len(g) < 2:
            continue
        if split_col is None:
            f = pair_frame(g, g, VECS, keys, same=True)
        else:
            # Cross-group only: e.g. partner alignment wants A-vs-B, never A-vs-A.
            parts = [p for _, p in g.groupby(split_col, observed=True)]
            if len(parts) < 2:
                continue
            f = pd.concat(
                [pair_frame(x, y, VECS, keys) for x, y in itertools.combinations(parts, 2)],
                ignore_index=True)
        if len(f) == 0:
            continue
        for col, val in zip(group_cols if isinstance(group_cols, list) else [group_cols],
                            gvals if isinstance(gvals, tuple) else (gvals,)):
            f[col] = val
        frames.append(f)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# ---------------------------------------------------------------------------
# The tables
# ---------------------------------------------------------------------------
KEYS = ["unit_id", "gameID", "playerID", "repNum", "roundID", "image", "phase",
        "cell", "targetLabel", "order"]


def t_within_dyad_same_target(corpus):
    """Conventionalisation: the same dyad describing the same shape across blocks.

    Exp 1's headline convention measure. Restricted to training, grouped by
    (game, target), so every pair is two blocks' descriptions of one shape.
    """
    d = corpus[corpus["source"] == "training"]
    d = d[d["targetLabel"].notna() & (d["targetLabel"] != "")]
    return grouped_pairs(d, ["gameID", "targetLabel"], KEYS)


def t_within_block(corpus):
    """Systematicity: all pairs of director texts inside one block.

    High within-block similarity across DIFFERENT shapes is the signature of a
    systematic scheme -- descriptions built from shared parts rather than
    unrelated wholes.
    """
    d = corpus[corpus["source"] == "training"]
    d = d[d["repNum"].notna() & (d["repNum"] != "")]
    return grouped_pairs(d, ["gameID", "repNum"], KEYS)


def t_partner_alignment(corpus):
    """DV5: the two partners' descriptions of the same item, within a phase.

    Only possible because both partners describe every item (S4.3). The pre-test
    value is the per-item baseline for how much two naive people converge by
    visual accident; the gain from pre to post is the alignment DV.
    """
    d = corpus[corpus["source"].isin(["pretest", "posttest"])]
    return grouped_pairs(d, ["gameID", "source", "image"], KEYS, split_col="playerID")


def t_between_dyad_same_item(corpus):
    """DV6: different dyads, same stimulus set, same condition, same item.

    The chance level that makes DV1 and DV5 interpretable (S4.8). Requires the
    flat allocation -- two dyads per condition per set -- and joins on `image`
    rather than `label`, because a label means different things in the comp and
    noncomp files (see the header of exp2.js).
    """
    d = corpus[corpus["source"].isin(["pretest", "posttest"])]
    return grouped_pairs(d, ["setId", "contextStructure", "source", "image"],
                         KEYS, split_col="gameID")


def t_pre_post(corpus):
    """DV1: the same person describing the same shape before and after training."""
    d = corpus[corpus["source"].isin(["pretest", "posttest"])]
    return grouped_pairs(d, ["playerID", "image"], KEYS, split_col="source")


TABLES = {
    "within_dyad_same_target": t_within_dyad_same_target,
    "within_block": t_within_block,
    "partner_alignment": t_partner_alignment,
    "between_dyad_same_item": t_between_dyad_same_item,
    "pre_post": t_pre_post,
}


def main():
    global VECS
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=os.path.join(HERE, "config.yaml"))
    ap.add_argument("--tag", default=None, help="embedding folder (default: model basename)")
    ap.add_argument("--tables", nargs="*", default=None)
    ap.add_argument("--keep-excluded", action="store_true",
                    help="do not drop games listed in excluded_games.csv")
    ap.add_argument("--keep-chitchat", action="store_true")
    args = ap.parse_args()

    cfg = load_config(args.config)
    tag = args.tag or cfg["embedding"]["model"].split("/")[-1]
    corpus, VECS = load_store(cfg, tag)
    print(f"store  : {len(corpus):,} units, {VECS.shape[0]:,} unique vectors "
          f"({VECS.shape[1]}d), tag={tag}")

    keep = analysable(corpus, not args.keep_excluded, not args.keep_chitchat)
    print(f"filter : {len(keep):,} analysable units "
          f"({len(corpus) - len(keep):,} dropped: excluded games)")

    out = os.path.join(REPO, cfg["paths"]["out"], "similarities", tag)
    os.makedirs(out, exist_ok=True)
    wanted = args.tables or cfg["similarity"]["tables"]

    summary = {}
    for name in wanted:
        if name not in TABLES:
            print(f"  {name}: unknown table, skipping", file=sys.stderr)
            continue
        df = TABLES[name](keep)
        path = os.path.join(out, f"{name}.parquet")
        df.to_parquet(path, index=False)
        mb = os.path.getsize(path) / 1e6
        summary[name] = {"rows": int(len(df)), "mb": round(mb, 2)}
        mean = f"{df['similarity'].mean():.3f}" if len(df) else "n/a"
        print(f"  {name:26} {len(df):>9,} rows  {mb:>7.2f} MB  mean sim {mean}")

    with open(os.path.join(out, "similarity_meta.json"), "w") as f:
        json.dump({"tag": tag, "n_units_analysable": int(len(keep)),
                   "tables": summary}, f, indent=2)
        f.write("\n")
    total = sum(v["mb"] for v in summary.values())
    print(f"\n  {total:.1f} MB total in {os.path.relpath(out, REPO)}")
    print("  (join unit_id_a / unit_id_b back to corpus.parquet for text)")


if __name__ == "__main__":
    main()
