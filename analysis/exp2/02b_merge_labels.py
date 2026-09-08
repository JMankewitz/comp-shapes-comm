#!/usr/bin/env python3
"""Merge the recheck pass into the hand labels and report the filler rate.

Produces `dev_labels.csv`, the authoritative label file. `dev_sample.csv` (first
pass) and `recheck.csv` (second pass on the ambiguous rows) are both kept: the
merge is auditable rather than destructive, and the `revised` column marks every
row whose label changed.

THE TWO SHEETS ARE NOT INTERCHANGEABLE.
  sheet A is a uniform random sample -- its base rate is the corpus base rate.
  sheet B over-samples hard cases by construction. Pooling them naively reports
  a filler rate several times the truth. Sheet A alone gives the headline; the
  post-stratified estimate below uses both, correctly weighted.
"""

import csv
import glob
import math
import os
import re
import sys

import pandas as pd

csv.field_size_limit(10 ** 9)

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
ANNO = os.path.join(REPO, "data/processed_data/exp_2/annotation")

# Must match 02a_make_dev_sample.py. Applied in PRIORITY order to make the
# strata disjoint -- a short negation is a negation, counted once.
STRATA = [
    ("negation", lambda s, nw: bool(re.match(r"(?i)^(no|not|nope|without)\b", s))),
    ("meta", lambda s, nw: bool(re.search(
        r"(?i)\b(?:freeze|frozen|lag\w*|glitch|refresh|reload|disconnect|"
        r"internet|wifi|screen|click\w*|button|timer|round|trial|bonus|cents?|"
        r"pay|prolific|survey|director|matcher|partner|score|points?|correct|"
        r"wrong|my turn|your turn)\b", s))),
    ("short", lambda s, nw: nw <= 2),
    ("other", lambda s, nw: True),
]


def truthy(s):
    return s.astype(str).str.strip().str.upper().isin(["TRUE", "1", "1.0", "YES", "Y"])


def squish(t):
    return re.sub(r"\s+", " ", str(t)).strip()


def stratum_of(text):
    s = squish(text)
    nw = len(s.split())
    for name, fn in STRATA:
        if fn(s, nw):
            return name
    return "other"


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return 100 * max(0.0, c - h), 100 * min(1.0, c + h)


def main():
    sample = pd.read_csv(os.path.join(ANNO, "dev_sample.csv"), dtype=str)
    recheck_path = os.path.join(ANNO, "recheck.csv")

    sample["revised"] = False
    if os.path.exists(recheck_path):
        rc = pd.read_csv(recheck_path, dtype=str)
        rc = rc[rc["is_description"].notna()]
        new = dict(zip(rc["row_id"], rc["is_description"]))
        changed = 0
        for i, rid in enumerate(sample["row_id"]):
            if rid in new:
                before = sample.at[i, "is_description"]
                if str(before) != str(new[rid]):
                    changed += 1
                    sample.at[i, "revised"] = True
                sample.at[i, "is_description"] = new[rid]
        print(f"  recheck: {len(new)} rows re-labelled, {changed} changed")
    else:
        print("  no recheck.csv -- using first-pass labels as-is")

    lab = sample[sample["is_description"].notna()].copy()
    lab["filler"] = ~truthy(lab["is_description"])
    unlab = len(sample) - len(lab)
    if unlab:
        print(f"  {unlab} row(s) still unlabelled -- excluded from every rate below")

    out = os.path.join(ANNO, "dev_labels.csv")
    sample.to_csv(out, index=False)
    print(f"  wrote {os.path.relpath(out, REPO)} ({len(lab):,} labelled)\n")

    # ---- headline: sheet A only -------------------------------------------
    a = lab[lab["sheet"] == "A"]
    k, n = int(a["filler"].sum()), len(a)
    lo, hi = wilson(k, n)
    print(f"FILLER RATE (sheet A, uniform random)   {k}/{n} = {100 * k / n:.2f}%"
          f"   95% CI [{lo:.2f}%, {hi:.2f}%]")

    # ---- post-stratified estimate over the whole pilot corpus -------------
    #
    # Sheet A alone is 300 messages and the rare strata land in it only a few
    # times. Reweighting BOTH sheets by each stratum's true share of the corpus
    # uses sheet B's extra labels without letting its fabricated base rate leak
    # into the estimate.
    files = sorted(glob.glob(os.path.join(
        REPO, "data/processed_data/exp_2/pilot_v1", "*", "chats.csv")))
    corpus = pd.concat([pd.read_csv(f, dtype=str, engine="python") for f in files],
                       ignore_index=True).drop_duplicates(
        subset=["roundID", "playerID", "text"])
    corpus = corpus[truthy(corpus["director_msg"])]
    corpus = corpus[corpus["text"].map(lambda t: len(squish(t)) > 0)]
    corpus["stratum"] = corpus["text"].map(stratum_of)
    sizes = corpus["stratum"].value_counts()
    N = int(sizes.sum())

    lab["stratum_d"] = lab["text"].map(stratum_of)
    print(f"\nBY STRATUM (both sheets pooled within stratum; N = {N:,} pilot director msgs)")
    print(f"  {'stratum':10s} {'corpus N':>9s} {'share':>7s} {'labelled':>9s} "
          f"{'filler':>7s} {'rate':>8s}")
    est = 0.0
    var = 0.0
    for st in ["other", "short", "negation", "meta"]:
        Nh = int(sizes.get(st, 0))
        g = lab[lab["stratum_d"] == st]
        if not len(g) or not Nh:
            print(f"  {st:10s} {Nh:9,d} {100 * Nh / N:6.1f}% {len(g):9d}       -        -")
            continue
        nh, ph, Wh = len(g), g["filler"].mean(), Nh / N
        est += Wh * ph
        # Finite-population correction matters here: `negation` and `meta` are
        # CENSUSES (every one in the corpus is labelled), so they contribute no
        # sampling variance at all. Without the correction their 26 and 39
        # observations look like small noisy samples and the interval is a third
        # too wide.
        fpc = max(0.0, 1 - nh / Nh)
        var += (Wh ** 2) * (ph * (1 - ph) / nh) * fpc
        print(f"  {st:10s} {Nh:9,d} {100 * Wh:6.1f}% {nh:9d} "
              f"{int(g['filler'].sum()):7d} {100 * ph:7.1f}%")
    se = math.sqrt(var)
    print(f"\nPOST-STRATIFIED FILLER RATE               {100 * est:.2f}%"
          f"   95% CI [{100 * (est - 1.96 * se):.2f}%, {100 * (est + 1.96 * se):.2f}%]")
    print(f"  ~{round(N * est)} of {N:,} pilot director messages")

    n_rev = int(sample['revised'].sum())
    if n_rev:
        print(f"\n  ({n_rev} label(s) revised on the second pass; `revised` column marks them)")


if __name__ == "__main__":
    main()
