#!/usr/bin/env python3
"""One-screen health check of a RUNNING (or finished) Exp 2 wave, from the server log.

WHY
---
On 2026-09-11 a wave of 38 games ran at ~123-271 s per round against a healthy
32 s, and nothing on the VM said so while it was happening: CPU, memory, disk
and the network all looked fine. The cause is structural. Empirica runs every
server-side callback for every game through ONE global mutex and waits for each
callback's writes to be acknowledged before starting the next (Cake.mutex and
postCallback in @empirica/core admin), so the whole study is a single lane. When
the lane saturates, rounds slow down for everyone at once while the machine
sits idle. The only reliable signal is how long rounds actually take.

This reads the log the server already writes and reports that signal, plus the
number of live and dead games, so the decision "stop admitting people" can be
made in thirty seconds instead of reconstructed afterwards.

USAGE
-----
  # on your laptop, against the VM:
  gcloud compute ssh social-interaction-lab-small-runs --zone=us-central1-f \\
      --project=hs-social-interaction-lab --command='cat ~/exp2-serve.log' \\
      | python3 scripts/wave_monitor.py

  # or against a saved log, optionally as of an earlier time:
  python3 scripts/wave_monitor.py friday.log --at 22:30

Reads stdin if no file is given. Standard library only.

HOW IT TIMES ROUNDS
-------------------
Round log lines written by callbacks.js since 2026-11 carry `t=<epoch ms>`, which
is exact. Older logs (including 2026-09-11) carry no time on those lines, so the
time is interpolated from the nearest preceding timestamped line (Empirica's own
WRN/INF lines). That is accurate to a few seconds while the log is busy, which it
is exactly when this matters.

THRESHOLDS
----------
A round is selection (<=60 s) + feedback (3 s). Healthy rounds measured across
every wave to date: median 32 s, p90 59 s. Friday's lag: 123-271 s.
  GREEN  median round <= 45 s
  AMBER  45-75 s         slowing; do not admit more people
  RED    > 75 s          saturated; stop admitting, let games drain
"""

import argparse
import re
import statistics
import sys
from collections import Counter, defaultdict

ANSI = re.compile(r"\x1b\[[0-9;]*m")
TS = re.compile(r"^(\d\d):(\d\d):(\d\d)\.(\d+)\s+(\w+)\s")
ROUND = re.compile(r"^Game ([0-9A-Z]{26}) - (\d+)/(\d+)\s*$")
TARGET = re.compile(r'^- target: "[^"]*", selection: "([^"]*)", messages: (\d+), '
                    r'inactive per player: \[[\d,]*\](?:, t=(\d{12,14}))?')
STARTED = re.compile(r"^(comp-between|comp-within|noncomp) ([0-9A-Z]{26}) started -- set (\d+)")
ENDED = re.compile(r"^Game ([0-9A-Z]{26}) ended; training (\d+)/(\d+), endedInactive=(\w+)")
ABANDONED = re.compile(r"^Game ([0-9A-Z]{26}): pre-test abandoned")

HEALTHY_S, AMBER_S = 45, 75


def parse(lines):
    """Events from the LAST server run in the log. Times: seconds, rolled past midnight."""
    starts = [i for i, l in enumerate(lines) if "callbacks: connecting" in l]
    lines = lines[starts[-1]:] if starts else lines

    cur, day, last_raw = None, 0, None
    rounds, pending = [], None
    started, ended, abandoned = {}, {}, {}
    warns, errors = [], []          # errors: (time, text)

    for ln in lines:
        m = TS.match(ln)
        if m:
            h, mi, s, ms, level = m.groups()
            t = int(h) * 3600 + int(mi) * 60 + int(s) + int(ms[:3].ljust(3, "0")) / 1000
            if last_raw is not None and t + 3600 < last_raw:     # rolled past midnight
                day += 1
            last_raw = t
            cur = t + day * 86400
            if "invalid transition" in ln:
                warns.append(cur)
            if level == "ERR":
                errors.append((cur, ln[m.end():m.end() + 60].strip()))
            continue
        r = ROUND.match(ln)
        if r:
            pending = (r.group(1), int(r.group(2)))
            continue
        t = TARGET.match(ln)
        if t and pending:
            sel, msgs, epoch = t.groups()
            if epoch:
                rounds.append((("epoch", int(epoch) / 1000.0), pending[0], pending[1], sel == "", int(msgs)))
            elif cur is not None:
                rounds.append((("sod", cur), pending[0], pending[1], sel == "", int(msgs)))
            pending = None
            continue
        s = STARTED.match(ln)
        if s:
            started[s.group(2)] = (cur, s.group(1))
            continue
        e = ENDED.match(ln)
        if e:
            ended[e.group(1)] = (cur, int(e.group(2)), int(e.group(3)), e.group(4) == "true")
            continue
        a = ABANDONED.match(ln)
        if a:
            abandoned[a.group(1)] = cur
    return rounds, started, ended, abandoned, warns, errors


