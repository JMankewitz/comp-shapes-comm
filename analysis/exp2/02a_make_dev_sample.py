#!/usr/bin/env python3
"""Draw the hand-labelling sheet for the Exp 2 referential/filler classifier.

WHY THIS EXISTS
---------------
Exp 1's `chit_chat` column is the only gold set we have, and it is not good
enough to tune against. Measured on run_v3's 37,510 director messages: of the
741 that are unambiguous filler under the narrowest possible rule, the hand
labels mark only 505. It misses 236 -- 115 bare "yes", 44 bare "no". The errors
run almost entirely one way (chit-chat marked as description, not the reverse),
so a classifier's FALSE POSITIVES are inflated by gold's own misses and its
PRECISION against that gold cannot be read as precision. Recall is the only
direction that survives.

Exp 2 also does not look like Exp 1. In the pilot, the screen-position confusion
that the Exp 1 prompt spends its longest section on occurs twice in 1,699
messages. Tuning against Exp 1 optimises for a failure that no longer happens.

So: a few hundred in-domain labels, drawn here, filled in by hand. That fixes
gold-set noise and domain shift in one move and gives the classifier an honest
number to be measured against.

WHAT YOU GET
------------
One CSV, two sheets, kept separate ON PURPOSE:

  sheet A -- a uniform random sample. Its base rate is the real base rate, so
             this is the ONLY sheet that may be used for overall accuracy,
             precision, recall, or the filler rate.
  sheet B -- deliberately over-sampled hard cases (short messages, negation,
             interface talk). DIAGNOSTIC ONLY. Its base rate is fabricated by
             construction; averaging it into sheet A silently corrupts every
             rate you report.

HOW TO FILL IT IN
-----------------
Open in Excel/Numbers. For each row put 1 or 0 in `is_description`:

    1 = this message says something about what the TARGET SHAPE looks like
        (including very short conventions -- "fish", "K", "down arrow" -- and
        negations that carry content -- "no hole", "not the triangle")
    0 = it does not (greetings, bare yes/no, reactions, interface or study talk)

`round_context` shows the whole round with the message under judgement wrapped
in >>> <<<. Judge THAT message, using the context to disambiguate it.

Leave a row blank if you genuinely cannot decide; blanks are dropped from
scoring rather than guessed at. Use `note` for anything you want to remember.

NOTE THE POLARITY. This column is `is_description`, not `chit_chat`. 1 means
KEEP. Exp 1's column runs the other way and the double negative is a large part
of why this has been confusing; the loader inverts it in one place.

Usage:
    python 02a_make_dev_sample.py                 # pilot_v1 -> dev_sample.csv
    python 02a_make_dev_sample.py --n-random 400  # a bigger sheet A
"""

import argparse
import csv
import glob
import os
import re
import sys

import pandas as pd

csv.field_size_limit(10 ** 9)

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))

# The three families where the judgement is actually hard in EXP 2, measured on
# the pilot rather than inherited from Exp 1. Screen-position talk is not among
# them: it occurs twice in 1,699 messages.
BOUNDARY = {
    # Conventions get shorter with practice, so most short messages are the most
    # important data in the corpus -- and a few are bare acknowledgements. This
    # is where a wrong call is most expensive.
    "short": lambda s, nw: nw <= 2,
    # "no hole" is a description; bare "no" is not. A 7B model dropped 89% of
    # these when the prompt told it "no" was filler.
    "negation": lambda s, nw: bool(re.match(r"(?i)^(no|not|nope|without)\b", s)),
    # On-task but not about the shape -- the distinction the model is most
    # likely to collapse, because this talk is task-relevant.
    "meta": lambda s, nw: bool(re.search(
        r"(?i)\b(?:freeze|frozen|lag\w*|glitch|refresh|reload|disconnect|"
        r"internet|wifi|screen|click\w*|button|timer|round|trial|bonus|cents?|"
        r"pay|prolific|survey|director|matcher|partner|score|points?|correct|"
        r"wrong|my turn|your turn)\b", s)),
}


def squish(t):
    return re.sub(r"\s+", " ", str(t)).strip()


def is_true(s):
    return s.astype(str).str.upper().isin(["TRUE", "T", "1"])


def read_chats(pattern):
    """Pool chats.csv files, DEDUPED.

    The run folders are cumulative re-exports, not disjoint waves: pooling
    pilot_v1 naively gives 2,812 rows for 1,932 real messages. Every duplicate
    is a message the classifier scores twice and the evaluation counts twice.
    """
    files = sorted(glob.glob(pattern))
    if not files:
        sys.exit(f"No chats.csv matched {pattern}")
    df = pd.concat([pd.read_csv(f, dtype=str, engine="python") for f in files],
                   ignore_index=True)
    n_raw = len(df)
    df = df.drop_duplicates(subset=["roundID", "playerID", "text"]).reset_index(drop=True)
    print(f"  {len(files)} file(s): {n_raw:,} rows -> {len(df):,} after dedup")
    return df


