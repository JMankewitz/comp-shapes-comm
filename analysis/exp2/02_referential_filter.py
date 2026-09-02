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

import numpy as np
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
#
# SINGLE LETTERS ARE NOT FILLER. Tangrams get named for the letter they resemble
# ("M", "W", "E", "L", "K"), so a pattern matching a lone letter silently deletes
# a convention. A bare "k" for "ok" was doing exactly that.
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

PROMPT_HEADER = """You are helping analyse how people invent shared names for \
abstract shapes. Two players play a reference game: the director describes a \
tangram shape so their partner can pick it out of four on screen. Over repeated \
rounds they converge on short conventional labels for each shape.

Our goal is to extract, for each round, the director's DESCRIPTION of the shape \
— discarding everything else — and then measure how those descriptions change as \
conventions form. The messages you keep are concatenated into that description. \
Dropping a real description destroys the measurement; keeping a stray "ok" merely \
adds noise. When genuinely unsure, keep it.

Label each message REFERENTIAL or FILLER.

DESCRIBES THE SHAPE (answer YES) — contributes anything about what the shape LOOKS LIKE: its parts, \
their arrangement within the shape, its orientation, or what it resembles.

  - BREVITY IS NOT FILLER. Conventions get shorter with practice. By the last \
    round a full description may be two words: "down arrow", "n shape", "the \
    fish", "tall". These are the most important messages in the corpus.
  - NEGATION IS USUALLY DESCRIPTION. "no triangle", "not the fish", "No cutout", \
    "not the ones pointed straight down" say what the shape does NOT have, which \
    identifies it. Only a bare "no" with nothing attached is filler.
  - FOLLOW-UP DETAIL COUNTS: "it has a hole in the middle too", "and the bottom \
    is flat".
  - Corrections count: "sorry not a triangle, a parallelogram".

DOES NOT (answer NO) — everything else, including talk that is on-task:
  - Greetings, sign-offs, thanks, reactions ("lol", "Ikr").
  - Bare agreement or disagreement with NOTHING attached: "yes", "no", "ok".
  - Turn coordination: "your turn now", "you're the director".
  - Interface and study talk: freezing, lag, refreshing, timers, pay, bonus.

CRITICAL — position ON THE SCREEN is FILLER; position WITHIN THE SHAPE is \
REFERENTIAL. The four shapes appear in a DIFFERENT ORDER for each player, so \
"it's the top right one" or "for me that was bottom left" tells the partner \
nothing. But "triangle on the left side" or "diamond at the bottom" describes \
the shape itself.

Decide whether the message says anything about what the SHAPE looks like."""


# A deliberately minimal alternative to PROMPT_HEADER.
#
# The elaborate prompt lists rules, caveats and a CRITICAL section, and its
# FILLER bullet says 'bare agreement or disagreement: "yes", "no", "ok"'. A 7B
# model then dropped 89% of messages beginning "no" -- including "no small
# square on right" and "no hole", which are descriptions. The instructions
# created the failure. This asks the one question the task actually is.
PROMPT_MINIMAL = """Two people are playing a game. One of them (the DIRECTOR) can \
see an abstract shape and has to describe it so their partner can pick that shape \
out of four on screen.

Your job: decide whether one message says anything about what the SHAPE looks like.

YES - it describes the shape or any part of it, in any way. This includes very \
short messages ("down arrow", "R", "the fish") and messages saying what the shape \
is NOT ("no hole", "not the triangle one").

NO  - it says nothing about the shape's appearance: greetings, reactions, talk \
about the game, the website or the timer, and talk about where a shape sits on \
the SCREEN ("it's the top right one") rather than within the shape."""


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

