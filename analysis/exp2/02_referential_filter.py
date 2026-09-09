#!/usr/bin/env python3
"""SCREEN Exp 2 director messages for ones that do not describe the target shape,
and nominate them for human review.

THE MODEL DOES NOT DECIDE ANYTHING. It writes `referential_scores.parquet` and a
`review_queue.csv`; a person rules on every nominated message; `02c_apply_review.py`
turns those rulings into `referential_flags.parquet`, which is the only file
03_build_corpus.py reads. Until someone has signed off, that file does not exist
and 03 keeps every message. No code path here deletes a description unreviewed.

That inverts what to optimise. A false positive costs five seconds of reading; a
false negative is never seen again. So tune for RECALL at a tolerable review
burden, set `referential.review_threshold` LOW, and read the burden table that
--validate prints.

WHAT IT IS MEASURED AGAINST
---------------------------
`data/processed_data/exp_2/annotation/dev_labels.csv` -- 400 director messages
from the pilot, hand-labelled by Jess in September 2026. NOT Exp 1's `chit_chat`
column: those labels miss ~32% of even the most obvious filler, their errors run
almost entirely one way, and Exp 2 is no longer being compared to Exp 1.

Two sheets, and they are not interchangeable:
  sheet A  300 uniform random  -> the only source of a rate you may report
  sheet B  100 over-sampled hard cases -> diagnostic only, base rate fabricated

WHAT THE MODEL ACTUALLY HAS TO DO
---------------------------------
Measured on those labels: the corpus is 3.05% filler [1.86, 4.25], and the
one-line rule below catches the obvious half of it with 11/13 agreement. So the
model's real job is the residue, which is almost entirely ON-TASK talk:

    "press it"          "you have to click it"    "had to click 3 times"
    "as the director"   "it says i'm the director"  "not the same number"
    "i cant wait tbh"   "anyway..."               "Got it /"

It is NOT greetings (the rule has those), NOT negation (`no boat`, `no white
gaps` are descriptions), and NOT short messages (`bat`, `Boxing glove`, `the
claw` are the conventionalised labels this study exists to measure).

WHY THE SCREEN-THEN-REVIEW SHAPE IS RIGHT HERE
----------------------------------------------
Filler is sparse -- ~3% of director messages, ~260 of them at the planned 180
games. That is few enough for a person to adjudicate but far too many to find by
reading 8,600 messages. So the model reads all 8,600 and hands back a few
hundred; the researcher rules on those. An earlier Qwen2.5-7B run flagged 36-49%
of messages, which as an autonomous classifier would have deleted 600-1,700 real
descriptions -- as a screen it would merely have been unusable, which is the
failure mode you want.

Usage:
    python 02_referential_filter.py --validate     # burden vs recall on dev_labels
    python 02_referential_filter.py --self-test    # 11 boundary cases, no data
    python 02_referential_filter.py --debug-tokens # what the model wants to say
    python 02_referential_filter.py                # screen Exp 2 -> review_queue.csv
"""

import argparse
import csv
import glob
import math
import os
import re
import sys

import numpy as np
import pandas as pd
import yaml

csv.field_size_limit(10 ** 9)

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
FEWSHOT_FILE = os.path.join(HERE, "fewshot_examples.csv")
DEV_LABELS = os.path.join(REPO, "data/processed_data/exp_2/annotation/dev_labels.csv")

