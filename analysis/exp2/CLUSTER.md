# Exp 2 embeddings + similarities

`00_preprocessing.R` → **`02_referential_filter.py`** → **`03_build_corpus.py`** →
**`04_embed.py`** → **`05_similarity.py`**

(`01_exploratory.qmd` sits outside this chain; it reads the processed CSVs directly.)

## The design decision behind all of it

Store **embeddings**, not pairwise similarities.

At full-study size the corpus is ~54,000 texts (~21,600 training + ~32,400
pre/post descriptions). Materialising all pairs means 1.46 **billion** rows:

| Artifact | Size |
|---|---|
| All pairs, CSV in the Exp 1 layout (both texts on every row) | 292 GB |
| All pairs, CSV with ids + value only | 87 GB |
| All pairs, parquet float32 + int32 ids | 17.5 GB |
| All pairs, dense float32 triangular matrix | 5.8 GB |
| **Embeddings, Qwen3-0.6B (1024d) float32** | **221 MB** |

With L2-normalised vectors cosine is a dot product, so any subset's similarity
matrix is one matmul. The embedding store answers *more* questions than a pair
table, in 1/80th the space, and survives a change of encoder — swapping models
re-runs `04_embed.py` rather than invalidating a 17 GB derived file.

This is also why `data/processed_data/exp_1/message_similarities.csv` is 205 MB
for 970k rows and will not load: it stores `text1` and `text2` in full on every
row, ~180 bytes of duplicated string per 8-byte similarity. **No pair table
written here contains text.** Join `unit_id_a` / `unit_id_b` back to
`corpus.parquet`.

To read the Exp 1 file today without the memory blowup:

```python
pd.read_csv(path, usecols=["gameID","roundID1","roundID2","playerID1","playerID2","similarity"])
```

## 02: the referential / chit-chat classifier

Replaces Exp 1's hand coding (44,534 messages read by hand, 1,611 marked). Writes
`referential_flags.parquet`; `03_build_corpus.py` joins it on
`(roundID, playerID, text)`. It never edits `chats.csv`, so reclassifying does not
mutate preprocessed data.

**The operative distinction is not "is this a greeting".** It is *does this
message carry information about the target shape's appearance* — learned from the
gold labels, not invented. Task-coordination talk is FILLER even though it is
on-task:

| | |
|---|---|
| `"for me its top right"` | FILLER — position on the SCREEN |
| `"triangle on the left side"` | REFERENTIAL — position within the SHAPE |
| `"alright now you're the matcher"` | FILLER |
| `"did it freeze up for you too"` | FILLER |

Two stages. **Rules** fire only on strings that cannot be referential under any
reading (greetings, acknowledgements, bare punctuation) — narrow by design, since
a rule hit gets no review. Everything else, including anything with shape content,
goes to the **model**. Few-shot examples are sampled from Exp 1's gold labels at
runtime, so the boundary encoded in the prompt is Jess's rather than the prompt
author's.

### What the gold set can and cannot validate

Measured before building this:

- Restricted to **director** messages, coverage is good: of unambiguous filler,
  **87%** is labeled when it stands alone in a round, **61%** when it sits beside
  other messages.
- **Matcher** messages are effectively unannotated — 7,024 messages, 0.6% marked,
  and mostly "ok"/"?" acknowledgements that plainly are filler.

So validation runs on director messages only, and a residual 10–15% disagreement
is gold-set noise, not classifier error. **Do not tune past it** — that is fitting
the annotation's mistakes. Watch precision on the chit-chat class; at a 4% base
rate accuracy is meaningless (always-REFERENTIAL scores 96%).

Rules alone, scored on 37,449 director messages: **precision 0.660, recall 0.322**.
Low recall is the point — the rules deliberately punt anything interesting to the
model.

### Avoid the two Volta nodes in the jag queue

The env's torch is a CUDA 13 build, which carries no kernels below `sm_75`. Two
`jag` nodes are older than that, and a job landing on one loads all the weights
and then dies in `generate()` with `cudaErrorNoKernelImageForDevice`:

