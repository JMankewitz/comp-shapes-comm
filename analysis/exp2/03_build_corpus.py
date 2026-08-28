#!/usr/bin/env python3
"""Assemble every Exp 2 text into one corpus, and shard the unique strings for embedding.

WHY A CORPUS STEP
-----------------
Exp 2 produces two kinds of text that all the similarity measures need to compare
against each other:

  * TRAINING  -- the director's message(s) on a reference-game trial, collapsed to
                 one text per (round, director), the way Exp 1 did it.
  * PRE/POST  -- one free description per participant per item.

DV1 (pre->post), DV5 (partner alignment) and DV6 (between-dyad) all compare
descriptions to descriptions; the Brennan & Clark persistence question compares
post-test descriptions to training messages. They therefore have to live in one
embedding space, produced by one model in one pass. Splitting them would make the
cross-phase comparisons depend on two separate encodings.

WHAT IS DELIBERATELY *NOT* DONE HERE
------------------------------------
Filtering. Chit-chat and excluded games are FLAGGED, never dropped:

  * `excluded_game` marks games in excluded_games.csv (AI use, degenerate
    responses). Their text is still embedded, so an exclusion decision can be
    revisited without re-running a GPU job.
  * `chit_chat` is carried through when the referential classifier has run, and
    is null otherwise.

05_similarity.py applies the filters. The embedding store is meant to outlive
any particular set of exclusion criteria -- that is the whole reason it is the
durable artefact rather than a pair table.

DEDUPLICATION
-------------
Embedding is keyed on sha1 of the exact string sent to the model. By block 4 a
dyad's conventions are short and highly repeated ("arrow up", "flat base no
hole"), and identical strings recur across dyads too, so the unique-text count
runs well below the row count. Shards contain unique texts only; corpus.parquet
keeps every occurrence and joins back on text_sha1.

Usage:
    python 03_build_corpus.py                 # all runs found under processed/
    python 03_build_corpus.py --runs pilot_v1/2026-08-25-23-16-22
"""

import argparse
import csv
import glob
import hashlib
import json
import os
import re
import sys

import pandas as pd
import yaml

csv.field_size_limit(10 ** 9)

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))


def load_config(path):
    with open(path) as f:
        return yaml.safe_load(f)


