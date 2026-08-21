#!/usr/bin/env bash
#
# Split experiments/compositional-tangrams into per-version folders:
#
#   experiments/compositional-tangrams-v1/   Exp 1, frozen at the published state
#   experiments/compositional-tangrams-v2/   Exp 2, the current implementation
#
# Each version then owns its own runnable copy and no longer carries code paths
# for an experiment it does not run. Experiment 3 gets -v3 the same way.
#
# v1 is restored byte-for-byte from the pre-Exp-2 commit, so it is exactly what
# produced the published results -- including the 30 tangram images the Exp 2
# deploy script overwrote (white -> transparent).
#
# v2 is LEAN: it drops Exp 1's stimulus sets, data exports, bundle and image
# pool, and regenerates only the images its own schedule references. That keeps
# repo growth near zero. scripts/deploy_exp2_images.py becomes the single source
# of truth for v2's stimuli -- rerun it to widen the set pool.
#
# RUN THIS ONLY ON A CLEAN TREE, AFTER COMMITTING THE EXP 2 WORK.
# It refuses otherwise. Nothing here commits; review with `git status` and
# `git diff --cached` afterwards, then commit yourself.

set -euo pipefail

# The commit holding Exp 1 as published ("add message annotations").
EXP1_REF="48a855dbc4db8406b39c67402e46fbab87bc7fab"

SRC="experiments/compositional-tangrams"
V1="experiments/compositional-tangrams-v1"
V2="experiments/compositional-tangrams-v2"
N_SETS="${N_SETS:-8}"   # override: N_SETS=75 ./scripts/split_experiment_versions.sh

die() { echo "ERROR: $*" >&2; exit 1; }
step() { echo; echo "==> $*"; }

# --- preflight ---------------------------------------------------------------
cd "$(git rev-parse --show-toplevel)" || die "not inside a git repository"

git diff --quiet || die "working tree has unstaged changes. Commit or stash first."
git diff --cached --quiet || die "index has staged changes. Commit them first."

[ -d "$SRC" ] || die "$SRC not found (already split?)"
[ -e "$V1" ] && die "$V1 already exists"
[ -e "$V2" ] && die "$V2 already exists"

git cat-file -e "${EXP1_REF}^{commit}" 2>/dev/null || die "EXP1_REF $EXP1_REF not found"
[ "$(git rev-parse HEAD)" != "$EXP1_REF" ] || die \
  "HEAD is still the Exp 1 commit. Commit the Exp 2 work before splitting, or v2 would be empty."

git cat-file -e "${EXP1_REF}:${SRC}/server/src/callbacks.js" 2>/dev/null \
  || die "$SRC not present at $EXP1_REF"

echo "Repo:     $(pwd)"
echo "HEAD:     $(git log -1 --format='%h %s')"
echo "Exp 1 at: $(git log -1 --format='%h %s' "$EXP1_REF")"

# --- 1. current work becomes v2 ----------------------------------------------
step "Moving current experiment -> $V2"
git mv "$SRC" "$V2"

# --- 2. Exp 1 restored from its own commit becomes v1 ------------------------
step "Restoring Exp 1 from $EXP1_REF -> $V1"
git checkout "$EXP1_REF" -- "$SRC"
git mv "$SRC" "$V1"

# --- 3. strip Exp 1 ballast out of v2 ----------------------------------------
# All of this belongs to Exp 1 only. v2 has its own exp2_*.json stimulus files
# and regenerates its images below.
step "Pruning Exp 1 material from $V2"
for p in \
  "$V2/data" \
  "$V2/compShapesV1.tar.zst" \
  "$V2/client/public/compositional-transparent" \
  "$V2/client/public/tangrams" \
  "$V2/server/src/comp_sets.json" \
  "$V2/server/src/noncomp_sets.json" \
  "$V2/client/src/comp_sets.json" \
  "$V2/client/src/noncomp_sets.json"
do
  if [ -e "$p" ]; then
    git rm -r -q "$p"
    echo "    removed $p"
  fi
done

# --- 4. point the deploy script at v2 and regenerate its images --------------
step "Repointing scripts/deploy_exp2_images.py at $V2"
python3 - "$V2" <<'PY'
import pathlib, sys
v2 = sys.argv[1].split("/")[-1]
p = pathlib.Path("scripts/deploy_exp2_images.py")
s = p.read_text()
old = 'EXP = REPO / "experiments" / "compositional-tangrams"'
new = f'EXP = REPO / "experiments" / "{v2}"'
if old not in s and new in s:
    print("    already repointed")
else:
    assert old in s, "could not find EXP constant in deploy_exp2_images.py"
    p.write_text(s.replace(old, new))
    print(f"    EXP -> experiments/{v2}")
PY

step "Regenerating v2 images (--n-sets $N_SETS)"
python3 scripts/deploy_exp2_images.py --n-sets "$N_SETS"
git add "$V2/client/public/tangrams" scripts/deploy_exp2_images.py

# --- 5. report ----------------------------------------------------------------
step "Done. Nothing has been committed."
echo
printf "  %-40s %8s  %s\n" "PATH" "SIZE" "TANGRAM IMAGES"
for d in "$V1" "$V2"; do
  n=$(ls "$d/client/public/tangrams" 2>/dev/null | wc -l | tr -d ' ')
  printf "  %-40s %8s  %s\n" "$d" "$(du -sh "$d" | cut -f1)" "$n"
done
echo
echo "  Review:  git status  |  git diff --cached --stat | tail -20"
echo "  Then commit yourself. Suggested message:"
echo "      Split experiment into per-version folders (v1 frozen, v2 current)"