| Node | GPU | CC | |
|---|---|---|---|
| jagupard19, 20 | titanv | 7.0 | **unusable** |
| jagupard26, 27 | titanrtx | 7.5 | ok |
| jagupard28, 29 | 3090 | 8.6 | ok |
| jagupard30, 31 | a5000 | 8.6 | ok |
| jagupard32–36 | a6000 | 8.6 | ok |
| jagupard37–39 | rtx6000ada | 8.9 | ok |

Exclude the two rather than pinning a type — it costs almost no availability:

```bash
nlprun -q jag -g 1 -x jagupard19,jagupard20 -r 60G -c 8 -p low -a compshapes-nlp \
    'cd /nlp/scr/jmank/comp-shapes && python analysis/exp2/02_referential_filter.py --self-test'
```

`sphinx` is entirely a100/h100/h200 if `jag` is congested. `sinfo -N -o "%N %G" | sort -u`
lists every node's card; `nlprun --help` has the flags (`-d` requests a GPU type,
`-m` pins one machine, `-x` excludes a comma-separated list).

The scripts check `torch.cuda.get_arch_list()` against the assigned card and exit
in seconds with the card name if there is no kernel for it, rather than failing
after a minute of weight loading.

### Check the model before spending a GPU job

```bash
python analysis/exp2/02_referential_filter.py --self-test
```

Nine boundary cases with verdicts printed. This exists because **a model too
small for the task answers REFERENTIAL to everything**, which produces a
plausible-looking output file ("only 2% was filler") rather than an error.
Qwen2.5-0.5B scores 4/9, missing every FILLER case. Expect ≥7/9 before committing.
The run also warns if fewer than 0.5% of undecided texts come back as filler, and
counts any batch where the model returned fewer labels than inputs.

```bash
# rules only -- no model needed, sanity-checks the plumbing
python analysis/exp2/02_referential_filter.py --validate --no-llm

# full classifier against Exp 1's hand labels
nlprun -q jag -g 1 -r 60G -c 8 -p low -a compshapes-nlp \
    'cd /nlp/scr/jmank/comp-shapes && python analysis/exp2/02_referential_filter.py --validate'

# label Exp 2
nlprun -q jag -g 1 -r 60G -c 8 -p low -a compshapes-nlp \
    'cd /nlp/scr/jmank/comp-shapes && python analysis/exp2/02_referential_filter.py'
```

⚠️ **Back up `data/processed_data/exp_1/run_v3/*/chats.csv` before touching
`analysis/exp1/00_preprocessing.R`.** It hardcodes `chit_chat = FALSE`, so
re-running it over run_v3 destroys all 1,611 hand labels with no error — and
nothing in the code regenerates them.

## One description per round, assembled after filtering

A director often splits one description across several messages, and the unit of
analysis is the whole description. So `03_build_corpus.py` **drops filler
messages first, then concatenates what survives** — the order matters. Joining
first and flagging the round afterwards would leave "hi" and "yes" inside the
text that gets embedded.

A round whose director said nothing referential produces **no unit at all**:
there is no description to compare.

Recorded per unit: `n_messages` (kept), `n_messages_total`, `n_messages_filler`.

`excluded_game` is still a late filter — `05_similarity.py` drops those, so
revisiting an AI/quality exclusion costs only a CPU rerun.

### Re-filtering does not mean re-embedding everything

Because filtering changes the joined text, it changes that round's sha1 — so a
reclassification does need `04_embed.py` again. But the embedding store is
**content-addressed**: `04` builds a sha1→vector cache from whatever it already
has and encodes only genuinely new strings.

Measured on the pilot: a filter revision that changed 84 messages required
encoding **25 texts instead of 3,289** — 100s down to 2.4s. `04` also detects a
shard whose contents changed since the last run and re-embeds it rather than
skipping, so stale vectors can never be paired with new strings.

## The five pair tables

