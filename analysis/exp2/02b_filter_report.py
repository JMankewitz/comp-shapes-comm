#!/usr/bin/env python3
"""Diagnose the referential classifier against the Exp 1 hand labels.

WHY THIS IS SEPARATE FROM --validate
------------------------------------
`--validate` prints precision/recall/F1. Those summary numbers hid the failure
that actually mattered: a 3B model scored a respectable-looking F1 while wrongly
dropping 18% of ONE-WORD descriptions, and a 7B model made it worse (35%). Short
and contrastive is exactly what a conventionalised reference looks like by block
4, so an aggregate metric can look acceptable while the classifier deletes the
signal the study exists to measure.

This reads the cached P(filler) scores and reports the three things that caught
it: the threshold sweep, the error rate BY MESSAGE LENGTH, and sampled
disagreements you can actually read.

Runs on your laptop against an rsynced cache -- no GPU, seconds.

Usage:
    python 02b_filter_report.py                       # newest cache found
    python 02b_filter_report.py --model Qwen/Qwen2.5-7B-Instruct
    python 02b_filter_report.py --show 40             # more sampled errors
"""

import argparse
import glob
import os
import re
import sys

import numpy as np
import pandas as pd
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

NEG = re.compile(r"^(?:no|not|nope|isn'?t|doesn'?t|without)\b", re.I)


def squish(t):
    return re.sub(r"\s+", " ", str(t)).strip()