# ---------------------------------------------------------------------------
# The rule layer. Deliberately tiny, and validated: on the 400 hand labels it
# fires 13 times and agrees with Jess 11 times. Both disagreements are a bare
# "yes"/"no" answering a matcher's question about the shape -- and her own
# labels split 7:2 on that exact case, so it is a coin flip either way. Making
# it a RULE removes the coin flip rather than handing it to the model.
#
# SINGLE LETTERS ARE NOT FILLER. Tangrams get named for the letter they
# resemble ("M", "W", "E", "L", "K"), so a pattern matching a lone letter
# silently deletes a convention. A bare "k" for "ok" was doing exactly that.
# ---------------------------------------------------------------------------
PURE_FILLER = re.compile(
    r"^(?:"
    r"h(?:i+|ey+|ello+|iya)|yo|sup|"
    r"ok(?:ay)?|kk|alright|aight|"   # NOT bare "k": single letters name shapes
    r"y(?:es+|ea+h?|ep|up)|n(?:o+|ope|ah)|mhm+|"
    r"got\s?it|gotcha|understood|makes sense|"
    r"thank(?:s| you)?|ty|tysm|np|no problem|you'?re welcome|"
    r"gg|good game|good luck|gl|hf|nice|great|cool|awesome|perfect|"
    r"lol|lmao|haha+|hehe+|:\)|:\(|:d|<3|"
    r"wow|oh|ah+|hm+|huh|oops|oof|dang|damn|darn|"
    r"sorry|my bad|"
    r"bye+|goodbye|see ya|cya|later|good bye|"
    r"ready|done|next|go|start|wait|hold on|one sec|brb|"
    r"[?!.…,~\-\s]+"
    r")$",
    re.IGNORECASE,
)

# The Exp 1 prompt spent its longest, most emphatic section on screen-position
# confusion ("for me it's top right"). That occurs TWICE in 1,699 Exp 2 director
# messages, and Jess kept one of them. Emphatic instructions about an absent
# category push a model to find it anyway, so the section is gone. What replaced
# it is the boundary that actually exists here: on-task talk vs. shape talk.
PROMPT = """Two people are playing a game. One of them (the DIRECTOR) can see \
an abstract black shape and has to describe it so their partner can pick that \
shape out of four on screen. Over repeated rounds they invent short nicknames \
for the shapes.

Your job: decide whether one message says anything about what the SHAPE looks like.

YES - it describes the shape or any part of it: the parts, how they are \
arranged, which way it faces, or what it resembles. This includes
  - very short nicknames: "bat", "backwords E", "the claw", "Big W"
  - fragments continuing an earlier description: "on a ledge", "with round body"
  - what the shape does NOT have: "no boat", "no white gaps", "not touching"
  - corrections and typo fixes of an earlier description: "top*"

NO - it says nothing about the shape. Most of these are still ON TASK, which is \
what makes them easy to get wrong:
  - clicking and the interface: "press it", "you have to click it", "it froze"
  - whose turn it is: "as the director", "it says i'm the matcher now"
  - how the last round went: "that one was way off", "not the same number"
  - greetings, thanks, reactions and small talk: "hi", "anyway...", "gg"

If a message does both - a description with a remark attached - answer YES."""


def squish(t):
    return re.sub(r"\s+", " ", str(t)).strip()


def truthy(s):
    return s.astype(str).str.strip().str.upper().isin(["TRUE", "T", "1", "1.0", "YES"])


def load_config(path):
    with open(path) as f:
        return yaml.safe_load(f)


def read_chats(pattern):
    """Pool chats.csv files, DEDUPED.

    The run folders are cumulative re-exports, not disjoint waves. Pooling
    pilot_v1 naively gives 2,812 rows for 1,932 real messages -- 45% duplicates,
    every one of them scored twice and counted twice in any evaluation.
    """
    files = sorted(glob.glob(pattern))
    if not files:
        sys.exit(f"No chats.csv matched {pattern}")
    df = pd.concat([pd.read_csv(f, dtype=str, engine="python") for f in files],
                   ignore_index=True)
    n_raw = len(df)
    df = df.drop_duplicates(subset=["roundID", "playerID", "text"]).reset_index(drop=True)
    print(f"  {len(files)} file(s): {n_raw:,} rows -> {len(df):,} deduped")
    return df


def load_shots():
    """The curated examples, ALL of them, interleaved YES/NO.

    Hand-written rather than sampled from the labelled data, so nothing here
    leaks into the evaluation set. Read straight from the file they come out
    grouped -- every YES then every NO -- and a block of trailing NOs biases a
    few-shot model toward the trailing label, which is the exact direction this
    classifier kept failing in.
    """
    if not os.path.exists(FEWSHOT_FILE):
        print("  WARNING: fewshot_examples.csv missing -- much weaker without it")
        return []
    pool = pd.read_csv(FEWSHOT_FILE)
    pairs = list(zip(pool["text"].astype(str), pool["label"].astype(str)))
    yes = [x for x in pairs if x[1] == "REFERENTIAL"]
    no = [x for x in pairs if x[1] != "REFERENTIAL"]
    out = []
    for i in range(max(len(yes), len(no))):
        if i < len(yes):
            out.append(yes[i])
        if i < len(no):
            out.append(no[i])
    return out


