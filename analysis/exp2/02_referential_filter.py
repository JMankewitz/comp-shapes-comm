#!/usr/bin/env python3
"""Flag each chat message as REFERENTIAL (about the target shape) or FILLER.

WHAT THIS REPLACES
------------------
Exp 1's `chit_chat` column was hand-coded: Jess read every message and flipped
the flag. 44,534 messages, 1,611 marked. That is not repeatable at Exp 2's scale,
and `analysis/exp1/00_preprocessing.R` hardcodes `chit_chat = FALSE`, so the
labels exist ONLY in the processed CSVs and re-running preprocessing destroys
them. Back those files up before touching that script.

THE OPERATIVE DISTINCTION (learned from the gold set, not invented here)
------------------------------------------------------------------------
Not "is this a greeting". The rule is: **does this message carry information
about the target shape's appearance?** Task-coordination and screen-position talk
count as FILLER even though they are on-task and not social. Examples Jess marked
as chit-chat:

    "for me its top right"          "alright now you're the matcher"
    "thats it"                      "did it freeze up for you too"
    "do you get it?"                "63 cents ain't bad"

That boundary is what an LLM gets wrong by default, which is why the few-shot
examples below are drawn from the gold labels at runtime rather than written by
hand.

WHAT THE GOLD SET CAN AND CANNOT VALIDATE
-----------------------------------------
Measured before building this (see --validate):

  * Restricted to DIRECTOR messages, coverage is good: of unambiguous filler,
    87% is labeled when it is the round's only message and 61% when it sits
    alongside other messages.
  * MATCHER messages are effectively unannotated -- 7,024 messages, 0.6% marked,
    and they are mostly "ok"/"?" acknowledgements that plainly are filler.

So: validate on director messages only, and read a residual disagreement rate of
10-15% as gold-set noise rather than classifier error. Chasing F1 past that point
is fitting the annotation's mistakes. Precision on the chit-chat class is the
number to watch; base rate is ~4%, so accuracy is meaningless (a classifier that
always says "referential" scores 96%).

Usage:
    # rules only, no model -- fast, and the sanity check for the pipeline
    python 02_referential_filter.py --validate --no-llm

    # validate the full classifier against Exp 1's hand labels
    python 02_referential_filter.py --validate

    # label Exp 2 (writes referential_flags.parquet)
    python 02_referential_filter.py
"""

import argparse
import csv
import glob
import json
import os
import random
import re
import sys

import pandas as pd
import yaml

csv.field_size_limit(10 ** 9)

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))

# ---------------------------------------------------------------------------
# Stage 1: rules
#
# Deliberately NARROW. These fire only on strings that cannot be referential
# under any reading, so a rule hit needs no model call and no review. Anything
# with shape content -- even one word like "arrow" -- must fall through to the
# LLM. Recall is not the job here; precision is.
# ---------------------------------------------------------------------------
PURE_FILLER = re.compile(
    r"^(?:"
    r"h(?:i+|ey+|ello+|iya)|yo|sup|"
    r"ok(?:ay)?|kk?|alright|aight|"
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

# Strong signals of task/meta talk rather than shape description. Used only to
# ROUTE to the model with a hint, never to decide on their own -- "it's the one
# on the left" is positional, but "left" also appears in real descriptions
# ("triangle on the left side").
META_HINT = re.compile(
    r"\b(freeze|frozen|frozen|lag(g|s|ging)?|glitch|refresh|reload|disconnect|"
    r"internet|wifi|screen|browser|click(ed|ing)?|button|timer|clock|round|trial|"
    r"bonus|cents?|pay|paid|prolific|study|survey|director|matcher|partner|"
    r"score|points?|correct|wrong|got that|missed)\b",
    re.IGNORECASE,
)

PROMPT_HEADER = """You are labelling messages from a two-player reference game. \
One player (the director) describes an abstract tangram shape so their partner \
can pick it out of four options on screen.

The messages you keep will be CONCATENATED into a single description of that \
shape, so keep everything that contributes to the description and drop \
everything that does not.

Label each message REFERENTIAL or FILLER.

REFERENTIAL — contributes to describing what the shape LOOKS LIKE: its parts, \
their arrangement within the shape, its orientation, or what it resembles.
  - Fragments count: "arrow up", "the pointy one", "not the fish".
  - FOLLOW-UP DETAIL COUNTS. A director often splits one description across \
    several messages, or adds to it after a pause: "it has a hole in the middle \
    too", "and the bottom is flat". These are part of the description.
  - Corrections to a description count: "no I meant the wider one".

FILLER — everything else, including talk that is on-task:
  - Greetings, sign-offs, thanks.
  - Bare agreement or disagreement with nothing added: "yes", "no", "ok", \
    "that's it", "got it", "nope try again".
  - Turn coordination: "your turn now", "you're the director".
  - Interface and study talk: freezing, lag, refreshing, timers, pay, bonus.

CRITICAL — screen position is FILLER. The four shapes appear in a DIFFERENT \
ORDER for each player, so "it's the top right one" or "for me that was bottom \
left" tells the partner nothing about the shape and is not a description. \
Position WITHIN the shape is REFERENTIAL: "triangle on the left side", \
"diamond at the bottom".

Answer with one word per line, in order: REFERENTIAL or FILLER."""


def load_config(path):
    with open(path) as f:
        return yaml.safe_load(f)


def squish(t):
    return re.sub(r"\s+", " ", str(t)).strip()


def rule_label(text):
    """Return True (filler), False (referential), or None (undecided)."""
    t = squish(text)
    if not t:
        return True
    if PURE_FILLER.match(t):
        return True
    return None


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def read_chats(folder_glob):
    frames = []
    for f in sorted(glob.glob(folder_glob)):
        try:
            frames.append(pd.read_csv(f, dtype=str, keep_default_na=False))
        except Exception as e:
            print(f"  WARNING: {f}: {e}", file=sys.stderr)
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True).drop_duplicates()
    df["text"] = df["text"].map(squish)
    return df[df["text"].str.len() > 0].reset_index(drop=True)