def build_prompt(batch_texts, shots, context=None, target_idx=None):
    """One message to judge, optionally shown inside its round transcript.

    CONTEXT IS THE POINT. Judged alone, "R" could be a typo and "no hole" could
    be a reply. Inside a round where the director is describing a shape, both are
    obviously description -- and the round transcript is exactly what a human
    annotator has in front of them. Without it a 7B model destroyed 89% of
    negated descriptions and 33% of one-word ones while being confident about it.
    """
    lines = [PROMPT_MINIMAL if PROMPT_STYLE == "minimal" else PROMPT_HEADER, ""]
    if shots:
        lines.append("Examples:")
        for t, lab in shots:
            lines.append(f'  "{t}" -> {"YES" if lab == "REFERENTIAL" else "NO"}')
        lines.append("")
    if context:
        lines.append("Here is the full chat for one round of the game. The two "
                     "players are trying to agree on ONE target shape:")
        for i, entry in enumerate(context):
            who, msg = entry[0], entry[1]
            mark = "  >>> " if i == target_idx else "      "
            lines.append(f'{mark}{who}: {msg}')
        lines.append("")
        lines.append("Does the message marked >>> say anything about what the "
                     "shape looks like? Answer YES or NO.")
    else:
        lines.append(f'Message: "{batch_texts[0]}"')
        lines.append("Does this message say anything about what the shape looks "
                     "like? Answer YES or NO.")
    return "\n".join(lines)


FEWSHOT_FILE = os.path.join(HERE, "fewshot_examples.csv")

# Set from --prompt; module-level so build_prompt stays a pure function of it.
PROMPT_STYLE = "full"


