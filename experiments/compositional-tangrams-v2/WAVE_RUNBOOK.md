# Running a collection wave (Experiment 2)

The step-by-step for ONE wave: recruiting people to be online at the same moment,
running the games, paying everyone, and updating the books. `DEPLOY.md` is the
reference for how the server and scripts work; this is the order to do things in.

**Where a command runs matters.** Planning, git, payments and ingest scripts run on
your LAPTOP, in the repo root (`comp-shapes-comm/`, which has `scripts/`). Building,
serving and exporting run on the VM, in `~/comp-shapes-comm/experiments/compositional-tangrams-v2`.
A command that begins `gcloud compute ssh` is run from the laptop. Each step below says
which.

Status: rewritten 2026-11-12 after the 2026-09-11 failure, the load tests, and the
decisions below. Numbers in the box are decisions, not measurements -- see
"What is and is not known" before trusting them.

```
Server                         the big instance (instance-20260113-201755), ONE server, port 3001
CAP                            10 concurrent games = 3 batches of 3 games (9) per datastore wipe. Not raised.
Waves                          1 per day, fresh datastore each time
Lobby                          10 min, with an on-screen countdown (client/src/components/WaitingLobby.jsx)
Pay                            $11 base (approve) + $0.03/correct round; $2.50 lobby; $1.00 turned away
Prolific fee                   33%   ->  about $39.09 per usable dyad all-in
Scheduling survey              $0.30 per respondent (~$0.40 with fee), ~30 slots per wave
Budget (2026-11-12)            $2,280.02, AFTER paying the 2026-09-11 participants
Target                         ~59 / 59 / 58 dyads (comp-within / comp-between / noncomp) ~= 55 more dyads
Sessions                       about 7-8 (a 10-game wave yields ~7-8 usable dyads)
Game study link                http://<IP>:3001/?participantKey={{%PROLIFIC_PID%}}&STUDY_ID={{%STUDY_ID%}}&SESSION_ID={{%SESSION_ID%}}
```

Counts before the next wave (included, completed, with post-test, pilot included,
`bad_run` excluded): comp-within 36, comp-between 41, noncomp 44. Recount before
planning each wave -- exclusions change them.

---

## What went wrong on 2026-09-11, in one paragraph

38 games started within 16 seconds. Rounds took 123-271 s instead of 32 s, 18 games
died, and one usable dyad came out of ~$870. Nothing looked wrong on the VM. The
cause is structural: Empirica runs every server callback for every game through ONE
lock, and the cost of each callback grows with how much the datastore holds. A
48-round game pre-creates ~150 objects the moment it starts, so many simultaneous
starts in a fresh server is the worst case. On a 36-game laptop test, cost per round
was 2.2x higher than at 18 games, and at 72 games no round completed in 400 s. Rules that
follow from it:

1. **Cap concurrent games.** More is not "a bit slower", it collapses.
2. **Never start many games at once.** Starts must be staggered.
3. **Fresh server for every wave.** Old games stay in the datastore and slow it.
4. **Do not tell people to reload.** Reloading adds load to a congested server.
5. **Watch the monitor.** The machine looks idle while the study is dying.

## What is and is not known

- Known (measured on a laptop): healthy at 18 concurrent production-size games,
  cliff near 36, collapse at 72. The small VM is ~2.45x slower per core than the
  laptop, which puts its cliff at roughly 15 games.
- **Not known: how fast the big instance is.** CAP = 10 is a conservative guess from
  the small-VM scaling, not a measurement. It was chosen on purpose because a lost wave
  is unaffordable. The monitor is what tells you whether it holds.
- Empirica stays on **1.12.1**. 1.12.5 was diffed: none of its changes touch the callback
  lock or per-callback cost, so no speedup is expected, and an upgrade is untested risk.
- Admin password and service token are left at the bundle default (decision, 2026-11-12).

---

## Server on/off (the big instance is stopped between waves to save money)

Do these yourself; nothing here is done for you.

- **Start** the instance in the Google Cloud console (Compute Engine > VM instances).
  Allow ~1-2 min for ssh.
- **The external IP changes on every start** unless a static IP is reserved. The IP is
  inside the Prolific study link, so after every start: read the new IP from the console
  and update the study link (and the scheduling survey, if it links to it). Reserving a
  static IP avoids this but is billed while the instance is stopped -- your call.
- **Nothing starts by itself.** After boot the Empirica server is NOT running; you
  start it in tmux (T-30 below). `tmux` sessions do not survive a stop.