def build_prompt(shots, entries, target_pos):
    """One message to judge, shown inside its round transcript.

    CONTEXT IS THE POINT. Judged alone, "no" could be anything and "left side"
    looks like screen talk. Inside the round, both are decidable -- and the
    round transcript is exactly what the human annotator had in front of her.
    """
    lines = [PROMPT, ""]
    if shots:
        lines.append("Examples:")
        lines += [f'  "{t}" -> {"YES" if lab == "REFERENTIAL" else "NO"}' for t, lab in shots]
        lines.append("")
    lines.append("Here is the full chat for one round. The two players are "
                 "trying to agree on ONE target shape:")
    for k, (who, msg) in enumerate(entries):
        lines.append(f'{"  >>> " if k == target_pos else "      "}{who}: {msg}')
    lines.append("")
    lines.append("Does the message marked >>> say anything about what the shape "
                 "looks like? Answer YES or NO.")
    return "\n".join(lines)


def build_contexts(chats):
    """roundID -> [(who, text), ...] in chronological order, matcher included.

    Source row order IS chronological: 00_preprocessing.R unnests Empirica's
    append-ordered chat array. It drops `chatTimestamps` before writing, so
    there is no explicit sort key -- worth restoring, but the order is right.
    """
    out = {}
    for rid, grp in chats.groupby("roundID", sort=False):
        out[rid] = [("DIRECTOR" if d else "MATCHER", squish(t))
                    for t, d in zip(grp["text"], truthy(grp["director_msg"]))]
    return out


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def check_vram(model_id, vram_gb, n_gpu):
    """Refuse to run if the weights do not fit on the visible GPUs.

    THIS IS NOT A NICETY. `device_map="auto"` does not raise when a model is too
    big -- it fills the GPUs, then silently spills the rest to CPU RAM, and the
    job runs orders of magnitude slower while looking like it is working. A
    Qwen3-32B self-test on 2 x RTX A5000 (48 GB against ~66 GB of weights) spent
    six minutes loading and would have taken hours to score eleven prompts.

    The size estimate is deliberately crude -- parameter count parsed out of the
    model name, 2 bytes each for bf16, +15% for activations and the KV cache.
    Qwen names are regular ("Qwen3-32B", "Qwen3-14B"), and a rough number that
    fires early beats an exact one that arrives after the weights have loaded.
    """
    m = re.search(r"[-/](\d+(?:\.\d+)?)B", model_id)
    if not m:
        print("  (could not read a parameter count from the model name -- "
              "skipping the VRAM check)")
        return
    params = float(m.group(1))
    need = params * 2 * 1.15
    print(f"  {params:g}B params in bf16 needs ~{need:.0f} GB; {vram_gb:.0f} GB visible")
    if need <= vram_gb:
        return
    per_card = vram_gb / max(1, n_gpu)
    cards = math.ceil(need / per_card)
    smaller = [x for x in (32, 14, 8, 4) if x * 2 * 1.15 <= vram_gb]
    fit = f"Qwen/Qwen3-{smaller[0]}B" if smaller else "a smaller model"
    sys.exit(
        f"\n  STOP: {model_id} needs ~{need:.0f} GB and only {vram_gb:.0f} GB is visible.\n\n"
        f"  device_map=\"auto\" does NOT error here -- it offloads the remainder to\n"
        f"  CPU RAM and runs for hours while looking like it is working.\n\n"
        f"  Two ways forward:\n"
        f"    1. more cards: -g {cards} at {per_card:.0f} GB each (or request larger ones)\n"
        f"    2. smaller model: set referential.model in config.yaml to {fit}\n\n"
        f"  For a binary judgement scored off two logits, (2) is worth trying first --\n"
        f"  --validate answers whether it is enough in a single job.\n")