def sha1(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def squish(text):
    """Whitespace normalisation only -- what actually gets embedded.

    Punctuation and case are PRESERVED. Exp 1 stripped both (`re.sub(r'[^\\w\\s]',
    '', text)`) because it fed all-MiniLM-L6-v2, but modern encoders are trained
    on natural text and read "?" and capitalisation as signal. The Exp 1-style
    stripped form is kept alongside as `text_clean` for the lexical measures
    (substring reuse), where punctuation is genuinely noise.
    """
    return re.sub(r"\s+", " ", str(text)).strip()


def clean_lexical(text):
    """Exp 1's normalisation: punctuation stripped, lowercased, squished."""
    t = re.sub(r"[^\w\s]", " ", str(text))
    return re.sub(r"\s+", " ", t).strip().lower()


def read_csv_dedup(paths, key_cols=None):
    """Concatenate CSVs, dropping rows duplicated by re-export.

    Exports overlap by design -- re-exporting mid-study is the encouraged
    workflow -- so the same game legitimately appears in several wave folders. A
    re-exported row is byte-identical to the original, so a full-row distinct is
    the correct dedup and needs no key.
    """
    frames = []
    for p in paths:
        try:
            frames.append(pd.read_csv(p, dtype=str, keep_default_na=False))
        except Exception as e:  # a truncated export should not kill the run
            print(f"  WARNING: could not read {p}: {e}", file=sys.stderr)
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    return df.drop_duplicates(subset=key_cols) if key_cols else df.drop_duplicates()


def discover_runs(processed):
    return sorted(
        os.path.relpath(os.path.dirname(g), processed)
        for g in glob.glob(os.path.join(processed, "**", "games.csv"), recursive=True)
    )


def build(cfg, runs=None):
    processed = os.path.join(REPO, cfg["paths"]["processed"])
    runs = runs or cfg["corpus"]["runs"] or discover_runs(processed)
    if not runs:
        sys.exit(f"No processed runs under {processed}. Run 00_preprocessing.R first.")
    print(f"pooling {len(runs)} run(s): {', '.join(runs)}")

    def paths(name):
        return [os.path.join(processed, r, f"{name}.csv") for r in runs
                if os.path.exists(os.path.join(processed, r, f"{name}.csv"))]

    games = read_csv_dedup(paths("games"), key_cols=["gameID"])
    rounds = read_csv_dedup(paths("rounds"), key_cols=["roundID"])
    chats = read_csv_dedup(paths("chats"))
    descs = read_csv_dedup(paths("descriptions"))
    print(f"  {len(games)} games, {len(rounds)} training rounds, "
          f"{len(chats)} messages, {len(descs)} descriptions")

    excl_path = os.path.join(REPO, cfg["paths"]["excluded_games"])
    excluded = set()
    if os.path.exists(excl_path):
        ex = pd.read_csv(excl_path, dtype=str)
        excluded = set(ex["gameID"].str.strip()) if "gameID" in ex else set()
        print(f"  {len(excluded)} game(s) flagged in excluded_games.csv "
              f"(flagged, NOT dropped -- 05_similarity.py filters)")

    game_cols = [c for c in ["gameID", "contextStructure", "setId", "setReplicate",
                             "compSetId", "rotation"] if c in games.columns]
    gmeta = games[game_cols] if game_cols else pd.DataFrame(columns=["gameID"])

    units = []

    # ---- training: collapse a round's director messages into one text --------
    # One text per (round, director), matching Exp 1 so the training-phase
    # measures stay comparable. `chit_chat` is carried if the classifier has run;
    # messages are NOT dropped here.
    if len(chats):
        c = chats.copy()
        if "director_msg" in c.columns:
            c = c[c["director_msg"].str.upper().isin(["TRUE", "T", "1"])]
        c["text"] = c["text"].map(squish)
        c = c[c["text"].str.len() > 0]
        # 02_referential_filter.py writes flags rather than editing chats.csv, so
        # a reclassification never mutates preprocessed data. Join on
        # (roundID, playerID, text): identical text from the same player in the
        # same round always gets the same label, so a many-to-one join is safe.
        if "chit_chat" not in c.columns:
            c["chit_chat"] = ""
        flags_path = os.path.join(REPO, cfg["paths"]["out"], "referential_flags.parquet")
        if os.path.exists(flags_path):
            fl = pd.read_parquet(flags_path)
            fl = (fl[["roundID", "playerID", "text", "chit_chat"]]
                  .drop_duplicates(subset=["roundID", "playerID", "text"])
                  .rename(columns={"chit_chat": "chit_chat_pred"}))
            c = c.merge(fl, on=["roundID", "playerID", "text"], how="left")
            n_lab = int(c["chit_chat_pred"].notna().sum())
            c["chit_chat"] = c["chit_chat_pred"].fillna(False).map(
                lambda v: "TRUE" if bool(v) else "FALSE")
            c = c.drop(columns=["chit_chat_pred"])
            print(f"  joined referential flags for {n_lab:,}/{len(c):,} messages")
        else:
            print("  no referential_flags.parquet -- chit_chat left unset "
                  "(run 02_referential_filter.py to populate it)")
        # Filter BEFORE joining. The unit of analysis is one description per
        # round, assembled from however many messages the director split it
        # across ("arrow up" ... "with a hole in it"). Concatenating first and
        # flagging the round afterwards would leave "hi" and "yes" inside the
        # text that gets embedded.
        #
        # A round whose director sent nothing referential produces NO unit: there
        # is no description to compare.
        c["_filler"] = c["chit_chat"].astype(str).str.upper().isin(["TRUE", "T", "1"])
        n_before = len(c)
        totals = (c.groupby(["gameID", "roundID", "playerID"], as_index=False)
                    .agg(n_messages_total=("text", "size"),
                         n_messages_filler=("_filler", "sum")))
        c = c[~c["_filler"]]
        print(f"  dropped {n_before - len(c):,} filler message(s) before joining "
              f"({len(c):,} referential messages remain)")
        agg = (c.groupby(["gameID", "roundID", "playerID"], as_index=False)
                 .agg(text=("text", lambda s: ", ".join(s)),
                      n_messages=("text", "size")))
        agg = agg.merge(totals, on=["gameID", "roundID", "playerID"], how="left")
        rcols = [x for x in ["roundID", "trialNum", "repNum", "targetLabel",
                             "target", "setId"] if x in rounds.columns]
        if rcols:
            agg = agg.merge(rounds[rcols].rename(columns={"setId": "round_setId"}),
                            on="roundID", how="left")
        agg["source"] = "training"
        units.append(agg)

    # ---- pre/post descriptions ----------------------------------------------
    if len(descs):
        d = descs.copy()
        d["text"] = d["text"].map(squish)
        d["n_messages"] = 1
        d["n_chit_chat"] = 0
        # phase is 'pretest'/'posttest'; keep it as the source label directly.
        d["source"] = d["phase"] if "phase" in d.columns else "description"
        units.append(d)

    corpus = pd.concat(units, ignore_index=True, sort=False)
    corpus = corpus[corpus["text"].str.len() > 0].reset_index(drop=True)

    # Game-level metadata. Descriptions already carry contextStructure/setId, so
    # only fill what is missing rather than creating _x/_y column pairs.
    if len(gmeta):
        corpus = corpus.merge(gmeta, on="gameID", how="left", suffixes=("", "_game"))
        for col in ["contextStructure", "setId", "setReplicate"]:
            gcol = f"{col}_game"
            if gcol in corpus.columns:
                if col in corpus.columns:
                    corpus[col] = corpus[col].replace("", pd.NA).fillna(corpus[gcol])
                else:
                    corpus[col] = corpus[gcol]
                corpus = corpus.drop(columns=[gcol])

    corpus["excluded_game"] = corpus["gameID"].isin(excluded)
    corpus["text_clean"] = corpus["text"].map(clean_lexical)
    corpus["text_sha1"] = corpus["text"].map(sha1)
    corpus["n_chars"] = corpus["text"].str.len()
    corpus["n_words"] = corpus["text"].str.split().str.len()
    corpus.insert(0, "unit_id", range(len(corpus)))

    # ---- shard the UNIQUE texts ---------------------------------------------
    uniq = (corpus[["text_sha1", "text"]]
            .drop_duplicates(subset="text_sha1")
            .sort_values("text_sha1")     # stable order => stable shard membership
            .reset_index(drop=True))
    per = int(cfg["corpus"]["texts_per_shard"])
    uniq["shard_id"] = uniq.index // per
    n_shards = int(uniq["shard_id"].max()) + 1 if len(uniq) else 0

    out = os.path.join(REPO, cfg["paths"]["out"])
    shard_dir = os.path.join(out, "text_shards")
    os.makedirs(shard_dir, exist_ok=True)
    # Stale shards from a previous, larger corpus would otherwise be embedded and
    # silently merged in.
    for old in glob.glob(os.path.join(shard_dir, "shard_*.parquet")):
        os.remove(old)
    for sid, part in uniq.groupby("shard_id"):
        part[["text_sha1", "text"]].to_parquet(
            os.path.join(shard_dir, f"shard_{sid:04d}.parquet"), index=False)

    corpus.to_parquet(os.path.join(out, "corpus.parquet"), index=False)

    manifest = {
        "runs": runs,
        "n_units": int(len(corpus)),
        "n_unique_texts": int(len(uniq)),
        "n_shards": n_shards,
        "texts_per_shard": per,
        "excluded_games": sorted(excluded),
        "by_source": {k: int(v) for k, v in corpus["source"].value_counts().items()},
        "model": cfg["embedding"]["model"],
    }
    with open(os.path.join(out, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")

    print(f"\n  {len(corpus):,} text units -> {len(uniq):,} unique strings "
          f"({100 * (1 - len(uniq) / max(1, len(corpus))):.0f}% are repeats)")
    for k, v in sorted(manifest["by_source"].items()):
        print(f"    {k:10} {v:,}")
    print(f"  {n_shards} shard(s) in {os.path.relpath(shard_dir, REPO)}")
    print(f"  wrote {os.path.relpath(os.path.join(out, 'corpus.parquet'), REPO)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=os.path.join(HERE, "config.yaml"))
    ap.add_argument("--runs", nargs="*", default=None,
                    help="processed run folders to pool (default: all)")
    args = ap.parse_args()
    build(load_config(args.config), args.runs)


if __name__ == "__main__":
    main()