def sample_shots(gold=None, n=None, seed=0):
    """The CURATED illustrative examples -- all of them, in a fixed order.

    NOT sampled, and NOT drawn from the annotated corpus. An earlier version took
    random short messages from the Exp 1 hand labels, which was wrong twice over:
    those labels carry roughly 10-15% noise, so the prompt was shown uncertain
    calls as if they were definitions -- and random sampling meant a run could
    contain no example of the very boundary it was about to get wrong.

    An example's job is to illustrate the distinction unambiguously. They live in
    `fewshot_examples.csv`, one per row with a `why` column; edit that file to
    change what the model is taught. Using ALL of them every time also keeps the
    prompt constant, which makes runs comparable and the cache meaningful.
    """
    if gold is not None and len(gold):
        rng = random.Random(seed)          # legacy path, callers that pass a frame
        pairs = []
        for lab, want in (("FILLER", True), ("REFERENTIAL", False)):
            pool = gold[gold["chit_chat_gold"] == want]
            pool = pool[pool["text"].str.len() <= 60]
            if len(pool):
                k = min((n or 32) // 2, pool["text"].nunique())
                pairs += [(t, lab) for t in rng.sample(list(pool["text"].unique()), k)]
        rng.shuffle(pairs)
        return pairs

    if not os.path.exists(FEWSHOT_FILE):
        print("  WARNING: fewshot_examples.csv missing -- the classifier is much "
              "weaker without examples.")
        return []
    pool = pd.read_csv(FEWSHOT_FILE)
    pairs = list(zip(pool["text"].astype(str), pool["label"].astype(str)))

    # INTERLEAVE the labels. Read straight from the file the examples come out
    # grouped -- every YES, then every NO -- so the last thing the model sees
    # before the question is a run of 14 NOs. Block-ordered demonstrations bias
    # few-shot models toward the trailing label, which is the exact direction
    # (over-flagging as filler) this classifier kept failing in. Deterministic
    # alternation keeps the prompt constant across runs.
    yes = [x for x in pairs if x[1] == "REFERENTIAL"]
    no = [x for x in pairs if x[1] != "REFERENTIAL"]
    out, i, j = [], 0, 0
    while i < len(yes) or j < len(no):
        if i < len(yes):
            out.append(yes[i]); i += 1
        if j < len(no):
            out.append(no[j]); j += 1
    return out


def config_fingerprint(cfg, shots):
    """Identifies WHAT produced a set of labels: model, prompt text, examples.

    A cache is only reusable if all three are unchanged. Without this, editing a
    prompt or swapping examples and re-running silently resumes the old scores
    and reports them as new -- which has now happened three times, once masking a
    broken thinking-mode run whose numbers looked like a real result.
    """
    import hashlib
    parts = [cfg["referential"]["model"], PROMPT_STYLE,
             PROMPT_MINIMAL if PROMPT_STYLE == "minimal" else PROMPT_HEADER,
             "|".join(f"{t}=>{l}" for t, l in shots)]
    return hashlib.sha1("\n".join(parts).encode()).hexdigest()[:12]


def cache_path(cfg, model_id):
    """Where partial labels live. Keyed by MODEL -- a different model is a
    different labelling, and silently reusing another model's decisions would be
    invisible in the output."""
    out = os.path.join(REPO, cfg["paths"]["out"])
    os.makedirs(out, exist_ok=True)
    slug = re.sub(r"[^A-Za-z0-9]+", "-", model_id).strip("-")
    # Prompt style is part of the identity: two styles give different labels for
    # the same text, and silently merging them would be invisible.
    # Always suffix, including "full": an unsuffixed name collided with the
    # pre-context cache and silently merged two incompatible key formats into
    # one file, which then read back as the older run's results.
    return os.path.join(out, f"llm_labels_{slug}_{PROMPT_STYLE}_ctx.parquet")


def llm_label(items, cfg, shots, batch_size=32, cache_file=None, flush_every=10,
              threshold=0.5, fingerprint=None):
    """Label texts with a local instruct model. Returns list of bools (True=filler).

    RESUMABLE. Partial results are flushed to `cache_file` every `flush_every`
    batches and reloaded on the next run, because the low-priority queue preempts:
    a validate pass is ~475 model calls, and losing all of it to a SIGTERM at 90%
    is the difference between a coffee break and an afternoon.
    """
    from transformers import AutoModelForCausalLM, AutoTokenizer
    import torch

    done = {}
    if cache_file and os.path.exists(cache_file):
        try:
            prev = pd.read_parquet(cache_file)
            # Older caches stored a bool; newer ones store P(filler) so the
            # threshold can be moved without re-running the model.
            stale = (fingerprint is not None
                     and "fingerprint" in prev.columns
                     and len(prev) and prev["fingerprint"].iloc[0] != fingerprint)
            if stale:
                print(f"  cache was built with a DIFFERENT prompt/model "
                      f"({prev['fingerprint'].iloc[0]} != {fingerprint}); ignoring it "
                      f"and re-scoring from scratch")
                prev = prev.iloc[0:0]
            elif fingerprint is not None and "fingerprint" not in prev.columns:
                print("  cache predates fingerprinting; ignoring it to be safe")
                prev = prev.iloc[0:0]
            if "p_filler" in prev.columns:
                done = dict(zip(prev["text"], prev["p_filler"].astype(float)))
            else:
                done = {t: (1.0 if v else 0.0)
                        for t, v in zip(prev["text"], prev["chit_chat"].astype(bool))}
            print(f"  resuming: {len(done):,} label(s) already cached")
        except Exception as e:
            print(f"  ignoring unreadable cache {cache_file}: {e}")

    # items: list of (cache_key, prompt_text). The key carries the round, so the
    # same string in two different rounds is scored separately -- context makes
    # them different questions.
    keys = [k for k, _ in items]
    todo_idx = [i for i, k in enumerate(keys) if k not in done]
    if not todo_idx:
        print("  every message already labelled from cache; no model needed")
        return [done[k] > threshold for k in keys]
    if len(todo_idx) < len(items):
        print(f"  {len(todo_idx):,} of {len(items):,} still need the model")
    todo = [keys[i] for i in todo_idx]

    def flush():
        if not cache_file:
            return
        pd.DataFrame({"text": list(done.keys()),
                      "p_filler": list(done.values()),
                      "chit_chat": [v > threshold for v in done.values()],
                      "fingerprint": fingerprint}).to_parquet(
            cache_file + ".tmp", index=False)
        os.replace(cache_file + ".tmp", cache_file)

    from transformers import AutoModelForCausalLM, AutoTokenizer
    import torch

    model_id = cfg["referential"]["model"]
    print(f"  loading {model_id} ...")
    tok = AutoTokenizer.from_pretrained(model_id)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    tok.padding_side = "left"  # last-position logits must be the true last token

    if torch.cuda.is_available():
        major, minor = torch.cuda.get_device_capability()
        name = torch.cuda.get_device_name(0)
        dtype = torch.bfloat16 if major >= 8 else torch.float16
        print(f"  GPU: {name} (CC {major}.{minor}) -> "
              f"{'bfloat16' if dtype is torch.bfloat16 else 'float16'}")
        # Binary compatibility holds WITHIN a major compute-capability
        # generation: an sm_86 cubin runs on sm_89. An exact match is the wrong
        # test -- it rejected an RTX 6000 Ada against a build carrying sm_86.
        arch_list = torch.cuda.get_arch_list()
        dev_arch = f"sm_{major}{minor}"
        compatible = [a for a in arch_list
                      if (m := re.match(r"sm_(\d)(\d+)$", a))
                      and int(m.group(1)) == major and int(m.group(2)) <= minor]
        if arch_list and not compatible:
            sys.exit(
                f"\n  This torch build has no kernels for {name} ({dev_arch}).\n"
                f"  torch.cuda.get_arch_list() = {arch_list}\n"
                f"  (need some sm_{major}x with minor <= {minor})\n\n"
                f"  Resubmit excluding the Volta nodes:\n"
                f"    nlprun ... -x jagupard19,jagupard20 ...\n"
            )
        print(f"  kernels via {sorted(compatible)[-1]}")
    else:
        dtype = torch.float32
        print("  no CUDA visible -> float32 on CPU (slow)")

    try:
        model = AutoModelForCausalLM.from_pretrained(
            model_id, dtype=dtype, device_map="auto")
    except TypeError:
        model = AutoModelForCausalLM.from_pretrained(
            model_id, torch_dtype=dtype, device_map="auto")
    model.eval()

    # ---- SCORE, don't generate ---------------------------------------------
    #
    # Earlier this asked the model to emit one word per line for a batch of 32
    # messages and parsed the reply. That was wrong in three ways:
    #   * 20 batches returned fewer labels than inputs, silently defaulting 50
    #     texts to REFERENTIAL;
    #   * holding 32 items in one prompt lets the model drift across the list;
    #   * it discards the model's actual confidence.
    # Measured cost: precision 0.299, and 18% of ONE-WORD descriptions wrongly
    # called filler -- exactly the conventionalised short forms this project
    # exists to measure.
    #
    # Instead: one message per prompt, a single forward pass, compare the logits
    # of the two answer tokens. Deterministic, impossible to drop an item, no
    # parsing, and it yields a probability that can be thresholded.
    # YES / NO are SINGLE tokens of comparable frequency. The previous pair was
    # not: "REFERENTIAL" tokenises to ['REFER', 'ENTIAL'] and "FILLER" to
    # ['F', 'ILL', 'ER'], so the comparison was P('REFER') vs P('F') -- and 'F'
    # is far more likely a priori, biasing every decision toward FILLER.
    def one(word, *alts):
        for w in (word,) + alts:
            ids = tok.encode(w, add_special_tokens=False)
            if len(ids) == 1:
                return ids[0]
        return tok.encode(word, add_special_tokens=False)[0]
    tok_ref = one("YES", "Yes", "yes", " YES")
    tok_fil = one("NO", "No", "no", " NO")
    if tok_ref == tok_fil:
        raise RuntimeError("YES/NO share a first token for this tokenizer")
    print(f"  answer tokens: YES={tok_ref} NO={tok_fil} "
          f"({tok.decode([tok_ref])!r}/{tok.decode([tok_fil])!r})")

    # Instruction-tuned models must see their chat template. This was lost when
    # generation (which applied it) was replaced by logit scoring (which did
    # not), and a 7B model then behaved close to randomly -- flagging ~50% of
    # everything as filler. add_generation_prompt=True opens the assistant turn,
    # so the very next token is the answer we score.
    def wrap(text):
        msgs = [{"role": "user", "content": text}]
        # enable_thinking=False is REQUIRED for hybrid reasoning models.
        #
        # Qwen3's default template ends at "<|im_start|>assistant\n", so the
        # model's next token is "<think>" -- and this code scores the next token
        # for YES vs NO. Comparing two tokens the model has no intention of
        # emitting yields a flat, meaningless signal: Qwen3-32B returned
        # P(filler) < 0.1 for every message in the self-test, filler included.
        # Passing False emits an EMPTY "<think></think>" block, so the very next
        # token is the answer. Models without the flag raise TypeError.
        try:
            return tok.apply_chat_template(msgs, tokenize=False,
                                           add_generation_prompt=True,
                                           enable_thinking=False)
        except TypeError:
            pass
        try:
            return tok.apply_chat_template(msgs, tokenize=False,
                                           add_generation_prompt=True)
        except Exception:
            return text + "\nAnswer:"
    prompts = [wrap(items[i][1]) for i in todo_idx]
    probs = []
    start = 0
    while start < len(prompts):
        chunk = prompts[start:start + batch_size]
        enc = tok(chunk, return_tensors="pt", padding=True, truncation=True,
                  max_length=4096, add_special_tokens=False).to(model.device)
        # Ask for ONE position's logits, not all of them.
        #
        # A causal LM returns [batch, seq_len, vocab] by default. At batch 32,
        # ~950 tokens of prompt and Qwen's 152k vocab that is 9.3 GB in bf16 --
        # which OOMed a 50 GB card -- and every position but the last is thrown
        # away here. The kwarg was renamed across transformers versions, so try
        # both and fall back to the full tensor with a smaller batch.
        try:
          with torch.no_grad():
            try:
                out_l = model(**enc, logits_to_keep=1)
            except TypeError:
                try:
                    out_l = model(**enc, num_logits_to_keep=1)
                except TypeError:
                    out_l = model(**enc)
            logits = out_l.logits[:, -1, :]
        except torch.cuda.OutOfMemoryError:
            if batch_size <= 1:
                raise
            batch_size = max(1, batch_size // 2)
            print(f"\n  CUDA OOM -- halving batch to {batch_size} and retrying")
            torch.cuda.empty_cache()
            continue
        pair = torch.stack([logits[:, tok_fil], logits[:, tok_ref]], dim=-1)
        p_fil = torch.softmax(pair.float(), dim=-1)[:, 0]
        probs += p_fil.tolist()
        for t, p in zip(todo[start:start + batch_size], p_fil.tolist()):
            done[t] = float(p)
        if ((start // max(1, batch_size)) + 1) % flush_every == 0:
            flush()
        print(f"    {min(start + batch_size, len(todo)):,}/{len(todo):,}", end="\r")
        start += batch_size
    print()
    flush()
    out = [done.get(k, 0.0) > threshold for k in keys]
    if probs:
        arr = np.array(probs)
        print(f"  P(filler): mean {arr.mean():.3f}, "
              f"{(arr > threshold).sum():,} of {len(arr):,} over {threshold}; "
              f"{((arr > 0.4) & (arr < 0.6)).sum():,} within 0.1 of the boundary")
    frac = sum(out) / max(1, len(out))
    if frac < 0.005:
        print(f"  WARNING: the model flagged only {100 * frac:.2f}% of undecided "
              f"texts as filler. Run --self-test: a model too small for this task "
              f"answers REFERENTIAL to everything and looks like a clean result.")
    return out


# ---------------------------------------------------------------------------
# Classify
# ---------------------------------------------------------------------------

def classify(df, cfg, use_llm=True, gold_for_shots=None, batch_size=32,
             context_df=None):
    """Add `chit_chat` and `method` columns.

    Classification is per MESSAGE IN ITS ROUND, not per unique string. The same
    text in two rounds is two different questions once context is supplied, and
    context is what makes short and negated messages decidable at all.

    `df` is the set of messages TO LABEL. `context_df` is the full, unfiltered
    chat used to reconstruct each round's transcript -- they are different
    frames and conflating them was a real bug: validation labels only director
    messages from a random half, so building transcripts from it showed the
    model roughly a quarter of each round with the matcher's side missing.
    Pass the complete chat frame as `context_df`.
    """
    df = df.drop(columns=[c for c in ("chit_chat", "method") if c in df.columns]).copy()
    df["_rule"] = df["text"].map(rule_label)

    n_rule = int(df["_rule"].notna().sum())
    print(f"  {len(df):,} messages; rules decided {n_rule:,} "
          f"({100 * n_rule / max(1, len(df)):.0f}%)")

    need = df[df["_rule"].isna()]
    if use_llm and len(need):
        shots = sample_shots(gold_for_shots)
        has_ctx = "roundID" in df.columns
        print(f"  {len(need):,} to the model ({len(shots)} few-shot examples"
              f"{', with round context' if has_ctx else ', NO round context'})")

        # Build one transcript per round so every judged message can be shown
        # inside the exchange it belongs to.
        src = context_df if context_df is not None else df
        transcripts = {}
        if has_ctx:
            for rid, grp in src.groupby("roundID", sort=False):
                msgs = []
                for i, r in grp.iterrows():
                    who = ("DIRECTOR"
                           if str(r.get("director_msg", "")).upper() in ("TRUE", "T", "1")
                           else "MATCHER")
                    # carry the source index so the target can be located exactly
                    msgs.append((who, r["text"], i))
                transcripts[rid] = msgs

        items = []
        for _idx, r in need.iterrows():
            if has_ctx:
                rid = r["roundID"]
                ctx = transcripts.get(rid, [])
                # By source index first: a round can legitimately contain the
                # same string twice, and matching on text marked the wrong one.
                idx = next((k for k, (_, _, i) in enumerate(ctx) if i == _idx), None)
                if idx is None:
                    idx = next((k for k, (_, m, _) in enumerate(ctx)
                                if m == r["text"]), None)
                key = f"{rid}|{r['text']}"
                prompt = build_prompt([r["text"]], shots, context=ctx, target_idx=idx)
            else:
                key = r["text"]
                prompt = build_prompt([r["text"]], shots)
            items.append((key, prompt))

        preds = llm_label(items, cfg, shots, batch_size,
                          cache_file=cache_path(cfg, cfg["referential"]["model"]),
                          threshold=float(cfg["referential"].get("threshold", 0.5)),
                          fingerprint=config_fingerprint(cfg, shots))
        df.loc[need.index, "_llm"] = preds
    else:
        if len(need):
            print(f"  {len(need):,} undecided -> REFERENTIAL (--no-llm)")
        df.loc[need.index, "_llm"] = False

    df["chit_chat"] = (df["_rule"].where(df["_rule"].notna(), df.get("_llm"))
                       .astype("boolean").fillna(False).astype(bool))
    df["method"] = df["_rule"].notna().map({True: "rule", False: "llm"})
    return df.drop(columns=[c for c in ("_rule", "_llm") if c in df.columns])


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
    # Held out from fewshot_examples.csv ON PURPOSE. Reusing curated examples
    # here would test whether the model can echo its own prompt, not whether it
    # can draw the distinction. Keep these disjoint if you edit either file.
    ("hey there", True),
    ("you got it", True),
    ("mine is frozen", True),
    ("how much are we getting paid for this", True),
    ("i clicked the wrong one sorry", True),
    ("3 hooks", False),
    ("half circle on top", False),
    ("K", False),
    ("no diamond", False),
    ("not the one with the hat", False),
    ("with two feet", False),
]


def debug_tokens(cfg, k=10):
    """What does the model actually want to say? Prints top-k next tokens.

    Logit scoring compares P(YES) against P(NO) at the first answer position.
    That is only meaningful if the model INTENDS to emit one of them. If its real
    preference is "Yes", "**", or "The", both candidates sit far down the
    distribution and their ratio reflects token frequency rather than the answer
    -- which looks exactly like a confident classifier returning a near-constant
    probability for every input.
    """
    from transformers import AutoModelForCausalLM, AutoTokenizer
    import torch

    model_id = cfg["referential"]["model"]
    tok = AutoTokenizer.from_pretrained(model_id)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    tok.padding_side = "left"
    try:
        model = AutoModelForCausalLM.from_pretrained(
            model_id, dtype=torch.bfloat16, device_map="auto")
    except TypeError:
        model = AutoModelForCausalLM.from_pretrained(
            model_id, torch_dtype=torch.bfloat16, device_map="auto")
    model.eval()

    shots = sample_shots()
    for text, gold in SELF_TEST[:6]:
        prompt = build_prompt([text], shots)
        msgs = [{"role": "user", "content": prompt}]
        try:
            full = tok.apply_chat_template(msgs, tokenize=False,
                                           add_generation_prompt=True,
                                           enable_thinking=False)
        except TypeError:
            full = tok.apply_chat_template(msgs, tokenize=False,
                                           add_generation_prompt=True)
        enc = tok(full, return_tensors="pt", add_special_tokens=False).to(model.device)
        with torch.no_grad():
            logits = model(**enc).logits[0, -1, :]
        probs = torch.softmax(logits.float(), dim=-1)
        top = torch.topk(probs, k)
        print(f"\n  {text!r}  (gold={'FILLER' if gold else 'REFERENTIAL'})")
        print("     top tokens: " + ", ".join(
            f"{tok.decode([i])!r}:{p:.3f}" for p, i in zip(top.values.tolist(),
                                                           top.indices.tolist())))
        for w in ("YES", "NO", "Yes", "No", "yes", "no"):
            wid = tok.encode(w, add_special_tokens=False)
            if len(wid) == 1:
                print(f"     P({w!r}) = {probs[wid[0]].item():.5f}", end="")
        print()


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
    pred = res["chit_chat"].astype(bool).tolist()
    texts = df["text"].tolist()
    ok = sum(p == g for p, g in zip(pred, gold))
    print(f"\n  self-test: {ok}/{len(gold)} correct\n")
    by = res["method"].tolist()
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
    ap.add_argument("--prompt", choices=["full", "minimal"], default="minimal",
                    help="minimal asks the one question the task is; full is the "
                         "rule-laden version whose FILLER bullet taught a 7B model "
                         "to drop every message starting with 'no'")
    ap.add_argument("--debug-tokens", action="store_true",
                    help="print the model's ACTUAL top next-token predictions for "
                         "the self-test cases. Logit scoring is only valid if the "
                         "model intends to emit one of the two candidates; if it "
                         "wants 'Yes' or '**' instead, the YES/NO ratio is noise.")
    ap.add_argument("--self-test", action="store_true",
                    help="run 9 boundary cases through the model and stop")
    args = ap.parse_args()
    global PROMPT_STYLE
    PROMPT_STYLE = args.prompt
    cfg = load_config(args.config)

    if args.debug_tokens:
        debug_tokens(cfg)
        return

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

        # Few-shot examples come from the COMMITTED pool, and the messages in it
        # are removed from the test set. The previous version split the data in
        # half to source shots -- discarding 50% of the evaluation to obtain 32
        # examples, and leaking anyway since the same string recurs across
        # rounds. Excluding 393 texts costs almost nothing and is airtight.
        shot_texts = set()
        if os.path.exists(FEWSHOT_FILE):
            shot_texts = set(pd.read_csv(FEWSHOT_FILE)["text"].astype(str))
        test = d[~d["text"].isin(shot_texts)] if shot_texts else d
        print(f"  scoring on {len(test):,} messages "
              f"({len(d) - len(test):,} excluded as few-shot examples)")

        # `chats` -- NOT `test` -- supplies the round transcripts: the full
        # exchange including the matcher, unfiltered and unsplit.
        res = classify(test, cfg, use_llm=not args.no_llm,
                       gold_for_shots=None, batch_size=args.batch_size,
                       context_df=chats)
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

    # Label the DIRECTOR's messages; the matcher's turns are still supplied as
    # context so "no hole" is read inside the exchange it belongs to.
    targets = chats[is_true(chats["director_msg"])] if "director_msg" in chats else chats
    res = classify(targets, cfg, use_llm=not args.no_llm,
                   gold_for_shots=None, batch_size=args.batch_size,
                   context_df=chats)
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