def rule_label(text):
    """Imported lazily from the classifier so the two never drift apart."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "rf", os.path.join(HERE, "02_referential_filter.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.rule_label(text)


def load_gold():
    frames = []
    for f in sorted(glob.glob(os.path.join(
            REPO, "data/processed_data/exp_1/run_v3/*/chats.csv"))):
        frames.append(pd.read_csv(f, dtype=str, keep_default_na=False))
    if not frames:
        sys.exit("No Exp 1 run_v3 chats found -- nothing to validate against.")
    g = pd.concat(frames, ignore_index=True).drop_duplicates()
    g["text"] = g["text"].map(squish)
    g = g[(g["text"].str.len() > 0)
          & g["director_msg"].str.upper().isin(["TRUE", "T"])]
    g["gold"] = g["chit_chat"].str.upper().isin(["TRUE", "T"])
    return g.reset_index(drop=True)  # keeps roundID for the context-aware join


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=os.path.join(HERE, "config.yaml"))
    ap.add_argument("--model", default=None, help="filter caches by model id")
    ap.add_argument("--cache", default=None,
                    help="explicit cache file. Two prompt styles for the same "
                         "model share a slug, so --model alone picks whichever "
                         "is newer -- name the file to compare them.")
    ap.add_argument("--show", type=int, default=25)
    args = ap.parse_args()

    with open(args.config) as f:
        cfg = yaml.safe_load(f)
    out = os.path.join(REPO, cfg["paths"]["out"])

    if args.cache:
        caches = [args.cache if os.path.isabs(args.cache)
                  else os.path.join(out, args.cache)]
        if not os.path.exists(caches[0]):
            sys.exit(f"No such cache: {caches[0]}")
    else:
        caches = sorted(glob.glob(os.path.join(out, "llm_labels_*.parquet")),
                        key=os.path.getmtime)
    if args.model and not args.cache:
        slug = re.sub(r"[^A-Za-z0-9]+", "-", args.model).strip("-")
        caches = [c for c in caches if slug in os.path.basename(c)]
    if not caches:
        sys.exit(f"No label cache in {out}. rsync it down from the cluster first.")
    cache = caches[-1]
    c = pd.read_parquet(cache)
    print(f"cache : {os.path.basename(cache)}  ({len(c):,} texts scored)")
    if "p_filler" not in c.columns:
        c["p_filler"] = c["chit_chat"].astype(float)
        print("  (old cache: booleans only, threshold sweep unavailable)")

    p = c["p_filler"].values
    bins = [(0, .1), (.1, .3), (.3, .5), (.5, .7), (.7, .9), (.9, 1.01)]
    print("  P(filler) distribution: " + "  ".join(
        f"{lo:.1f}-{hi:.1f}:{int(((p >= lo) & (p < hi)).sum()):,}" for lo, hi in bins))

    # Cache keys are "roundID|text" once messages are scored in context (the
    # same string in two rounds is two questions). Older caches are bare text.
    keyed = c["text"].astype(str).str.contains("|", regex=False)
    g = load_gold()
    if keyed.mean() > 0.5:
        parts = c["text"].astype(str).str.split("|", n=1, expand=True)
        c = c.assign(roundID=parts[0], msg=parts[1])
        lab = dict(zip(zip(c["roundID"], c["msg"]), c["p_filler"]))
        g["p"] = [lab.get((r, t)) for r, t in zip(g["roundID"], g["text"])]
        print("  (context-scored cache: joined on roundID + text)")
    else:
        lab = dict(zip(c["text"], c["p_filler"]))
        g["p"] = g["text"].map(lab)
    d = g[g["p"].notna()].copy()
    d["nw"] = d["text"].str.split().str.len()
    print(f"joined: {len(d):,} gold messages scored "
          f"({int(d['gold'].sum()):,} hand-labelled filler, "
          f"{100 * d['gold'].mean():.1f}%)\n")

    print("threshold sweep (chit-chat class):")
    for th in (0.3, 0.5, 0.7, 0.9, 0.95):
        pr = d["p"] > th
        tp = int((pr & d["gold"]).sum()); fp = int((pr & ~d["gold"]).sum())
        fn = int((~pr & d["gold"]).sum())
        P = tp / (tp + fp) if tp + fp else 0
        R = tp / (tp + fn) if tp + fn else 0
        F = 2 * P * R / (P + R) if P + R else 0
        print(f"  {th:>4}   precision {P:.3f}  recall {R:.3f}  F1 {F:.3f}"
              f"   (tp={tp:,} fp={fp:,} fn={fn:,})")

    th = float(cfg["referential"].get("threshold", 0.5))
    print(f"\nDROP RATE ON REAL DESCRIPTIONS by length (threshold {th}):")
    print("  this is the number that matters -- conventionalised references are SHORT")
    neg = d[~d["gold"]]
    for lo, hi in [(1, 1), (2, 2), (3, 3), (4, 5), (6, 8), (9, 99)]:
        s = neg[(neg["nw"] >= lo) & (neg["nw"] <= hi)]
        if len(s):
            rate = 100 * (s["p"] > th).mean()
            flag = "  <-- HIGH" if rate > 10 else ""
            print(f"    {lo:>2}-{hi:<3} words  n={len(s):>6,}  dropped {rate:>5.1f}%{flag}")
    negated = neg[neg["text"].str.match(NEG)]
    if len(negated):
        print(f"    negated ('no X')  n={len(negated):>6,}  "
              f"dropped {100 * (negated['p'] > th).mean():>5.1f}%")

    fp = d[(d["p"] > th) & (~d["gold"])].sort_values("p", ascending=False)
    fn = d[(d["p"] <= th) & (d["gold"])]
    print(f"\n=== {args.show} most confident FALSE POSITIVES "
          f"(dropped, gold says referential) ===")
    print("  read these: are they real descriptions, or filler you did not mark?")
    for t in fp["text"].drop_duplicates().head(args.show):
        print(f"    {t[:95]}")
    print(f"\n=== {min(args.show, 15)} FALSE NEGATIVES (kept, gold says filler) ===")
    for t in fn["text"].drop_duplicates().head(min(args.show, 15)):
        print(f"    {t[:95]}")

    print("\nReminder: precision against this gold set understates the classifier.")
    print("Hand-coding caught 87% of unambiguous filler standing alone in a round")
    print("and 61% beside other messages, so some 'false positives' are real filler")
    print("that was never marked. The length breakdown above is the honest signal.")


if __name__ == "__main__":
    main()
