# Deploying Experiment 2 to the lab GCloud VM

Reference for running the study on the lab VM. Commands are meant to be read and
run by hand, one at a time — nothing here is automated on purpose.

```
project   hs-social-interaction-lab
host      social-interaction-lab-small-runs   (us-central1-f, n2-standard-2)
external  34.135.228.108
port      3001   via --addr :3001            (NOT 3000 — see below)
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

**Install dependencies before the first bundle.** `empirica bundle` runs
`npm run build`, not `npm install` — on a fresh clone there is no `node_modules`,
so the build falls through to whatever global `vite` exists on the box (currently
7.2.2, which demands Node 20.19+ and cannot find
`@vitejs/plugin-react-refresh`). The error looks like a Node version problem but
is really a missing-dependency problem. Locally this never surfaces because
`node_modules` is already there from development.

```bash
cd ~/comp-shapes-comm/experiments/compositional-tangrams-v2/client && npm install && cd ../server && npm install
```

Empirica pins Node 20.10.0 itself via the `volta` field in `package.json`, using
its own vendored volta under `~/.local/share/empirica` — that pin is correct and
the locally-installed `vite 2.9.15` works fine on it. Do not "fix" the Node
version.

---

## Each deployment

Pull the latest (from `~/comp-shapes-comm` on the VM):

```bash
git fetch --depth 1 origin master && git reset --hard origin/master
```

**Build on the VM.** The bundle is gitignored (`*.tar.zst`), so it is never
pushed or pulled — each host builds its own from the source it just checked out.

```bash
cd ~/comp-shapes-comm/experiments/compositional-tangrams-v2 && EMPIRICA_PORT=3001 empirica bundle
```

Check the bundle is actually newer than the source you just pulled. `empirica
serve` does **not** rebuild, so restarting a server without bundling silently
serves the old client — the failure is invisible, because the app comes up fine
and simply behaves like the previous version:

```bash
cd ~/comp-shapes-comm/experiments/compositional-tangrams-v2 && ls -l --time-style=+%H:%M compShapesV1.tar.zst && find client/src server/src -newer compShapesV1.tar.zst -name '*.js*' | head
```

If that `find` prints any file, the bundle is stale — bundle again before serving.

Start it in tmux:

```bash
tmux new -s exp2
```

```bash
cd ~/comp-shapes-comm/experiments/compositional-tangrams-v2 && EMPIRICA_PORT=3001 empirica serve compShapesV1.tar.zst --addr :3001
```

**Both the flag and the env var are required, and they must match.**

- `--addr :3001` moves the server's listener. It is `--addr` (or `--server.addr`),
  **not** `--port` — Empirica v1.12.1 rejects `--port` as an unknown flag. Note the
  leading colon: `--addr :3001` binds all interfaces, while `--addr 3001` is read as
  a hostname.
- `EMPIRICA_PORT=3001` tells the **callbacks process** where to connect back to.
  `server/src/index.js` builds its websocket URL from it. Empirica does not pass
  `--addr` through to the callbacks, so without this they dial `localhost:3000` —
  which on this shared host is another lab member's app, and the handshake dies with
  `Unexpected server response: 404` on `/query`.

Exp 1 never hit this because it always ran on the default 3000, where the old
hardcoded fallback happened to be correct.

On startup the callbacks log `callbacks: connecting to http://localhost:3001/query`.
If that line says 3000, the env var did not take.

Detach with **ctrl-b then d**. Do *not* ctrl-c — that ends the study. Reattach later
with `tmux attach -t exp2`.

Participant URL: <http://34.135.228.108:3001/>
Admin console:   <http://34.135.228.108:3001/admin>

Plain http, no TLS. Prolific accepts http links; fine here since nothing collects
credentials.

---

## Launching a new wave

`[L]` = laptop, `[VM]` = server. Run top to bottom.

**1. Export** the finished wave from the admin UI: <http://34.135.228.108:3001/admin>

**2. [L]** Pull + unpack + preprocess every new export:

```bash
python3 scripts/ingest_exports.py --into full_sample --preprocess
```

**3. [L]** Pay this wave now — don't wait for the study to end.

Preprocessing (step 2) already wrote the paste-ready files. All are two columns,
no header, so select the whole file and paste into Prolific's bulk bonus box.
In `data/processed_data/exp_2/pilot_v1/<wave>/`:

