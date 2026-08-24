# Deploying Experiment 2 to the lab GCloud VM

Reference for running the study on the lab VM. Commands are meant to be read and
run by hand, one at a time — nothing here is automated on purpose.

```
project   hs-social-interaction-lab
host      social-interaction-lab-small-runs   (us-central1-f, n2-standard-2)
external  34.135.228.108
port      3001                                (NOT 3000 — see below)
```

Workflow is unchanged from Exp 1: push to GitHub → `git pull` on the VM → `empirica
bundle && empirica serve` over ssh → `scp` the data export back. **Data never goes
through git**; it comes home over scp and gets committed only when you choose to.

---

## Three things about this host

**1. It is shared.** Port 3000 is occupied by another lab member's study
(`yajunliu_stanford_edu/experiment-server`). Serve on **3001**. The `allow-empirica`
firewall rule already opens `tcp:3000-3010` to `0.0.0.0/0` for every instance in the
project, so no firewall change is needed. Don't kill anything on 3000.

**2. The disk is nearly full.** 9.7 GB total, ~938 MB free. A normal `git clone` will
fail — this repo's history is large even after `git gc`. Use the shallow + sparse
clone below, which fetches only `experiments/compositional-tangrams-v2` at a single
commit (~13 MB instead of the full history). If `empirica bundle` later dies with
ENOSPC, `~/empirica-tangrams-demo` is 522 MB of an old project you can reclaim.

**3. Run inside tmux.** A bare `empirica serve` over ssh dies the moment your
connection drops, taking the study down mid-session.

### Do not restart `instance-20260113-201755`

It's a `z3-highmem-14-standardlssd` — 14 vCPU, 112 GB RAM, on the order of $1k/month.
Wildly oversized for a study whose bottleneck is websocket round-trips, and it is
currently TERMINATED (not billing). The n2-standard-2 above is already running.

---

## Before you deploy

Confirm locally that the build is good — bundle, wipe the datastore, run through all
three conditions, and abandon one game mid-training to exercise the incomplete-exit
path.

```bash
cd experiments/compositional-tangrams-v2 && rm -f .empirica/local/tajriba.json && empirica bundle
```

Then push:

```bash
git push origin master
```

---

## First-time setup on the VM

SSH in:

```bash
gcloud compute ssh social-interaction-lab-small-runs --zone=us-central1-f --project=hs-social-interaction-lab
```

Shallow, sparse clone — only the v2 experiment, only one commit:

```bash
git clone --depth 1 --filter=blob:none --sparse https://github.com/JMankewitz/comp-shapes-comm comp-shapes-comm
```

```bash
cd comp-shapes-comm && git sparse-checkout set experiments/compositional-tangrams-v2
```

Sanity check — should be ~13 MB and 319 images:

```bash
du -sh experiments/compositional-tangrams-v2 && ls experiments/compositional-tangrams-v2/client/public/tangrams | wc -l
```

---

## Each deployment

Pull the latest (from `~/comp-shapes-comm` on the VM):

```bash
git fetch --depth 1 origin master && git reset --hard origin/master
```

Start it in tmux:

```bash
tmux new -s exp2
```

```bash
cd ~/comp-shapes-comm/experiments/compositional-tangrams-v2 && empirica bundle && empirica serve *.tar.zst --port 3001
```

Detach with **ctrl-b then d**. Do *not* ctrl-c — that ends the study. Reattach later
with `tmux attach -t exp2`.

Participant URL: <http://34.135.228.108:3001/>
Admin console:   <http://34.135.228.108:3001/admin>

Plain http, no TLS. Prolific accepts http links; fine here since nothing collects
credentials.

---

## Before recruiting

**Wipe the datastore on the VM** after any smoke testing:

```bash
rm -f ~/comp-shapes-comm/experiments/compositional-tangrams-v2/.empirica/local/tajriba.json
```

This matters more than it looks. The cross-batch stimulus-set tally lives in Empirica's
global scope, which is stored in `tajriba.json`. Test dyads keep their claim on set 0
otherwise, and the allocation silently starts skewed.

Then create batches from the admin UI — **one batch per game per condition**, which is
the pattern the set-assignment code is built around.

Set Prolific duration and pay from the ~43 min estimate in the design doc (§6.3), not
from Exp 1's numbers.

---

## Getting data back

Export from the admin UI first, then from your laptop:

```bash
gcloud compute scp --zone=us-central1-f --project=hs-social-interaction-lab "social-interaction-lab-small-runs:~/comp-shapes-comm/experiments/compositional-tangrams-v2/*.zip" ./vm_exports/
```

Export zips are gitignored (`experiments/*/compShapesV1-*.zip`), so they won't be
committed by accident.

---

## Stopping

```bash
tmux kill-session -t exp2
```

To stop billing entirely, stop the instance from the console or:

```bash
gcloud compute instances stop social-interaction-lab-small-runs --zone=us-central1-f --project=hs-social-interaction-lab
```

Note this is a shared host — check with the lab before stopping it.

---

## Useful checks

Instance state and IPs:

```bash
gcloud compute instances list --project=hs-social-interaction-lab
```

What's listening, disk pressure, live tmux sessions (run on the VM):

```bash
df -h / && ss -ltn | grep -E ':30(0[0-9]|10)' && tmux ls
```