def normalise(rounds):
    """One clock for every round. Exact epoch times win when the log has them."""
    exact = [r for r in rounds if r[0][0] == "epoch"]
    if exact:
        return [(w[1], g, tr, emp, mg) for (w, g, tr, emp, mg) in exact], "exact"
    return [(w[1], g, tr, emp, mg) for (w, g, tr, emp, mg) in rounds], "interpolated"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("log", nargs="?", help="log file (default: stdin)")
    ap.add_argument("--at", help="evaluate as of HH:MM (log-local) instead of the end of the log")
    ap.add_argument("--window", type=int, default=10, help="minutes to measure over (default 10)")
    ap.add_argument("--ceiling", type=float, default=None,
                    help="measured max rounds/min for this server, from loadtest; adds a utilisation line")
    args = ap.parse_args()

    raw = open(args.log).read() if args.log else sys.stdin.read()
    lines = ANSI.sub("", raw).split("\n")
    rounds_raw, started, ended, abandoned, warns, errors = parse(lines)
    rounds, mode = normalise(rounds_raw)
    if not rounds:
        print("no round lines found in this log (wave not started, or wrong file).")
        return

    end_t = max(t for t, *_ in rounds)
    if args.at:
        if mode != "interpolated":
            sys.exit("--at is only supported for logs without exact epoch times")
        h, m = args.at.split(":")
        end_t = int(h) * 3600 + int(m) * 60
    win = args.window * 60

    per_game = defaultdict(list)
    for t, g, tr, emp, mg in rounds:
        if t <= end_t:
            per_game[g].append((tr, t, emp, mg))

    durs, win_rounds, empties = [], 0, 0
    for g, v in per_game.items():
        v.sort(key=lambda x: x[0])
        for (a, ta, _, _), (b, tb, emp, _) in zip(v, v[1:]):
            if b == a + 1 and end_t - win < tb <= end_t and 0 < tb - ta < 900:
                durs.append(tb - ta)
        for tr, t, emp, mg in v:
            if end_t - win < t <= end_t:
                win_rounds += 1
                empties += emp

    def upto(t):
        return t is not None and t <= end_t
    started_now = {g for g, (t, _) in started.items() if upto(t)}
    ended_now = {g: v for g, v in ended.items() if upto(v[0])}
    live = {g for g in started_now if g not in ended_now}
    finished = {g for g, (_, n, exp, inact) in ended_now.items() if not inact and n >= exp}
    died = {g for g in ended_now if g not in finished}
    n_abandoned = sum(1 for t in abandoned.values() if upto(t))
    recent_w = [w for w in warns if end_t - win < w <= end_t]
    recent_err = Counter(txt for t, txt in errors if end_t - win < t <= end_t)

    med = statistics.median(durs) if durs else float("nan")
    p90 = sorted(durs)[int(0.9 * len(durs))] if durs else float("nan")
    rpm = win_rounds / args.window
    state = "UNKNOWN" if not durs else "GREEN" if med <= HEALTHY_S else "AMBER" if med <= AMBER_S else "RED"

    hh, rem = divmod(int(end_t) % 86400, 3600)
    print(f"WAVE MONITOR   log through {hh:02d}:{rem // 60:02d}  ({mode} timing, last {args.window} min)")
    print("-" * 66)
    print(f"games     started {len(started_now):>3}   live {len(live):>3}   "
          f"finished {len(finished):>3}   ended early {len(died):>3}"
          + (f"   (pre-test abandoned {n_abandoned})" if n_abandoned else ""))
    print(f"rounds    {win_rounds:>3} completed in window   {rpm:5.1f}/min   "
          f"empty selections {100 * empties / max(win_rounds, 1):.0f}%")
    print(f"timing    median round {med:6.1f} s   p90 {p90:6.1f} s     (healthy: 32 / 59)")
    if live and rpm:
        print(f"per game  {rpm / len(live):.2f} rounds/min/live game        (healthy: ~1.9)")
    if args.ceiling:
        print(f"capacity  {100 * rpm / args.ceiling:.0f}% of the {args.ceiling:g} rounds/min "
              f"this server sustained in load testing")
    if recent_w:
        print(f"warnings  {len(recent_w)} 'invalid transition' in window ({len(recent_w) / args.window:.1f}/min)")
    if recent_err:
        print("errors    " + "; ".join(f"{n}x {k}" for k, n in recent_err.most_common(2)))
    print("-" * 66)
    msg = {
        "GREEN": "Healthy. Rounds are on pace.",
        "AMBER": "Slowing. Do NOT admit more participants; let the current games run.",
        "RED": f"SATURATED: rounds are {med / 32:.1f}x slower than healthy. Close Prolific places "
               f"now and let live games drain. Restarting kills every live game.",
        "UNKNOWN": "Not enough completed rounds in the window to judge yet.",
    }[state]
    print(f"{state}  {msg}")


if __name__ == "__main__":
    main()