def score(prompts, cfg, batch_size=16):
    """P(FILLER) for each prompt. One forward pass, two logits compared.

    SCORE, DON'T GENERATE. Asking the model to emit labels and parsing them
    dropped items silently (20 batches returned fewer labels than inputs),
    let the model drift across a list, and discarded its confidence. A single
    forward pass whose last-position logits are compared for YES vs NO is
    deterministic, cannot drop an item, needs no parsing, and yields a
    probability the threshold can move over without re-running anything.
    """
    from transformers import AutoModelForCausalLM, AutoTokenizer
    import torch

    model_id = cfg["referential"]["model"]
    print(f"  loading {model_id} ...")
    tok = AutoTokenizer.from_pretrained(model_id)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    tok.padding_side = "left"      # last-position logits must be the true last token
    # Truncate from the LEFT. The question and the >>> marker are at the END of
    # the prompt; right-truncation silently cuts them off and scores YES/NO on a
    # prompt with no question in it. If anything must go, drop the examples.
    tok.truncation_side = "left"

    dtype = torch.float32
    if torch.cuda.is_available():
        major, _ = torch.cuda.get_device_capability()
        dtype = torch.bfloat16 if major >= 8 else torch.float16
        n_gpu = torch.cuda.device_count()
        vram = sum(torch.cuda.get_device_properties(i).total_memory
                   for i in range(n_gpu)) / 1e9
        print(f"  {n_gpu} x {torch.cuda.get_device_name(0)} = {vram:.0f} GB -> {dtype}")
        check_vram(model_id, vram, n_gpu)
    else:
        print("  no CUDA -> float32 on CPU (slow)")
    try:
        model = AutoModelForCausalLM.from_pretrained(model_id, dtype=dtype, device_map="auto")
    except TypeError:
        model = AutoModelForCausalLM.from_pretrained(model_id, torch_dtype=dtype, device_map="auto")
    model.eval()

    # YES / NO are SINGLE tokens of comparable frequency. The previous pair was
    # not: "REFERENTIAL" tokenises to ['REFER','ENTIAL'] and "FILLER" to
    # ['F','ILL','ER'], so the comparison was P('REFER') vs P('F') -- and 'F' is
    # far likelier a priori, biasing every decision toward FILLER.
    def one(*words):
        for w in words:
            ids = tok.encode(w, add_special_tokens=False)
            if len(ids) == 1:
                return ids[0]
        return tok.encode(words[0], add_special_tokens=False)[0]
    t_ref, t_fil = one("YES", "Yes", "yes"), one("NO", "No", "no")
    if t_ref == t_fil:
        sys.exit("YES/NO share a first token for this tokenizer")
    print(f"  answer tokens: YES={t_ref} NO={t_fil}")

    def wrap(text):
        """Instruction-tuned models must see their chat template, and hybrid
        reasoning models must have thinking DISABLED. Qwen3's default template
        ends at "<|im_start|>assistant\\n", so the next token is "<think>" --
        and this scores the next token for YES vs NO. Comparing two tokens the
        model has no intention of emitting is a flat, meaningless signal:
        Qwen3-32B returned P(filler) < 0.02 for every self-test case, filler
        included. enable_thinking=False emits an empty <think></think> block so
        the very next token is the answer."""
        msgs = [{"role": "user", "content": text}]
        for kw in ({"enable_thinking": False}, {}):
            try:
                return tok.apply_chat_template(msgs, tokenize=False,
                                               add_generation_prompt=True, **kw)
            except TypeError:
                continue
            except Exception:
                break
        return text + "\nAnswer:"

    wrapped = [wrap(p) for p in prompts]
    probs, start = [], 0
    while start < len(wrapped):
        chunk = wrapped[start:start + batch_size]
        enc = tok(chunk, return_tensors="pt", padding=True, truncation=True,
                  max_length=4096, add_special_tokens=False).to(model.device)
        try:
            with torch.no_grad():
                # Ask for ONE position's logits. A causal LM returns
                # [batch, seq, vocab] by default -- at batch 32, ~950 tokens and
                # Qwen's 152k vocab that is 9.3 GB in bf16, which OOMed a 50 GB
                # card, and every position but the last is discarded here.
                try:
                    out = model(**enc, logits_to_keep=1)
                except TypeError:
                    out = model(**enc)
                logits = out.logits[:, -1, :]
        except torch.cuda.OutOfMemoryError:
            if batch_size <= 1:
                raise
            batch_size = max(1, batch_size // 2)
            print(f"\n  CUDA OOM -- batch -> {batch_size}, retrying")
            torch.cuda.empty_cache()
            continue
        pair = torch.stack([logits[:, t_fil], logits[:, t_ref]], dim=-1)
        probs += torch.softmax(pair.float(), dim=-1)[:, 0].tolist()
        print(f"    {len(probs):,}/{len(wrapped):,}", end="\r")
        start += batch_size
    print()
    return np.array(probs)


def classify(targets, context_df, cfg, use_llm=True, batch_size=16):
    """Add `p_filler`, `chit_chat` and `method` to the messages in `targets`.

    `context_df` is the FULL chat -- matcher turns included, unfiltered. Building
    transcripts from `targets` instead shows the model a round with the other
    side missing, which was a real bug in the previous version.
    """
    df = targets.copy()
    df["sq"] = df["text"].map(squish)
    df["_rule"] = df["sq"].map(lambda t: True if not t else bool(PURE_FILLER.match(t)))
    n_rule = int(df["_rule"].sum())
    print(f"  {len(df):,} messages; rule flagged {n_rule:,} as filler "
          f"({100 * n_rule / max(1, len(df)):.1f}%)")

    df["p_filler"] = np.where(df["_rule"], 1.0, 0.0)
    need = df[~df["_rule"]]
    if use_llm and len(need):
        shots = load_shots()
        ctx = build_contexts(context_df)
        print(f"  {len(need):,} to the model ({len(shots)} few-shot examples)")
        prompts = []
        for _, r in need.iterrows():
            entries = ctx.get(r["roundID"], [(("DIRECTOR"), r["sq"])])
            pos = next((k for k, (_, m) in enumerate(entries) if m == r["sq"]), 0)
            prompts.append(build_prompt(shots, entries, pos))
        df.loc[need.index, "p_filler"] = score(prompts, cfg, batch_size)
    elif len(need):
        print(f"  {len(need):,} undecided -> REFERENTIAL (--no-llm)")

    # NOMINATION threshold, not a decision threshold. Every flagged message is
    # read by a person, so a false positive costs five seconds and a false
    # negative is the only silent error. Set it LOW -- lower than you would for
    # an autonomous classifier -- and let --validate's burden table tell you how
    # low. Rule hits are flagged too: they are ~3% of the corpus and including
    # them makes the audit trail complete rather than partly automatic.
    thr = float(cfg["referential"].get("review_threshold", 0.2))
    df["flagged"] = df["_rule"] | (df["p_filler"] > thr)
    df["method"] = np.where(df["_rule"], "rule", "llm")
    p = df.loc[~df["_rule"], "p_filler"]
    if len(p):
        print(f"  model P(filler): mean {p.mean():.3f}; {int((p > thr).sum()):,} "
              f"over the review threshold {thr}")
        if (p > thr).mean() > 0.35:
            print(f"  WARNING: the model nominated {100 * (p > thr).mean():.0f}% of "
                  f"undecided messages. The hand-labelled rate is ~3%. Much past "
                  f"a third is a broken scoring path rather than a cautious "
                  f"screen -- run --debug-tokens before reading the queue.")
    return df.drop(columns=["_rule", "sq"])


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def wilson(k, n, z=1.96):
    if not n:
        return 0.0, 0.0
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return 100 * max(0.0, c - h), 100 * min(1.0, c + h)


def prf(pred, gold, label):
    tp = int((pred & gold).sum()); fp = int((pred & ~gold).sum())
    fn = int((~pred & gold).sum()); tn = int((~pred & ~gold).sum())
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    print(f"\n  {label}")
    print(f"    n={tp + fp + fn + tn:,}  gold filler={tp + fn:,} "
          f"({100 * (tp + fn) / max(1, tp + fp + fn + tn):.1f}%)")
    print(f"    RECALL on filler  {r:.3f}   ({tp}/{tp + fn} found)")
    print(f"    precision         {p:.3f}   ({fp} real descriptions wrongly dropped)")
    print(f"    tp={tp} fp={fp} fn={fn} tn={tn}")
    return {"precision": round(p, 4), "recall": round(r, 4),
            "tp": tp, "fp": fp, "fn": fn, "tn": tn}


def validate(cfg, use_llm, batch_size, show):
    if not os.path.exists(DEV_LABELS):
        sys.exit(f"No hand labels at {DEV_LABELS}.\n"
                 f"Run 02a_make_dev_sample.py, label it, then 02b_merge_labels.py.")
    gold = pd.read_csv(DEV_LABELS, dtype=str)
    gold = gold[gold["is_description"].notna()].copy()
    gold["gold_filler"] = ~truthy(gold["is_description"])
    print(f"validating on {len(gold):,} hand-labelled messages "
          f"({int(gold['gold_filler'].sum())} filler)")

    chats = read_chats(os.path.join(
        REPO, "data/processed_data/exp_2/pilot_v1", "*", "chats.csv"))
    d = chats[truthy(chats["director_msg"])].copy()
    d["sq"] = d["text"].map(squish)
    key = gold.set_index(gold["roundID"] + "|" + gold["text"].map(squish))["gold_filler"]
    d["_k"] = d["roundID"] + "|" + d["sq"]
    test = d[d["_k"].isin(key.index)].copy()
    print(f"  matched {len(test):,} of {len(gold):,} labelled messages in the corpus")

    res = classify(test, chats, cfg, use_llm=use_llm, batch_size=batch_size)
    res["gold"] = res["_k"].map(key).astype(bool)
    res["sheet"] = res["_k"].map(gold.set_index(gold["roundID"] + "|" +
                                                gold["text"].map(squish))["sheet"])

    a = res[res["sheet"] == "A"]
    prf(a["flagged"].astype(bool), a["gold"], "SHEET A (random -- the reportable numbers)")
    b = res[res["sheet"] == "B"]
    if len(b):
        prf(b["flagged"].astype(bool), b["gold"], "SHEET B (hard cases -- diagnostic only)")

    # BY LENGTH. This is the check that caught the previous failure: a 3B model
    # scored a respectable aggregate while wrongly dropping 18% of ONE-WORD
    # descriptions, and a 7B model 35%. Short and contrastive is what a
    # conventionalised reference LOOKS like by block 4, so an aggregate can look
    # fine while the classifier deletes exactly the signal being measured.
    res["nw"] = res["text"].map(lambda t: len(squish(t).split()))
    print("\n  REAL DESCRIPTIONS NOMINATED, by message length (extra reading, not loss)")
    print(f"    {'words':>8s} {'n':>6s} {'dropped':>8s} {'rate':>7s}")
    for lo, hi, lab in [(1, 1, "1"), (2, 2, "2"), (3, 4, "3-4"), (5, 8, "5-8"), (9, 999, "9+")]:
        g = res[(~res["gold"]) & (res["nw"] >= lo) & (res["nw"] <= hi)]
        if len(g):
            print(f"    {lab:>8s} {len(g):6d} {int(g['flagged'].sum()):8d} "
                  f"{100 * g['flagged'].mean():6.1f}%")

    # THE TABLE THIS DESIGN TURNS ON. The model nominates; a person decides. So
    # the question is not "is it accurate" but "how much do I have to read to
    # catch nearly all the filler". Recall is the only column that can hurt you:
    # a missed message is never seen again, while an over-nomination costs a few
    # seconds. Pick the threshold from here and put it in config.yaml as
    # referential.review_threshold.
    if use_llm:
        n_full = len(a)
        print("\n  REVIEW BURDEN vs RECALL (sheet A, and projected to 8,600 msgs "
              "at 180 games)")
        print(f"    {'thr':>5s} {'nominated':>10s} {'% corpus':>9s} "
              f"{'filler found':>13s} {'recall':>7s} {'to read @180g':>14s}")
        for t in [0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 0.9]:
            pr = a["flagged"] & ((a["p_filler"] > t) | (a["method"] == "rule"))
            tp = int((pr & a["gold"]).sum())
            fn = int((~pr & a["gold"]).sum())
            r = tp / (tp + fn) if tp + fn else 0.0
            share = pr.mean()
            print(f"    {t:5.2f} {int(pr.sum()):10d} {100 * share:8.1f}% "
                  f"{tp:8d}/{tp + fn:<4d} {r:7.3f} {round(8600 * share):14,d}")
        missed = a[(~a["flagged"]) & a["gold"]]
        if len(missed):
            print(f"\n    MISSED at the configured threshold ({len(missed)}) -- "
                  f"these are the only silent errors:")
            for _, r in missed.iterrows():
                print(f"      p={r['p_filler']:.2f}  {squish(r['text'])[:64]!r}")

    print(f"\n  DISAGREEMENTS (up to {show})")
    dis = res[res["flagged"].astype(bool) != res["gold"]]
    for _, r in dis.head(show).iterrows():
        kind = "over-nominated" if not r["gold"] else "MISSED filler"
        print(f"    [{r['sheet']}] p={r['p_filler']:.2f} {kind:16s} {squish(r['text'])[:64]!r}")
    if len(dis) > show:
        print(f"    ... and {len(dis) - show} more (--show N)")

    print("\n  The model nominates, you decide. RECALL is the number that matters:"
          "\n  an over-nomination costs seconds of reading, a miss is never seen again.")


SELF_TEST = [
    # Held out from fewshot_examples.csv on purpose -- reusing curated examples
    # tests whether the model can echo its prompt, not whether it can judge.
    ("hey there", True), ("you got it", True), ("mine is frozen", True),
    ("how much are we getting paid for this", True), ("press it", True),
    ("3 hooks", False), ("half circle on top", False), ("K", False),
    ("no diamond", False), ("not the one with the hat", False),
    ("with two feet", False),
]


def self_test(cfg, batch_size):
    shots = load_shots()
    prompts = [build_prompt(shots, [("DIRECTOR", t)], 0) for t, _ in SELF_TEST]
    p = score(prompts, cfg, batch_size)
    ok = 0
    for (t, want), pf in zip(SELF_TEST, p):
        got = pf > 0.5
        ok += got == want
        print(f"    {'OK ' if got == want else 'MISS'}  p={pf:.3f}  "
              f"want={'FILLER' if want else 'REF':6s}  {t!r}")
    print(f"  {ok}/{len(SELF_TEST)} correct")
    if p.max() < 0.5 or p.min() > 0.5:
        print("  WARNING: every case scored the same side. Run --debug-tokens; "
              "a flat signal means the model is not trying to emit YES or NO.")


def debug_tokens(cfg, k=8):
    """What does the model ACTUALLY want to say? Logit scoring is only valid if
    the model intends to emit one of the two candidates; if it wants "Yes" or
    "**" or "<think>" instead, the YES/NO ratio is noise that looks like data."""
    from transformers import AutoModelForCausalLM, AutoTokenizer
    import torch
    mid = cfg["referential"]["model"]
    tok = AutoTokenizer.from_pretrained(mid)
    try:
        model = AutoModelForCausalLM.from_pretrained(mid, dtype=torch.bfloat16, device_map="auto")
    except TypeError:
        model = AutoModelForCausalLM.from_pretrained(mid, torch_dtype=torch.bfloat16, device_map="auto")
    model.eval()
    shots = load_shots()
    for t, want in SELF_TEST[:6]:
        msgs = [{"role": "user", "content": build_prompt(shots, [("DIRECTOR", t)], 0)}]
        try:
            s = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True,
                                        enable_thinking=False)
        except TypeError:
            s = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
        enc = tok(s, return_tensors="pt", add_special_tokens=False).to(model.device)
        with torch.no_grad():
            lg = model(**enc).logits[0, -1, :]
        top = torch.topk(torch.softmax(lg.float(), -1), k)
        print(f"  {t!r} (want {'FILLER' if want else 'REFERENTIAL'})")
        print("     " + "  ".join(f"{tok.decode([i])!r}:{v:.2f}"
                                  for v, i in zip(top.values.tolist(), top.indices.tolist())))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=os.path.join(HERE, "config.yaml"))
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--no-llm", action="store_true", help="rule layer only")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--debug-tokens", action="store_true")
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--show", type=int, default=30, help="disagreements to print")
    args = ap.parse_args()
    cfg = load_config(args.config)

    if args.debug_tokens:
        return debug_tokens(cfg)
    if args.self_test:
        return self_test(cfg, args.batch_size)
    if args.validate:
        return validate(cfg, not args.no_llm, args.batch_size, args.show)

    chats = read_chats(os.path.join(REPO, cfg["paths"]["processed"], "*", "*", "chats.csv"))
    targets = chats[truthy(chats["director_msg"])].copy()
    print(f"screening {len(targets):,} director messages of {len(chats):,}")
    res = classify(targets, chats, cfg, use_llm=not args.no_llm, batch_size=args.batch_size)

    out = os.path.join(REPO, cfg["paths"]["out"])
    os.makedirs(out, exist_ok=True)

    # Scores, not decisions. THE MODEL DOES NOT DECIDE ANYTHING HERE -- it
    # nominates messages for a human to rule on, and `02c_apply_review.py`
    # turns the human's calls into `referential_flags.parquet`, which is the
    # only file 03_build_corpus.py reads. Until a person has signed off, that
    # file does not exist and 03 keeps every message. There is no code path in
    # which a model deletes a description unreviewed.
    spath = os.path.join(out, "referential_scores.parquet")
    keep = [c for c in ["gameID", "roundID", "playerID", "text", "director_msg",
                        "p_filler", "flagged", "method"] if c in res.columns]
    res[keep].to_parquet(spath, index=False)

    # The review queue, in the same shape as the hand-labelling sheet: one row
    # per nominated message, its round on one line with the message marked.
    q = res[res["flagged"]].copy()
    ctx = build_contexts(chats)
    rows = []
    for i, (_, r) in enumerate(q.sort_values("p_filler", ascending=False).iterrows()):
        entries = ctx.get(r["roundID"], [("DIRECTOR", squish(r["text"]))])
        pos = next((k for k, (_, m) in enumerate(entries) if m == squish(r["text"])), 0)
        rows.append({
            "row_id": f"R{i:05d}",
            "gameID": r["gameID"], "roundID": r["roundID"], "playerID": r["playerID"],
            "method": r["method"], "p_filler": round(float(r["p_filler"]), 3),
            "text": squish(r["text"]),
            "round_context": "  |  ".join(
                f'{w[0]}: {">>> " + m + " <<<" if k == pos else m}'
                for k, (w, m) in enumerate(entries)),
            "is_filler": "", "note": "",
        })
    qpath = os.path.join(REPO, "data/processed_data/exp_2/annotation/review_queue.csv")
    os.makedirs(os.path.dirname(qpath), exist_ok=True)
    if os.path.exists(qpath):
        prev = pd.read_csv(qpath, dtype=str)
        n_done = int(prev["is_filler"].notna().sum()) if "is_filler" in prev else 0
        if n_done:
            qpath = qpath.replace(".csv", ".new.csv")
            print(f"\n  existing review_queue.csv has {n_done:,} decisions in it -- "
                  f"writing to {os.path.basename(qpath)} instead of overwriting")
    pd.DataFrame(rows).to_csv(qpath, index=False)

    n = len(q)
    print(f"\n  {n:,} of {len(res):,} messages nominated for review "
          f"({100 * n / max(1, len(res)):.1f}% of the corpus)")
    print(f"    by method: {q['method'].value_counts().to_dict()}")
    print(f"  wrote {os.path.relpath(spath, REPO)}  (scores)")
    print(f"  wrote {os.path.relpath(qpath, REPO)}  ({n:,} rows to review)")
    print("\n  Next: fill `is_filler` (1 = not a description, 0 = keep it), then")
    print("        python analysis/exp2/02c_apply_review.py")
    print("  03_build_corpus.py reads referential_flags.parquet, which that step")
    print("  writes. Until then it keeps every message.")


if __name__ == "__main__":
    main()
