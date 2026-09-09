#!/usr/bin/env python3
"""Turn the reviewed queue into `referential_flags.parquet`.

This is the ONLY thing that writes the file 03_build_corpus.py reads, and it
writes it only from human decisions. The model's scores are input to a person's
judgement, never a substitute for it -- so a message is dropped from the corpus
if and only if someone looked at it and said to drop it.

    02_referential_filter.py   ->  referential_scores.parquet  (model, no decisions)
                               ->  review_queue.csv            (nominations)
    [you fill in `is_filler`]
    02c_apply_review.py        ->  referential_flags.parquet   (decisions)
    03_build_corpus.py         ->  one description per round

A message that was never nominated is KEPT. A nominated message with a blank
`is_filler` is also kept, and reported -- an unreviewed row must never become a
silent deletion, so the safe default and the lazy default are the same thing.

Usage:
    python 02c_apply_review.py
    python 02c_apply_review.py --queue .../review_queue.new.csv
"""

import argparse
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
ANNO = os.path.join(REPO, "data/processed_data/exp_2/annotation")


def truthy(s):
    return s.astype(str).str.strip().str.upper().isin(["TRUE", "T", "1", "1.0", "YES", "Y"])


def main():
    import yaml
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=os.path.join(HERE, "config.yaml"))
    ap.add_argument("--queue", default=os.path.join(ANNO, "review_queue.csv"))
    args = ap.parse_args()
    with open(args.config) as f:
        cfg = yaml.safe_load(f)

    out = os.path.join(REPO, cfg["paths"]["out"])
    spath = os.path.join(out, "referential_scores.parquet")
    if not os.path.exists(spath):
        sys.exit(f"No scores at {spath} -- run 02_referential_filter.py first.")
    if not os.path.exists(args.queue):
        sys.exit(f"No review queue at {args.queue}.")

    scores = pd.read_parquet(spath)
    q = pd.read_csv(args.queue, dtype=str)
    print(f"  {len(scores):,} scored messages; {len(q):,} nominated for review")

    reviewed = q[q["is_filler"].notna()].copy()
    blank = len(q) - len(reviewed)
    if blank:
        print(f"  {blank:,} nominated row(s) still blank -> KEPT (never silently dropped)")
    if not len(reviewed):
        sys.exit("  nothing reviewed yet; fill in `is_filler` (1 = drop, 0 = keep)")
    reviewed["drop"] = truthy(reviewed["is_filler"])

    # Join on the same key 03_build_corpus.py uses, so a row that cannot be
    # matched here would not have been matched there either -- better to fail
    # loudly now than to lose the decision silently downstream.
    key = ["roundID", "playerID", "text"]
    scores["text"] = scores["text"].astype(str)
    reviewed["text"] = reviewed["text"].astype(str)
    dec = reviewed.groupby(key, as_index=False)["drop"].max()
    merged = scores.merge(dec, on=key, how="left", indicator=True)
    matched = int((merged["_merge"] == "both").sum())
    if matched < len(dec):
        print(f"  WARNING: {len(dec) - matched:,} decision(s) matched no scored "
              f"message. The queue stores whitespace-squished text; if you edited "
              f"the `text` column, the join breaks.")

    merged["chit_chat"] = merged["drop"].astype("boolean").fillna(False).astype(bool)
    merged["method"] = merged.apply(
        lambda r: "human" if r["_merge"] == "both" else "kept_unreviewed", axis=1)

    n = int(merged["chit_chat"].sum())
    over = int((merged["flagged"] & ~merged["chit_chat"]).sum())
    print(f"\n  {n:,} of {len(merged):,} messages dropped as filler "
          f"({100 * n / len(merged):.2f}%)")
    print(f"  {over:,} nomination(s) overruled and kept "
          f"({100 * over / max(1, int(merged['flagged'].sum())):.0f}% of the queue)")
    if "p_filler" in merged and merged["chit_chat"].any():
        agree = merged.loc[merged["_merge"] == "both"]
        if len(agree):
            print(f"  model/human agreement on the queue: "
                  f"{100 * (agree['drop'] == (agree['p_filler'] > 0.5)).mean():.0f}%")

    path = os.path.join(out, "referential_flags.parquet")
    keep = [c for c in ["gameID", "roundID", "playerID", "text", "director_msg",
                        "p_filler", "chit_chat", "method"] if c in merged.columns]
    merged[keep].to_parquet(path, index=False)
    print(f"\n  wrote {os.path.relpath(path, REPO)}")
    print("  03_build_corpus.py joins this on (roundID, playerID, text).")


if __name__ == "__main__":
    main()