| Table | Pairs | Answers |
|---|---|---|
| `within_dyad_same_target` | same dyad, same shape, different blocks | conventionalisation (Exp 1's headline measure) |
| `within_block` | same dyad, same block, different shapes | systematicity — shared parts across different referents |
| `partner_alignment` | the two partners, same item, within a phase | **DV5**; pre-test value is the naive-convergence baseline |
| `between_dyad_same_item` | different dyads, same set + condition + item | **DV6**, the chance level that makes DV1 and DV5 interpretable (S4.8) |
| `pre_post` | same person, same item, pre vs post | **DV1** |

Anything else is one matmul away — `load_store()` and `pair_frame()` in
`05_similarity.py` are the public helpers.

`between_dyad_same_item` joins on `image`, never `label`: a label means different
things in the comp and noncomp files (see the header of `server/src/exp2.js`).

## Pilot results (38 dyads, MiniLM-L6-v2)

```
within_dyad_same_target     1,958 rows   mean sim 0.635
pre_post                      818 rows   mean sim 0.522
partner_alignment           1,080 rows   mean sim 0.377
between_dyad_same_item      5,244 rows   mean sim 0.343
within_block                7,355 rows   mean sim 0.329
```

All five tables together: **0.4 MB**. Partner alignment (0.377) sits just above
the between-dyad floor (0.343), and within-dyad conventionalisation (0.635) well
above both — the ordering the design predicts, with the DV6 floor doing its job.

Validated against direct `SentenceTransformer.encode` on sampled pairs: max
absolute error 6e-8.

## Model

`Qwen/Qwen3-Embedding-0.6B` (1024d). **Requires `sentence-transformers>=4.1` and
`transformers>=4.51`** — it uses last-token pooling with left padding, and older
releases load it silently but pool incorrectly. You get vectors; they are just
wrong. The laptop env (`coshapes_310`, ST 3.3.1) can only run the MiniLM pass.

**No instruction prefix.** Qwen3 takes one for asymmetric retrieval (query vs
document); every comparison here is description-to-description, so an instruction
on one side would bake a retrieval asymmetry into a symmetric measure.
`config.yaml` pins `prompt_name: null` — do not "improve" this.

`all-MiniLM-L6-v2` (384d) is the cheap robustness check. Both can coexist:

```bash
python analysis/exp2/04_embed.py --model sentence-transformers/all-MiniLM-L6-v2 --tag MiniLM-L6-v2
python analysis/exp2/05_similarity.py --tag MiniLM-L6-v2
```

## Running it

**Laptop** (fine at pilot size — 3.3k texts embed in ~100s on CPU with MiniLM):

```bash
python analysis/exp2/03_build_corpus.py
python analysis/exp2/04_embed.py --device cpu
python analysis/exp2/05_similarity.py
```

**Cluster.** Project dir `/nlp/scr/jmank/comp-shapes`, env `compshapes-nlp`.
Scratch is **not backed up** — code goes up through git, results come back
through rsync. Nothing that only exists on scratch matters.

### Which host does what

Cluster policy ([wiki](https://cluster.cs.stanford.edu/sc)):

> Do NOT run processes with high CPU/RAM/IO on `sc` itself or they will be
> killed. ALL data transfer tasks should be run on `scdt.stanford.edu`.

| Task | Host |
|---|---|
| `git clone`, `git fetch`, `rsync` | **scdt** |
| `conda create`, `pip install` | **scdt** — package downloads are transfers |
| Pre-downloading model weights | **scdt** — gemma-2-9b is ~18 GB |
| `nlprun` submission | `sc` |
| Every pipeline step | a compute node, via `nlprun` |

Nothing in this pipeline should run directly on `sc`; the login node only
submits.

### Getting the code there

Push first, from the laptop:

```bash
git add .gitignore analysis/exp2 data/processed_data/exp_2 && git commit -m "exp2 embedding pipeline" && git push origin master
```

The processed CSVs are tracked, so git carries the code *and* the data the
pipeline reads. Raw exports are not needed on the cluster.

Then clone **from the transfer node**:

```bash
ssh jmank@scdt.stanford.edu
```

**Shallow, blobless and sparse.** `.git` is 2.7 GB but the pipeline needs about
3 MB; a full clone drags the entire stimulus-image history across for nothing.
Same pattern as the study VM:

```bash
cd /nlp/scr/jmank && git clone --depth 1 --filter=blob:none --sparse https://github.com/JMankewitz/comp-shapes-comm comp-shapes
```

```bash
cd /nlp/scr/jmank/comp-shapes && git sparse-checkout set analysis/exp2 data/processed_data/exp_2
```

Sanity check — should be a few MB, not gigabytes:

```bash
du -sh /nlp/scr/jmank/comp-shapes && ls /nlp/scr/jmank/comp-shapes/analysis/exp2
```

### Environment and model weights (one-time, also on scdt)

Both are transfers, so neither belongs on `sc`:

```bash
conda create -n compshapes-nlp python=3.10 -y && conda activate compshapes-nlp && pip install -r /nlp/scr/jmank/comp-shapes/analysis/exp2/requirements.txt
```

**Point the HuggingFace cache at scratch before downloading anything.** The
default is `~/.cache/huggingface`; gemma-2-9b (~18 GB) plus the embedding model
will blow a home-directory quota:

```bash
echo 'export HF_HOME=/nlp/scr/jmank/hf_cache' >> ~/.bashrc && source ~/.bashrc && mkdir -p $HF_HOME
```

Pre-fetch the weights here rather than inside a GPU job — downloading 18 GB while
holding a GPU wastes the allocation, and gemma is a gated repo, so an
unauthenticated job fails *after* it has queued and started:

The CLI is `hf`. `huggingface-cli` was removed in `huggingface_hub` >= 0.34 and
now prints a deprecation notice instead of running.

```bash
hf auth login
```

Ungated model first: if it succeeds, the cache path and token both work, so any
failure on gemma is specifically the licence gate rather than setup.

```bash
hf download Qwen/Qwen3-Embedding-0.6B
```

```bash
hf download google/gemma-2-9b-it
```

⚠️ **gemma-2-9b-it is a GATED repo.** Accept the licence once, signed in, at
<https://huggingface.co/google/gemma-2-9b-it>. Until then every download and
every job 401s regardless of the token — and a job discovers this *after* it has
queued and taken a GPU. `Qwen/Qwen2.5-7B-Instruct` is ungated and comparable at
this task if you would rather skip the gate; it is a one-line change in
`config.yaml`, and `--self-test` will tell you in thirty seconds whether the
substitute holds up.

Both `HF_HOME` and `HF_TOKEN` must be visible to the `nlprun` jobs, which is why
they go in `~/.bashrc` rather than being exported for one shell.

### Every subsequent run

Push from the laptop, then on **scdt** (not `sc` — it is a transfer):

```bash
cd /nlp/scr/jmank/comp-shapes && git fetch --depth 1 origin master && git reset --hard origin/master
```

`reset --hard` is safe here precisely because nothing is authored on scratch —
every output lands in `data/embeddings/`, which is gitignored and comes home by
rsync.

```bash
bash analysis/exp2/run_embeddings.sh
```

Then pull the results back:

```bash
rsync -avz --progress \
    jmank@scdt.stanford.edu:/nlp/scr/jmank/comp-shapes/data/embeddings/exp_2/ \
    data/embeddings/exp_2/
```

`data/embeddings/` is gitignored — everything under it regenerates from
`processed_data`.

## Resumability

Each shard writes `emb_XXXX.npy` plus `emb_XXXX.ids.parquet`, and a shard whose
output exists is skipped. A job killed at shard 19 of 27 resumes at 19; re-running
`04_embed.py` is the safe way to fill gaps. Writes go to a temp name and are
renamed, so a job killed mid-write cannot leave a truncated file that the resume
logic mistakes for complete.

`--start_shard` / `--end_shard` split work across parallel jobs; they never touch
each other's files.

## Gotchas

- Rebuilding the corpus after embedding invalidates the store — `05_similarity.py`
  exits with "N corpus texts have no embedding" rather than silently dropping
  them. Re-run `04_embed.py`.
- `03_build_corpus.py` deletes stale shards before writing, so a corpus that
  shrinks cannot leave orphaned shards to be embedded and merged in.
- Embedding is keyed on sha1 of the exact string, so identical texts are embedded
  once. Expect the unique count well below the row count (11% repeats at pilot
  size; higher at full scale as block-4 conventions shorten and repeat).