- **Stop** the instance only after the export is copied to the laptop and ingested.
  A stopped instance keeps its disk, so the datastore survives, but a wave's data is
  not safe until it is on the laptop.
- Start it at least an hour before T so a problem is found before participants are.

---

## Once-only setup of the big instance (before its first wave)

Check each; fix only what is missing. Commands are the same as DEPLOY.md's first-time setup.

- [ ] ssh works: `gcloud compute ssh instance-20260113-201755 --zone=us-central1-c --project=hs-social-interaction-lab`
- [ ] Disk: `df -h /` -- checked 2026-11-12: 10 GB disk, 1.8 GB free (81% used). The repo plus node_modules is ~0.3 GB and a wave adds ~0.1 GB, so it fits, but keep >1 GB free before each wave and do not install large things. Resizing is possible but not needed.
- [ ] Node and npm: checked 2026-11-12: a non-interactive ssh shell gets the apt Node 18.20.4 with NO npm; an interactive login shell gets nvm Node 24.13.0 with npm. The small VM that produced the existing data used Node 20.19.5. Run `node -v && npm -v` in the same shell you will build in, and note which Node ran the wave.
- [ ] Empirica CLI: the big instance has v1.12.5 installed (the small VM had v1.12.1). The project pins `.empirica/release` = v1.12.1 and the CLI reads that file ("using build from release file"), so `empirica serve` in the project folder should fetch and use 1.12.1 -- confirm the version printed at server start is 1.12.1. If it says 1.12.5, stop and decide before running a wave.
- [ ] tmux and git installed.
- [ ] Repo cloned at `~/comp-shapes-comm` (shallow is fine) and `git remote -v` shows the right origin.
- [ ] `npm install` in BOTH `experiments/compositional-tangrams-v2/client` and `.../server`.
- [ ] Images: stimulus images present on the VM (they are not in git) -- DEPLOY.md "Launching a new wave", step 5.
- [ ] Firewall: from your laptop, `http://<IP>:3001` loads once the server is running. The `allow-empirica` rule covers ports 3000-3010 and has no target tags, so it applies to this instance (checked 2026-11-12).

---

## Smoke test (once per server, ~30 min, free apart from VM time)

There is no load test in this plan, but you should see one real game run before
participants do. With the server up and a TEST treatment batch (test treatments exist
with short settings), open the study link in two browser windows with different
`participantKey` values and check:

- [ ] Window 1 shows the new **"Waiting for a partner"** screen with a 10:00 countdown ticking down. (This screen has been build-checked but never seen rendered.)
- [ ] Window 2 joins; both go into the game; the sound plays.
- [ ] A round completes in both windows; the "Still loading" note does not appear in normal play.
- [ ] `tail -f ~/exp2-serve.log` shows round lines ending in `t=<number>`, and the monitor parses it.
- [ ] `empirica export` works, then **wipe the datastore** (T-30 step) before the real wave.

---

## Before every wave

- **Fresh datastore.** Export first, ingest, confirm `payments.csv` exists, THEN wipe
  (steps below). Never wipe a wave you have not exported.
- **Plan the wave size from CAP, not from the budget.** 10 games per wave. To collect
  faster, run more waves, not bigger ones.
- **Freeze the bundle.** Anything that restarts the server ends every game. No
  deploys, no `empirica bundle`, no reboots during a wave.
- **Free disk.** `df -h /` -- need >1 GB free. `tajriba.json` grows ~0.5 MB/min.
- **Set the log aside.** The log is append-only across runs. Start each wave with a
  clean one: `mv ~/exp2-serve.log ~/exp2-serve-<date>.log`.
- **Prolific balance** covers the wave (about $12 survey + roughly $300-350 for the wave with fee, including bonuses).
- **Do not reload advice.** If participants write in about lag, use the message below.

---

## The session, step by step

Times are before the announced start, T. About an hour end to end. One wave a day.

### T-60  Plan

On the laptop (main checkout, master):

```bash
python3 scripts/flag_timeout_games.py --write
/opt/anaconda3/bin/python3 scripts/flag_component_clashes.py --write
```

```bash
python3 scripts/plan_next_wave.py --n-sets 75 --exclude-games data/processed_data/exp_2/excluded_games.csv data/processed_data/exp_2/timeout_games.csv --include-games data/processed_data/exp_2/included_games.csv --skip-sets data/processed_data/exp_2/clashing_sets.csv
```

(`--n-sets` is the size of the study pool -- use the value you have decided on; 75 is
the original plan and the budget cannot reach it. Review the output, then repeat the
same command with `--write` added.)