| file | tier | what to do |
|---|---|---|
| `bonus.csv` | gave data | **approve** the submission ($11 base), then paste the bonus |
| `lobby.csv` | held a slot, no data | paste $2.50; they were told to return |
| `turned_away.csv` | some intro, no lobby | paste $1.00; they were told to return |
| `returns.csv` | turned away at entry | nothing to pay — ask them to return |

`payments.csv` has everyone with `group`, `action`, `minutes` and `already_paid`
for anything you want to check by hand. Anyone under ~25 min is flagged CHECK.

**3b. [L]** After Prolific confirms the payments went through:

```bash
python3 scripts/mark_paid.py full_sample/<wave>

python3 scripts/mark_paid.py full_sample/2026-08-28-20-31-40
```

Only run this once the money has actually landed. The ledger exists to stop the
same list being pasted twice, and it is only useful if a row means "Prolific
accepted this" rather than "I meant to pay this". Add `--only bonus` / `--only
lobby` / `--only turned_away` if you pay the tiers at different times.

**4. [L]** Plan the next wave (review, then `--write`):

```bash
python3 scripts/plan_next_wave.py --n-sets 75 --exclude-games data/processed_data/exp_2/excluded_games.csv
```

Always pass `--exclude-games`. Coverage counts dyads that *completed*, and a dyad
excluded post hoc (AI use, degenerate responses) completed exactly like a real
one — so without this its set reads as finished and the hole is only discovered
at analysis time, after recruitment has closed. Add rows to that CSV as each
wave's quality screens run, not at the end.

The report ends with `dyads still needed next wave: ...` — that total is what to
recruit, not `n_sets x 2 x 3`.

```bash
python3 scripts/plan_next_wave.py --n-sets 75 --write
```

`--write` now emits a `targets` map (remaining dyads per condition per set, `0`
meaning finished) and stamps the schedule `exp2-schedule-2`. A bundle older than
that throws on load rather than ignoring the targets, so the code and the
schedule must ship in the same deploy — which steps 6–10 already do.

`--n-sets` is the size of the pool the schedule will name — 8 while piloting,
~75 for the full study (S4.8). It must match what you deploy images for in step
5. A schedule naming 75 sets when only 8 sets of PNGs are on the VM will happily
assign a dyad to set 40 and serve them broken images; the schedule's own `notes`
field says as much. Widening the pool means widening both, and the VM has ~938 MB
free — check `df -h /` before a large jump.

**5. [L]** Deploy images for the sets step 4 chose. Use the exact
`--set-ids` line `plan_next_wave.py` printed:

```bash
python3 scripts/deploy_exp2_images.py --set-ids 2,3,4,5,6,7,8,9
```

**Do not pass `--n-sets` here.** Both scripts write the same
`server/src/exp2_set_schedule.json`, and `--n-sets N` re-selects the best N sets
from scratch — silently overwriting the plan step 4 just wrote, including the
partially-collected sets it resumed. The images would then be for a different
pool than the schedule names, and the first games log sets whose PNGs are absent.

**6. [L]** Push:

```bash
git add -A experiments/compositional-tangrams-v2 scripts analysis && git commit -m "wave N" && git push origin master
```

**7. [VM]** SSH in:

```bash
gcloud compute ssh social-interaction-lab-small-runs --zone=us-central1-f --project=hs-social-interaction-lab
```

**8. [VM]** Kill the old server and any orphaned callbacks — must print `0`:

```bash
tmux kill-server; pkill -u $USER -f callBackSessionToken; sleep 1; ps -u $USER -o cmd | grep -c callBackSessionToken
```

**9. [VM]** Pull, check disk, wipe the datastore:

```bash
cd ~/comp-shapes-comm && git fetch --depth 1 origin master && git reset --hard origin/master && df -h /
```

```bash
rm -f ~/comp-shapes-comm/experiments/compositional-tangrams-v2/.empirica/local/tajriba.json
```

**10. [VM]** Start in tmux:

```bash
tmux new -s exp2
```

```bash
cd ~/comp-shapes-comm/experiments/compositional-tangrams-v2 && EMPIRICA_PORT=3001 empirica bundle && EMPIRICA_PORT=3001 empirica serve compShapesV1.tar.zst --addr :3001 2>&1 | tee -a ~/exp2-serve.log
```

**11. [VM]** Detach with **ctrl-b** then **d** (release ctrl first). If that fails, from a second shell:

```bash
tmux detach-client -s exp2
```

**12. [VM]** Watch:

```bash
tail -f ~/exp2-serve.log
```

**13. [L]** Verify, then create **fresh batches** in the admin UI:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://34.135.228.108:3001/
```

