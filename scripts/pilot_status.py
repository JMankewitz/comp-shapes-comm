#!/usr/bin/env python3
"""Live-ish status for a running Exp 2 study, keyed by PROLIFIC ID.

The Empirica admin console shows internal ULIDs and, once a game ends, stops
telling you anything at all -- which is a problem here because the POST-TEST runs
as an exit step after the game is over. This reads a tajriba.json snapshot and
reports what the admin cannot:

  * post-test progress per participant, as it rolls in
  * who is paired with whom, by Prolific ID
  * who finished, who is mid-post-test, who never reached a game
  * last activity per participant, to spot people who walked away

Read-only. Run it against a snapshot copied down from the VM:

  gcloud compute scp --zone=us-central1-f --project=hs-social-interaction-lab \\
    "social-interaction-lab-small-runs:~/comp-shapes-comm/experiments/compositional-tangrams-v2/.empirica/local/tajriba.json" \\
    /tmp/taj.json

  python3 scripts/pilot_status.py /tmp/taj.json

NOTE: live connection state (the admin's red/green dot) is NOT in tajriba -- it is
ephemeral server memory. `idle` here is a staleness proxy: minutes since that
participant last wrote anything.
"""

import json
import sys
from datetime import datetime, timezone

# Attributes we care about; everything else is skipped for speed.
KEYS = {
    "participantID", "gameID", "contextStructure", "setId", "setReplicate",
    "posttestResponses", "pretestResponses", "completedStudy", "finishedTraining",
    "ended", "partner", "role", "introDone", "numPosttestItems", "treatmentName",
}


def parse_ts(s):
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    if "." in s:  # trim fractional seconds to 6 digits
        head, rest = s.split(".", 1)
        frac = "".join(c for c in rest if c.isdigit())[:6]
        tz = rest[len(frac):] if not rest[len(frac):].isdigit() else ""
        for marker in ("+", "-"):
            if marker in rest:
                tz = rest[rest.index(marker):]
                break
        s = f"{head}.{frac.ljust(6,'0')}{tz or '+00:00'}"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def load(path):
    participants = {}     # participant id -> Prolific identifier
    attrs = {}            # (nodeID, key) -> (createdAt, val)
    last_write = {}       # nodeID -> latest createdAt

    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind, obj = rec.get("kind"), rec.get("obj") or {}
            if kind == "Participant":
                participants[obj.get("id")] = obj.get("Identifier")
            elif kind == "Attribute":
                key, node = obj.get("key"), obj.get("nodeID")
                if key not in KEYS or not node:
                    continue
                ts = obj.get("createdAt")
                prev = attrs.get((node, key))
                # append-only: last write for a (node, key) wins
                if prev is None or (ts or "") >= prev[0]:
                    attrs[(node, key)] = (ts or "", obj.get("val"))
                if ts and ts > last_write.get(node, ""):
                    last_write[node] = ts
    return participants, attrs, last_write


def val(attrs, node, key, default=None):
    got = attrs.get((node, key))
    if got is None:
        return default
    v = got[1]
    if v is None:
        return default
    try:
        return json.loads(v)
    except (json.JSONDecodeError, TypeError):
        return v


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/taj.json"
    participants, attrs, last_write = load(path)

    # A node is a player scope if it carries a participantID.
    players = {n for (n, k) in attrs if k == "participantID"}
    now = datetime.now(timezone.utc)

    rows = []
    for node in players:
        pid = val(attrs, node, "participantID")
        prolific = participants.get(pid) or "(unknown)"
        game = val(attrs, node, "gameID")
        post = val(attrs, node, "posttestResponses", []) or []
        pre = val(attrs, node, "pretestResponses", []) or []
        n_post = val(attrs, node, "numPosttestItems") or 20
        ts = parse_ts(last_write.get(node, ""))
        idle = (now - ts).total_seconds() / 60 if ts else None

        if val(attrs, node, "completedStudy"):
            state = "DONE"
        elif game and len(post) > 0:
            state = "post-test"
        elif game and val(attrs, node, "finishedTraining"):
            state = "post-test (0)"
        elif game:
            state = "in game"
        elif val(attrs, node, "introDone"):
            state = "LOBBY/unmatched"
        else:
            state = "intro"

        rows.append({
            "prolific": prolific, "game": (game or "-")[:10],
            "cond": (val(attrs, node, "treatmentName") or "-").replace("exp2-", ""),
            "pre": f"{len(pre)}", "post": f"{len(post)}/{n_post}",
            "state": state, "idle": idle,
        })

    order = {"DONE": 0, "post-test": 1, "post-test (0)": 2, "in game": 3,
             "LOBBY/unmatched": 4, "intro": 5}
    rows.sort(key=lambda r: (order.get(r["state"], 9), -(r["idle"] or 0)))

    print(f"\n{'PROLIFIC ID':<26}{'GAME':<12}{'COND':<15}{'PRE':>4}{'POST':>8}"
          f"  {'STATE':<16}{'IDLE':>7}")
    print("-" * 92)
    for r in rows:
        idle = f"{r['idle']:.0f}m" if r["idle"] is not None else "-"
        flag = "  <-- stalled" if (r["idle"] or 0) > 10 and r["state"] not in ("DONE",) else ""
        print(f"{r['prolific']:<26}{r['game']:<12}{r['cond']:<15}{r['pre']:>4}"
              f"{r['post']:>8}  {r['state']:<16}{idle:>7}{flag}")

    print()
    from collections import Counter
    for state, n in Counter(r["state"] for r in rows).most_common():
        print(f"  {state:<18} {n}")
    done = sum(1 for r in rows if r["state"] == "DONE")
    inpost = sum(1 for r in rows if r["state"].startswith("post-test"))
    print(f"\n  post-tests complete: {done}   still working: {inpost}")
    print("  (idle = minutes since last write; NOT the admin's connection dot)")


if __name__ == "__main__":
    main()