If the output says some sets have images missing, run the `deploy_exp2_images.py`
command it prints, and include the new images in the commit below.

**Push the result to GitHub. The server only sees what is on `origin/master`.** The VM
runs `git reset --hard origin/master`, so anything left only on your laptop, or only
on a branch, does not reach it. Do this on the laptop, from the repo root, EVERY time
the planner is re-run:

```bash
git status --short
```

Expect the schedule `experiments/compositional-tangrams-v2/server/src/exp2_set_schedule.json`
(this is the file the server reads to decide which stimulus set each new game gets),
plus any changed exclusion lists under `data/processed_data/exp_2/` and any newly
deployed images. If the schedule is NOT listed, the planner did not write it -- go
back and re-run it with `--write`.

```bash
git add experiments/compositional-tangrams-v2/server/src/exp2_set_schedule.json
```

Add the other files from `git status` that belong to this wave (exclusion lists, new
images under `client/public/tangrams/`), then:

```bash
git commit -m "plan wave: <date>"
```

```bash
git push origin master
```

Then check it landed: `git log origin/master -1` should show your commit. On the VM,
T-30 step `git reset --hard origin/master` will pick it up; afterwards
`git log -1` on the VM should show the same commit message.

Do NOT pull or reset on the VM while a wave is live: that changes files under a
running server, and the server only picks them up on a restart, which ends every game.

This wave: **3 batches (9 games)**. Each batch holds one game per condition, so the
condition a player gets is random. If one condition falls far behind, plan later waves
more deliberately rather than relying on the random draw.

### T-45  Create the scheduling survey and the game study on Prolific

Two stages a few minutes apart, so people are online at the same moment:

1. A short **scheduling survey**, $0.30: "can you take a ~45-minute live study
   starting at {time}?" Duplicate the previous one; change the time, places, and
   internal name. **Places: ~30.** A wave needs 20 players (10 games x 2); 30 is 1.5x
   overbooking. This is a guess -- after the first wave replace it with the real
   show-up rate.
   **Quote ONLY the clock time of the game study, in both Pacific and Eastern.** Never
   write "in 15 minutes" or "N minutes from now": you cannot control when someone sees
   or opens the survey, so any relative time is wrong for late responders.
2. The **game study**, delivered only to the people who said yes, via a **Custom
   Allowlist**.

Game study link (the IP changes whenever the instance is restarted -- paste the
current one):

```
http://<IP>:3001/?participantKey={{%PROLIFIC_PID%}}&STUDY_ID={{%STUDY_ID%}}&SESSION_ID={{%SESSION_ID%}}
```

The game reads `participantKey` from the URL and uses it as the participant's ID.

Over-recruiting past 20 does not add games: extra people are turned away ($1.00 tier)
or time out in the lobby ($2.50 tier). Close the survey once the allowlist is built.

Settings to check every time (a wrong value is copied silently into every later
session):

- reward $11, estimated time ~45 min. **Pay target is $15/h, so $11 covers ~44
  min.** Real sessions run ~37 min to 1.5 h depending on lag; for a session that ran
  long, add a top-up bonus at $0.25/min over 44 min.
