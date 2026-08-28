#!/bin/bash
# Exp 2 embedding pipeline on the Stanford NLP cluster.
# Run from: /nlp/scr/jmank/comp-shapes
#
# Steps 02 and 04 are CPU-only and fast enough to run on your laptop; only 03
# wants a GPU. The split below mirrors llm-annotation: prep on john, model work
# on jagupard, collection on john.

set -e

PROJECT_DIR=/nlp/scr/jmank/comp-shapes
ENV=compshapes-nlp
EXP2=$PROJECT_DIR/analysis/exp2

echo "========================================"
echo "Exp 2 embeddings + similarities"
echo "========================================"

# Step 02: referential / chit-chat flags (GPU).
#
# Skipped if referential_flags.parquet already exists -- it changes only when the
# classifier or the message set changes, and 03 joins whatever is there.
if [ ! -f "$PROJECT_DIR/data/embeddings/exp_2/referential_flags.parquet" ]; then
    echo "Submitting 02_referential_filter..."
    nlprun -q jag -g 1 -r 60G -c 8 -p low -a $ENV \
        "cd $PROJECT_DIR && python $EXP2/02_referential_filter.py"
else
    echo "referential_flags.parquet exists, skipping 02"
fi

# Step 03: build the corpus and shard the unique texts (CPU, seconds).
echo "Submitting 03_build_corpus..."
nlprun -q john -r 20G -c 4 -p low -a $ENV \
    "cd $PROJECT_DIR && python $EXP2/03_build_corpus.py"

# How many shards did that produce? Split them across GPU jobs.
N_SHARDS=$(python -c "import json;print(json.load(open('$PROJECT_DIR/data/embeddings/exp_2/manifest.json'))['n_shards'])")
echo "corpus has $N_SHARDS shard(s)"

# Step 04: embed (GPU).
#
# One job is plenty at pilot size -- 3.3k texts is ~2 min even on CPU. Split only
# when the corpus is large; shards are independent and each writes its own file,
# so parallel jobs cannot collide and a dead job resumes at a shard boundary.
if [ "$N_SHARDS" -le 8 ]; then
    echo "Submitting 04_embed (single GPU job)..."
    nlprun -q jag -g 1 -r 40G -c 4 -p low -a $ENV \
        "cd $PROJECT_DIR && python $EXP2/04_embed.py"
else
    HALF=$((N_SHARDS / 2))
    echo "Submitting 04_embed (2 parallel GPU jobs: 0-$HALF, $HALF-$N_SHARDS)..."
    nlprun -q jag -g 1 -r 40G -c 4 -p low -a $ENV \
        "cd $PROJECT_DIR && python $EXP2/04_embed.py --start_shard 0 --end_shard $HALF" &
    nlprun -q jag -g 1 -r 40G -c 4 -p low -a $ENV \
        "cd $PROJECT_DIR && python $EXP2/04_embed.py --start_shard $HALF --end_shard $N_SHARDS" &
    wait
fi

echo ""
echo "Check status with: squeue -u \$USER"
echo ""
echo "After ALL 04_embed jobs finish, build the pair tables (CPU):"
echo "  nlprun -q john -r 40G -c 8 -p low -a $ENV \\"
echo "      \"cd $PROJECT_DIR && python $EXP2/05_similarity.py\""
echo ""
echo "04_embed.py skips shards that already have output, so re-running it is the"
echo "safe way to fill gaps left by a job that died."