A 200 only proves the server is up — it says nothing about whether the browser is
running the new bundle, which is the part that silently fails. After the first
dyad reaches training, confirm the client-side stamps are being written:

```bash
grep -c '"trainingStartedAt"' ~/comp-shapes-comm/experiments/compositional-tangrams-v2/.empirica/local/tajriba.json
```

Two per dyad that entered training. `0` means the bundle is stale — the pull
landed but `empirica bundle` did not rerun, or it ran before the pull.

### Gotchas

- Never pipe `empirica serve` to `head` — SIGPIPE kills the study. `tee` is safe.
- Batches snapshot the treatment at creation. Old batches carry old values; always make new ones.
- First games should log the sets step 4 printed. `set 0` when the schedule said otherwise = the VM didn't pull.
- Re-exporting is safe — coverage dedups by ULID. Export often, pay promptly.

---

## Running a wave

Order matters — several of these fail silently if skipped.

**1. Wipe the datastore.** The cross-batch stimulus-set tally lives in Empirica's
global scope, stored in `tajriba.json`. Test dyads keep their claim on set 0
otherwise and the allocation starts skewed.

```bash
tmux kill-server; rm -f ~/comp-shapes-comm/experiments/compositional-tangrams-v2/.empirica/local/tajriba.json
```

**2. Check disk before every wave.** `tajriba.json` grows ~0.5 MB/min during a run
and never compacts. Under ~500 MB free, reclaim first.

```bash
df -h / && npm cache clean --force && sudo apt-get clean && sudo journalctl --vacuum-size=50M
```

**3. Create fresh batches.** Batch configs snapshot the treatment **at creation**,
so a batch made before a `treatments.yaml` edit still runs the old values — this is
how a wave silently ran at `describeSecondsPerItem: 45` after it had been changed
to 60. Use **one batch per game per condition** (Empirica's documented
recommendation): each batch holds 1 game per treatment.

**4. Watch the first few games in the log.** Expect:

```
Game ... (comp-within) -> set 0, replicate 0, slot 0, rotation 0deg. Tally now {...}
Game ... (comp-within) -> set 0, replicate 0, slot 1, rotation 0deg.
Game ... (comp-between) -> set 0, replicate 0, slot 0, rotation 0deg.
```

Each condition tallies independently, so all three start at set 0 — that is what
makes the within-set between-condition contrast stimulus-matched. Sets fill
depth-first (both slots of set 0 before set 1) because the analysis unit is the
PAIR: a set with one dyad contributes nothing to the between-dyad comparison.

## Monitoring a live wave

Both scripts are read-only and run on your laptop against a snapshot, so they
cannot disturb the server. The admin console shows internal ULIDs and goes blind
once a game ends — which is exactly when the post-test runs, since it is an exit
step.

```bash
gcloud compute scp --zone=us-central1-f --project=hs-social-interaction-lab "social-interaction-lab-small-runs:~/comp-shapes-comm/experiments/compositional-tangrams-v2/.empirica/local/tajriba.json" /tmp/taj.json
```

```bash
python3 scripts/pilot_status.py /tmp/taj.json
```

`pilot_status.py` gives post-test progress and pairings keyed by Prolific ID.

Payment lists come from preprocessing an export, not from the live snapshot —
see "Launching a new wave" step 3.

## After an unplanned restart

A restart can leave a stage `started=True, ended=False` with an expired duration,
and submits recorded *before* the restart may not be honoured after it. That is
what left two pilot participants on "Waiting for your partner" for 30 and 45
minutes. After any unexpected restart, look for such rounds and end those games
deliberately rather than leaving people hanging.

**Never pipe `empirica serve` to `head`.** `head` exits after N lines, the pipe
closes, and empirica dies on SIGPIPE mid-study. Use `tee`:

```bash
cd ~/comp-shapes-comm/experiments/compositional-tangrams-v2 && EMPIRICA_PORT=3001 empirica serve compShapesV1.tar.zst --addr :3001 2>&1 | tee -a ~/exp2-serve.log
```

## Before recruiting

Superseded by "Launching a new wave" (steps 9 and 13) and "Running a wave", which
cover the wipe and the batch pattern in the order they actually happen. Kept only
for the one fact that lives nowhere else:

Set Prolific duration and pay from the ~43 min estimate in the design doc (§6.3),
not from Exp 1's numbers. The pilot's measured median was 38.4 min.

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