- device: desktop; the three completion paths (codes live in
  `client/src/completionCodes.js`: COMPLETE and INCOMPLETE share `CGLXE8O2` (this wave's Prolific default), NO_MATCH
  `CG2CK987` is not shown to participants);
- "approve" action on the completion code (never "screen out" -- it throttles recruitment);
- the participant-group **blocklist** so nobody plays twice.
- **language filters on BOTH the survey and the game study:** fluent English AND the native-language filter your protocol/design calls for. (2026-11-16: this was missed, only fluency was set. Nothing in the game records language, so it can only be recovered from Prolific demographics by Prolific ID.)

### T-30  Bring up the server

On the VM:

```bash
gcloud compute ssh instance-20260113-201755 --zone=us-central1-c --project=hs-social-interaction-lab
```

```bash
tmux kill-server; pkill -u $USER -f callBackSessionToken; sleep 1; ps -u $USER -o cmd | grep -c '[c]allBackSessionToken'
```
(must print `0`)

```bash
cd ~/comp-shapes-comm && git fetch --depth 1 origin master && git reset --hard origin/master && df -h /
```

```bash
mv ~/exp2-serve.log ~/exp2-serve-$(date +%F-%H%M).log 2>/dev/null; rm -f ~/comp-shapes-comm/experiments/compositional-tangrams-v2/.empirica/local/tajriba.json
```

```bash
tmux new -s exp2
```

```bash
cd ~/comp-shapes-comm/experiments/compositional-tangrams-v2 && EMPIRICA_PORT=3001 empirica bundle && EMPIRICA_PORT=3001 empirica serve compShapesV1.tar.zst --addr :3001 2>&1 | tee -a ~/exp2-serve.log
```

Detach with **ctrl-b** then **d**. Never ctrl-c, never pipe to `head`.

Confirm the bundle is current (DEPLOY.md "Each deployment") and that the log says
`callbacks: connecting to http://localhost:3001/query`.

**Create the batches.** Each batch holds THREE games, one per condition. That is
deliberate: it randomises which condition a player gets. How Empirica uses them
(checked against the datastore on 2026-11-16):

- It assigns each arrival to the **running batch that was created FIRST** that still
  has an open game. Inside that batch it picks at RANDOM among the games with room.
- **Start every batch, before you publish and before anyone arrives.** The admin lists
  the newest batch at the top, so starting them "as they fill" starts them newest-first.
  That sends each new arrival to whichever older batch you started last and strands the
  people already waiting in the others. This is what cost players on 2026-11-16.
- **The number of batches is the cap.** 3 games per batch, so CAP = 10 games means
  **3 batches (9 games)**, not 10. Optionally create a 4th and leave it unstarted as a
  reserve; start it only when the monitor is GREEN and the first three are filling.
- **Never terminate a batch that has live players.** It ends their games.
- Treatments snapshot at batch creation, so always make new ones after any
  `treatments.yaml` change. Choose the **"10m individual Kick"** lobby config -- the
  on-screen countdown is hard-coded to 10 minutes and will be wrong for any other.

Known limits of Empirica 1.12.1 assignment (not fixed): a player is assigned to a game
when they CONNECT, before finishing the intro, so a partner who never finishes leaves
the other to time out in the lobby; and `neverOverbookGames` is broken, so when every
game in the first batch is full, extra arrivals are overbooked there instead of moving
on. A proposed fix (assign at intro-done) has not been written or tested.

`maxTimeout` (rounds of inactivity before a game is ended) is **10** on the three
production treatments (the test treatments stay at 5).

Open three things and leave them open: the admin panel, this log in a second terminal
(`tail -f ~/exp2-serve.log`), and the monitor (below).

### T-25  Open the scheduling survey. Watch responses arrive.

### T-15  Build the allowlist, close the survey

Paste the Prolific IDs of everyone who answered yes into the game study's Custom
Allowlist. Close the survey; approve its submissions so respondents are paid.

### T-10  Send the reminder

> Hello! Thank you for signing up for our study. The study will appear on your
> dashboard at {time}. This study depends on real-time participation with a partner,
> so please start it as soon as you see it, and keep your sound on -- a sound plays
> when your game starts. If it doesn't appear after refreshing once, let us know.

### T  Publish the game study

Check the allowlist is attached before publishing: without one the study opens to
everyone on Prolific.

**Stagger the starts.** Games start the moment two people are ready, so a cohort that
all arrives together all start together -- the 2026-09-11 pattern. With only 3
batches (9 games) the batch count enforces the cap, but if the monitor shows AMBER
during the first 5 minutes, stop adding people.

### During the session: read the monitor every 5 minutes

Run it from your LAPTOP, in the repo root (`comp-shapes-comm/`). It copies the log over
ssh and reads it; it does nothing to the server and puts no load on it.

```bash
gcloud compute ssh instance-20260113-201755 --zone=us-central1-c --project=hs-social-interaction-lab --command='cat ~/exp2-serve.log' | python3 scripts/wave_monitor.py
```

Do NOT run it inside the VM: the VM's clone is a sparse checkout of
`experiments/compositional-tangrams-v2` only, so `scripts/` is not there, and the VM has
no gcloud login ("insufficient authentication scopes").

(No `--ceiling` yet: there is no load-test number for this server. After the first wave,
use its peak rounds/min.)

| state | meaning | do this |
|---|---|---|
| GREEN | median round <= 45 s | nothing |
| AMBER | 45-75 s | **stop admitting anyone new.** No more batches, no allowlist additions. |
| RED | > 75 s | close all open places on Prolific, send the "catching up" message, **do not restart** -- a restart kills every live game. Wait for games to drain. |

Do not wait for complaints: on 2026-09-11 this would have said AMBER ~20 minutes
before the first one.

**"The game is catching up" message (send to everyone in running games):**

> Hello! Our game server is busy right now, so the game may pause for a while between
> rounds. Sorry about this -- you will be compensated for the extra time. Please wait
> for the next screen rather than reloading the page, because reloading makes the
> delay longer. Your progress is saved.

---

## After the session

No periodic exports mid-wave -- export once, at the end.

1. **Let games finish**, then give players a few minutes for the exit survey.
2. **Export** (on the VM) and copy it down:

```bash
cd ~/comp-shapes-comm/experiments/compositional-tangrams-v2 && empirica export
```

3. **Ingest** (laptop):

```bash
python3 scripts/ingest_exports.py --into full_sample --preprocess --host instance-20260113-201755 --zone us-central1-c
```

   Check the printed wave and that `private/payments.csv` exists before wiping anything.
4. **Pay.** Preprocessing wrote the paste files to `data/processed_data/exp_2/<study>/<wave>/private/`:

| file | what to do |
|---|---|
| `bonus.csv` | **approve** the submission ($11 base), then paste the bonus |
| `lobby.csv` | paste $2.50 (told to return) |
| `turned_away.csv` | paste $1.00 (told to return) |
| `returns.csv` | pay nothing; ask them to return |

   If the wave ran across several Prolific runs, split the files per run:

```bash
python3 scripts/split_payments.py --wave full_sample/<wave> --ids <prolific export csv> --label <run>
```

5. After Prolific confirms the money landed (once, after ALL runs are paid):

```bash
python3 scripts/mark_paid.py full_sample/<wave>
```

6. **Quality screens**, then update the lists before planning the next wave:
   AI use and paste (`excluded_games.csv`), timeouts (`flag_timeout_games.py --write`).
7. **If the wave went RED or AMBER**, pay the extra time. Round time over the 32 s
   norm is the extra; pay it at your hourly standard, and decide whether the
   lag-affected games are usable (check round times in `trial_timing.csv` -- the
   2026-09-11 data was moved to `bad_run` and excluded as a whole study via
   `data/processed_data/exp_2/excluded_studies.csv`).
8. **Stop the instance** (console) once the export is on the laptop and ingested.
9. **Record this wave's real numbers** here: show-up rate (survey yes -> arrived),
   games started, usable dyads, peak rounds/min. Tune "places" and the cap from them.
10. Next wave: go back to "Before every wave". The datastore is wiped there.

---

## If something goes off script

**The server died or the page says "Just a moment".** Do not restart while it loads:
after a crash it replays the entire datastore before answering (9 minutes in another
lab's wave), and a manual restart throws that progress away. Watch for `server: started`.
`empirica export` reads the database file directly, so you can save the data even with
the server down.

**Someone was paid by mistake.** Prolific cannot reverse a bonus. `mark_paid.py` exists
so a list is never pasted twice -- check the ledger first.

**A participant says the study isn't on their dashboard.** Prolific shows allowlisted
studies late to some people. Send them the Prolific STUDY PAGE link (the study's own
URL on prolific.com), not the server address: opening the server directly skips Prolific, so there is no session to submit the completion code against.

**The instance restarted and the study link stopped working.** The external IP
changed. Read the new one from the console and update the Prolific study link.

**Lobby timeout with another wave later the same day.**

> Hi, really sorry for the lobby timeout -- we couldn't find you a partner because the
> game needs two people online at once, and sometimes people don't show up. If you're
> still interested, we run another session at {time}. You'll be paid $2.50 for your
> time; please return the submission so we can pay you by bonus.

**A game ended early because a partner left.**

> Sorry about that -- your partner left or there was a technical problem, which isn't
> your fault. You'll still be paid in full for your time. Returning the study just
> lets us pay you through the bonus route.

---

## Reference

**Pay tiers** (`analysis/exp2/00_preprocessing.R`, `client/src/tiers.js`):

| tier | who | pay | completion code |
|---|---|---|---|
| data | produced data | $11 base (approve) + $0.03 per correct round | shown |
| lobby | held a slot, no data | $2.50 | none -- told to return |
| no_lobby | some intro, turned away | $1.00 | none -- told to return |
| none | turned away at entry | $0 | none -- told to return |

**Cost per usable dyad:** $29.31 before the 33% fee, $39.09 with it (normal waves).
The scheduling survey is not in that figure (~$12 per wave with fee).

**Ports.** This study runs on 3001. A dedicated VM can use any port 3000-3010 (the
`allow-empirica` firewall rule opens that range).

**Admin console** is at `/admin` on the same address. The default admin password and
service token ship inside the bundle (`.empirica/empirica.toml`) and were left
unchanged by decision.