def is_true(s):
    return s.astype(str).str.strip().str.upper().isin(["TRUE", "T", "1"])


# ---------------------------------------------------------------------------
# Stage 2: LLM
# ---------------------------------------------------------------------------

def build_prompt(batch_texts, shots):
    lines = [PROMPT_HEADER, ""]
    if shots:
        lines.append("Examples:")
        for t, lab in shots:
            lines.append(f'  "{t}" -> {lab}')
        lines.append("")
    lines.append(f"Now label these {len(batch_texts)} messages:")
    for i, t in enumerate(batch_texts, 1):
        lines.append(f'{i}. "{t}"')
    return "\n".join(lines)


FEWSHOT_FILE = os.path.join(HERE, "fewshot_examples.csv")


def sample_shots(gold=None, n=16, seed=0):
    """Few-shot examples encoding Jess's boundary, not the prompt author's.

    Source order:
      1. A gold frame, when one is passed (validation runs have Exp 1 loaded).
      2. `fewshot_examples.csv` -- 240 balanced examples distilled from the Exp 1
         hand labels and COMMITTED alongside this script.

    (2) exists because the cluster sparse-checkout is `analysis/exp2` +
    `data/processed_data/exp_2`; Exp 1 is 219 MB and is not there. Without a
    committed pool, `sample_shots` silently returned [] on the cluster and the
    classifier ran with NO examples -- a materially weaker configuration than
    anything tested locally, and one that fails on inputs as easy as "hi".

    Biased toward SHORT messages: the boundary lives there, not in 15-word
    descriptions.
    """
    rng = random.Random(seed)
    pairs = []
    if gold is not None and len(gold):
        for lab, want in (("FILLER", True), ("REFERENTIAL", False)):
            pool = gold[gold["chit_chat_gold"] == want]
            pool = pool[pool["text"].str.len() <= 60]
            if len(pool):
                picks = rng.sample(list(pool["text"].unique()),
                                   min(n // 2, pool["text"].nunique()))
                pairs += [(t, lab) for t in picks]
    elif os.path.exists(FEWSHOT_FILE):
        pool = pd.read_csv(FEWSHOT_FILE)
        for lab in ("FILLER", "REFERENTIAL"):
            texts = pool.loc[pool["label"] == lab, "text"].dropna().tolist()
            picks = rng.sample(texts, min(n // 2, len(texts)))
            pairs += [(t, lab) for t in picks]
    if not pairs:
        print("  WARNING: no few-shot examples available. The classifier is much "
              "weaker without them -- check that fewshot_examples.csv shipped.")
    rng.shuffle(pairs)
    return pairs


def llm_label(texts, cfg, shots, batch_size=32):
    """Label texts with a local instruct model. Returns list of bools (True=filler)."""
    from transformers import AutoModelForCausalLM, AutoTokenizer
    import torch

    model_id = cfg["referential"]["model"]
    print(f"  loading {model_id} ...")
    tok = AutoTokenizer.from_pretrained(model_id)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    tok.padding_side = "left"
    # Pick the dtype from the ACTUAL card, not a hardcoded guess.
    #
    # bfloat16 requires Ampere (compute capability >= 8.0). The jag queue still
    # contains Volta cards (TITAN V, CC 7.0), where bf16 is unsupported and a
    # recent torch build may carry no kernels at all -- the job then dies during
    # generation, long after the weights have loaded and the GPU is committed.
    if torch.cuda.is_available():
        major, minor = torch.cuda.get_device_capability()
        name = torch.cuda.get_device_name(0)
        dtype = torch.bfloat16 if major >= 8 else torch.float16
        print(f"  GPU: {name} (CC {major}.{minor}) -> "
              f"{'bfloat16' if dtype is torch.bfloat16 else 'float16'}")
        if major < 8:
            print(f"  NOTE: pre-Ampere card. float16 works, but if torch was "
                  f"built without CC {major}.{minor} kernels this will fail at "
                  f"generation. Request a newer node if it does.")
    else:
        dtype = torch.float32
        print("  no CUDA visible -> float32 on CPU (slow)")

    # `torch_dtype` was renamed `dtype` in recent transformers; older releases
    # only accept the old name.
    try:
        model = AutoModelForCausalLM.from_pretrained(
            model_id, dtype=dtype, device_map="auto")
    except TypeError:
        model = AutoModelForCausalLM.from_pretrained(
            model_id, torch_dtype=dtype, device_map="auto")
    model.eval()

    out = []
    short_batches = 0
    n_defaulted = 0
    for start in range(0, len(texts), batch_size):
        chunk = texts[start:start + batch_size]
        prompt = build_prompt(chunk, shots)
        msgs = [{"role": "user", "content": prompt}]
        # apply_chat_template's return type is version-dependent: a bare Tensor
        # on transformers 4.47, a BatchEncoding on >= 4.51. Handle both -- this
        # crashed a cluster job at model load time precisely because the laptop
        # and the cluster sat on opposite sides of that change.
        enc = tok.apply_chat_template(msgs, add_generation_prompt=True,
                                      return_tensors="pt", return_dict=True)
        if torch.is_tensor(enc):
            enc = {"input_ids": enc, "attention_mask": torch.ones_like(enc)}
        else:
            enc = dict(enc)
        # One chunk is ONE prompt, so the mask is all ones -- but pass it
        # explicitly: with pad_token == eos_token, transformers cannot infer it
        # and warns that generation may be unreliable.
        enc.setdefault("attention_mask", torch.ones_like(enc["input_ids"]))
        enc = {k: v.to(model.device) for k, v in enc.items() if torch.is_tensor(v)}
        input_len = enc["input_ids"].shape[-1]
        with torch.no_grad():
            gen = model.generate(**enc,
                                 max_new_tokens=4 * len(chunk) + 32,
                                 do_sample=False,
                                 pad_token_id=tok.pad_token_id)
        text = tok.decode(gen[0][input_len:], skip_special_tokens=True)
        labels = re.findall(r"\b(REFERENTIAL|FILLER)\b", text.upper())
        # A short reply means the model dropped items. Default the remainder to
        # REFERENTIAL so a parse failure never silently deletes data -- but COUNT
        # it. Defaulting quietly is how a broken run comes back looking like
        # "almost nothing was filler" instead of like an error.
        if len(labels) < len(chunk):
            short_batches += 1
            n_defaulted += len(chunk) - len(labels)
            labels += ["REFERENTIAL"] * (len(chunk) - len(labels))
        out += [lab == "FILLER" for lab in labels[:len(chunk)]]
        print(f"    {min(start + batch_size, len(texts))}/{len(texts)}", end="\r")
    print()
    if short_batches:
        print(f"  WARNING: {short_batches} batch(es) returned fewer labels than "
              f"inputs; {n_defaulted} text(s) defaulted to REFERENTIAL. If this is "
              f"more than a handful the model is not following the output format "
              f"-- lower --batch_size or use a stronger model.")
    frac = sum(out) / max(1, len(out))
    if frac < 0.005:
        print(f"  WARNING: the model flagged only {100 * frac:.2f}% of undecided "
              f"texts as filler. Run --self-test: a model too small for this task "
              f"answers REFERENTIAL to everything and looks like a clean result.")
    return out


# ---------------------------------------------------------------------------
# Classify
# ---------------------------------------------------------------------------

def classify(df, cfg, use_llm=True, gold_for_shots=None, batch_size=32):
    """Add `chit_chat` and `method` columns. Classification is per UNIQUE text."""
    # Exp 1 frames already carry a hand-coded `chit_chat`; without this the merge
    # below silently produces chit_chat_x / chit_chat_y and the caller reads
    # neither. The gold labels live in `chit_chat_gold` by then.
    df = df.drop(columns=[c for c in ("chit_chat", "method") if c in df.columns])
    uniq = pd.DataFrame({"text": sorted(df["text"].unique())})
    uniq["rule"] = uniq["text"].map(rule_label)
    n_rule = uniq["rule"].notna().sum()
    print(f"  {len(uniq):,} unique strings; rules decided {n_rule:,} "
          f"({100 * n_rule / len(uniq):.0f}%)")

    undecided = uniq[uniq["rule"].isna()].copy()
    if use_llm and len(undecided):
        shots = sample_shots(gold_for_shots)
        print(f"  {len(undecided):,} to the model ({len(shots)} few-shot examples "
              f"drawn from the gold labels)")
        undecided["llm"] = llm_label(undecided["text"].tolist(), cfg, shots, batch_size)
    else:
        if len(undecided):
            print(f"  {len(undecided):,} undecided -> REFERENTIAL (--no-llm)")
        undecided["llm"] = False

    uniq = uniq.merge(undecided[["text", "llm"]], on="text", how="left")
    uniq["chit_chat"] = uniq["rule"].where(uniq["rule"].notna(), uniq["llm"]).fillna(False)
    uniq["method"] = uniq["rule"].notna().map({True: "rule", False: "llm"})
    return df.merge(uniq[["text", "chit_chat", "method"]], on="text", how="left")


def report(pred, gold, label):
    """Precision/recall/F1 on the CHIT-CHAT class. Accuracy is meaningless at a 4% base rate."""
    tp = int((pred & gold).sum())
    fp = int((pred & ~gold).sum())
    fn = int((~pred & gold).sum())
    tn = int((~pred & ~gold).sum())
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    print(f"\n  {label}")
    print(f"    n={tp + fp + fn + tn:,}   gold chit-chat={tp + fn:,} "
          f"({100 * (tp + fn) / max(1, tp + fp + fn + tn):.1f}%)")
    print(f"    precision {p:.3f}   recall {r:.3f}   F1 {f1:.3f}")
    print(f"    tp={tp}  fp={fp}  fn={fn}  tn={tn}")
    return {"precision": round(p, 4), "recall": round(r, 4), "f1": round(f1, 4),
            "tp": tp, "fp": fp, "fn": fn, "tn": tn}


SELF_TEST = [
    ("hi", True),
    ("gg good game", True),
    ("for me its top right", True),
    ("did it freeze up for you too", True),
    ("alright now you're the matcher", True),
    ("arrow pointing up with a diamond below", False),
    ("the pointy one not the fish", False),
    ("triangle on the left side", False),
    ("looks like a bird with its wings out", False),
    ("no that's not it try again", True),
    ("and it has a hole in the middle too", False),
]


def self_test(cfg, batch_size):
    """Boundary cases run through the REAL pipeline, printed with verdicts.

    Worth ninety seconds before committing a GPU job: a model too small for this
    task answers REFERENTIAL to everything, which produces a plausible-looking
    output file ("only 2% was filler") rather than an error.

    Goes through `classify()` -- rules first, then the model with few-shot
    examples -- because an earlier version called the model directly with no
    examples and no rules. That scored a 3B model at 6/11 and failed on "hi",
    which measured the harness rather than the model. Test what will run.
    """
    df = pd.DataFrame({"text": [t for t, _ in SELF_TEST]})
    gold = [g for _, g in SELF_TEST]
    res = classify(df, cfg, use_llm=True, batch_size=batch_size)
    pred = res.set_index("text").loc[df["text"], "chit_chat"].astype(bool).tolist()
    texts = df["text"].tolist()
    ok = sum(p == g for p, g in zip(pred, gold))
    print(f"\n  self-test: {ok}/{len(gold)} correct\n")
    by = res.set_index("text").loc[texts, "method"].tolist()
    for t, g, p, m in zip(texts, gold, pred, by):
        mark = "ok  " if p == g else "MISS"
        print(f"    {mark} pred={'FILLER' if p else 'REFERENTIAL':12} "
              f"gold={'FILLER' if g else 'REFERENTIAL':12} [{m:4}] {t}")
    if ok < len(gold) - 2:
        print("\n  This model is not reliable enough for the full run.")
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=os.path.join(HERE, "config.yaml"))
    ap.add_argument("--validate", action="store_true",
                    help="score against Exp 1's hand-coded labels instead of labelling Exp 2")
    ap.add_argument("--no-llm", action="store_true", help="rules only")
    ap.add_argument("--batch_size", type=int, default=32)
    ap.add_argument("--limit", type=int, default=None, help="cap texts (smoke test)")
    ap.add_argument("--self-test", action="store_true",
                    help="run 9 boundary cases through the model and stop")
    args = ap.parse_args()
    cfg = load_config(args.config)

    if args.self_test:
        self_test(cfg, args.batch_size)
        return

    if args.validate:
        chats = read_chats(os.path.join(REPO, "data/processed_data/exp_1/run_v3/*/chats.csv"))
        if not len(chats):
            sys.exit("No Exp 1 chats found for validation.")
        chats["chit_chat_gold"] = is_true(chats["chit_chat"])
        # Director messages only. Matcher messages are ~0.6% labeled -- scoring
        # against them measures the annotation's coverage, not the classifier.
        d = chats[is_true(chats["director_msg"])].reset_index(drop=True)
        print(f"validating on {len(d):,} DIRECTOR messages "
              f"({int(d['chit_chat_gold'].sum()):,} hand-labelled chit-chat)")
        if args.limit:
            d = d.sample(min(args.limit, len(d)), random_state=0).reset_index(drop=True)
            print(f"  limited to {len(d):,}")

        # Few-shot examples come from a disjoint half so validation is honest.
        half = d.sample(frac=0.5, random_state=1)
        shots_src = half if not args.no_llm else None
        test = d.drop(half.index) if not args.no_llm else d
        print(f"  scoring on {len(test):,} held-out messages")

        res = classify(test, cfg, use_llm=not args.no_llm,
                       gold_for_shots=shots_src, batch_size=args.batch_size)
        m = report(res["chit_chat"].astype(bool), res["chit_chat_gold"].astype(bool),
                   "rules only" if args.no_llm else "rules + LLM")
        print("\n  Read a residual 10-15% disagreement as gold-set noise: hand-coding")
        print("  caught 87% of unambiguous filler when it stood alone in a round and")
        print("  61% when it sat beside other messages. Do not tune past that.")
        out = os.path.join(REPO, cfg["paths"]["out"])
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, "referential_validation.json"), "w") as f:
            json.dump({"mode": "rules" if args.no_llm else "rules+llm",
                       "model": cfg["referential"]["model"], "metrics": m}, f, indent=2)
            f.write("\n")
        return

    # ---- label Exp 2 -------------------------------------------------------
    chats = read_chats(os.path.join(REPO, cfg["paths"]["processed"], "*", "*", "chats.csv"))
    if not len(chats):
        sys.exit("No Exp 2 chats found. Run 00_preprocessing.R first.")
    print(f"labelling {len(chats):,} Exp 2 messages")

    gold = read_chats(os.path.join(REPO, "data/processed_data/exp_1/run_v3/*/chats.csv"))
    if len(gold):
        gold["chit_chat_gold"] = is_true(gold["chit_chat"])
        gold = gold[is_true(gold["director_msg"])]

    res = classify(chats, cfg, use_llm=not args.no_llm,
                   gold_for_shots=gold if len(gold) else None,
                   batch_size=args.batch_size)
    out = os.path.join(REPO, cfg["paths"]["out"])
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, "referential_flags.parquet")
    keep = [c for c in ["gameID", "roundID", "playerID", "text", "director_msg",
                        "chit_chat", "method"] if c in res.columns]
    res[keep].to_parquet(path, index=False)
    n = int(res["chit_chat"].sum())
    print(f"\n  {n:,} of {len(res):,} messages flagged as filler "
          f"({100 * n / len(res):.1f}%)")
    print(f"  by method: {res.groupby('method')['chit_chat'].sum().to_dict()}")
    print(f"  wrote {os.path.relpath(path, REPO)}")
    print("  03_build_corpus.py joins this on (roundID, playerID, text).")


if __name__ == "__main__":
    main()