def build_contexts(chats):
    """roundID -> [(who, text, source_index), ...] in chronological order.

    Source row order IS chronological: 00_preprocessing.R unnests Empirica's
    chat array, which is append-ordered. It drops `chatTimestamps`, so there is
    no explicit key to sort on -- worth restoring, but the order is correct.

    Built from the FULL chat, matcher turns included. Judging "no hole" without
    the matcher's preceding question is a different and much harder question
    than the one a human annotator faces.
    """
    ctx = {}
    for rid, grp in chats.groupby("roundID", sort=False):
        ctx[rid] = [("DIRECTOR" if d else "MATCHER", squish(t), i)
                    for i, (t, d) in enumerate(zip(grp["text"], is_true(grp["director_msg"])))]
    return ctx


def render(entries, target_pos):
    """One round on one line, target wrapped in >>> <<<. Single-line because a
    CSV cell with newlines in it is unreadable in Excel, which is where this
    gets filled in."""
    out = []
    for k, (who, msg, _) in enumerate(entries):
        body = f">>> {msg} <<<" if k == target_pos else msg
        out.append(f"{who[0]}: {body}")
    return "  |  ".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", default="pilot_v1",
                    help="subfolder of data/processed_data/exp_2 to sample from")
    ap.add_argument("--n-random", type=int, default=300, help="size of sheet A")
    ap.add_argument("--n-boundary", type=int, default=100, help="size of sheet B")
    ap.add_argument("--seed", type=int, default=20260908)
    ap.add_argument("--out", default=os.path.join(
        REPO, "data/processed_data/exp_2/annotation/dev_sample.csv"))
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing sheet. Refuses by default: this "
                         "file is where hand labels live, and Exp 1's labels "
                         "were nearly lost exactly this way.")
    args = ap.parse_args()

    if os.path.exists(args.out) and not args.force:
        existing = pd.read_csv(args.out, dtype=str)
        n_lab = existing["is_description"].notna().sum() if "is_description" in existing else 0
        sys.exit(f"{args.out} already exists ({len(existing):,} rows, {n_lab:,} labelled).\n"
                 f"Regenerating would discard those labels. Pass --force if that "
                 f"is genuinely what you want.")

    chats = read_chats(os.path.join(
        REPO, "data/processed_data/exp_2", args.runs, "*", "chats.csv"))
    ctx = build_contexts(chats)

    d = chats[is_true(chats["director_msg"])].copy()
    d["sq"] = d["text"].map(squish)
    d["nw"] = d["sq"].str.split().str.len().fillna(0).astype(int)
    d = d[d["sq"].str.len() > 0].reset_index(drop=True)
    print(f"  {len(d):,} director messages across {d['roundID'].nunique():,} rounds, "
          f"{d['gameID'].nunique()} games")

    for name, fn in BOUNDARY.items():
        d[f"is_{name}"] = [fn(s, n) for s, n in zip(d["sq"], d["nw"])]
        print(f"    boundary/{name}: {int(d[f'is_{name}'].sum()):,}")

    # Sheet A: uniform. This is the only sheet whose base rate means anything.
    a = d.sample(min(args.n_random, len(d)), random_state=args.seed)
    a = a.assign(sheet="A", stratum="random")

    # Sheet B: every negation and meta case (they are rare and each one is
    # informative), topped up with short messages, none of them already in A.
    rest = d.drop(index=a.index)
    rare = rest[rest["is_negation"] | rest["is_meta"]]
    short = rest[rest["is_short"] & ~rest.index.isin(rare.index)]
    top_up = short.sample(max(0, min(args.n_boundary - len(rare), len(short))),
                          random_state=args.seed)
    b = pd.concat([rare, top_up])
    b = b.assign(sheet="B", stratum=[
        "negation" if n else "meta" if m else "short"
        for n, m in zip(b["is_negation"], b["is_meta"])])

    rows = []
    for i, (_, r) in enumerate(pd.concat([a, b]).iterrows()):
        entries = ctx.get(r["roundID"], [])
        pos = next((k for k, (_, m, _) in enumerate(entries) if m == r["sq"]), None)
        rows.append({
            "row_id": f"{r['sheet']}{i:04d}",
            "sheet": r["sheet"],
            "stratum": r["stratum"],
            "gameID": r["gameID"],
            "roundID": r["roundID"],
            "trialNum": r.get("trialNum", ""),
            "text": r["sq"],
            "round_context": render(entries, pos),
            "is_description": "",
            "note": "",
        })

    out = pd.DataFrame(rows)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    out.to_csv(args.out, index=False)
    print(f"\n  wrote {len(out):,} rows to {os.path.relpath(args.out, REPO)}")
    print(f"    sheet A (random, scoreable):  {int((out['sheet'] == 'A').sum()):,}")
    print(f"    sheet B (boundary, diagnostic only): {int((out['sheet'] == 'B').sum()):,}")
    print(out[out["sheet"] == "B"]["stratum"].value_counts().to_string())
    print("\n  Fill in `is_description` (1 = keep, 0 = drop). Blanks are dropped, "
          "not guessed.")
    print("  COMMIT THE FILLED FILE. These labels are not regenerable.")


if __name__ == "__main__":
    main()
