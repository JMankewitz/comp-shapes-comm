#!/usr/bin/env python3
"""Split one wave's payments into per-Prolific-run paste files.

WHY
---
One Empirica wave does not always map to one Prolific study. When a wave has to
be recruited across several Prolific runs, `bonus.csv` covers the whole wave and
pasting it into any single run's bulk-bonus box fails for everyone who belongs
to a different run.

Give it the Prolific ID list for one run and it emits that run's slice of the
same tiers preprocessing already computed. It does NOT reclassify anyone -- the
tier, the amount and the paid.log filtering all come from payments.csv.

It also reports both kinds of mismatch, because both are silent otherwise:
  * IDs in your list that are not in the wave (wrong wave, or a typo)
  * participants in the wave not in ANY list you have run (would go unpaid)

Usage:
    python3 scripts/split_payments.py --wave full_sample/2026-09-08-14-01-45 \\
        --ids ~/Downloads/prolific_run1.csv --label run1

    # check coverage once every run's list has been split
    python3 scripts/split_payments.py --wave full_sample/2026-09-08-14-01-45 \\
        --coverage ~/Downloads/run1.csv ~/Downloads/run2.csv ~/Downloads/run3.csv

The ID file can be a Prolific export or a bare list: any CSV whose header names
a column containing "participant" or "prolific" is used, otherwise the first
column. A file with no header works too.
"""

import argparse
import csv
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROCESSED = os.path.join(REPO, "data", "processed_data", "exp_2")
ID_RE = re.compile(r"^[0-9a-f]{24}$")


def norm(v):
    """Bare lowercase ID. Prolific sometimes sends it in email form."""
    return (v or "").strip().split("@")[0].strip().lower()


def read_ids(path):
    """IDs from a Prolific export or a bare list, with junk rows dropped."""
    with open(path, newline="") as f:
        rows = [r for r in csv.reader(f) if r]
    if not rows:
        sys.exit(f"{path}: empty")
    header, body, col = rows[0], rows, 0
    looks_like_header = not ID_RE.match(norm(header[0]))
    if looks_like_header:
        body = rows[1:]
        named = [i for i, h in enumerate(header)
                 if re.search(r"participant|prolific", h or "", re.I)]
        col = named[0] if named else 0
    ids, junk = set(), 0
    for r in body:
        if col >= len(r):
            continue
        v = norm(r[col])
        if ID_RE.match(v):
            ids.add(v)
        elif v:
            junk += 1
    if not ids:
        sys.exit(f"{path}: no valid 24-hex Prolific IDs found "
                 f"(looked at column {col}"
                 + (f", header {header[col]!r}" if looks_like_header else "")
                 + ")")
    if junk:
        print(f"  note: {junk} non-ID value(s) in {os.path.basename(path)} ignored",
              file=sys.stderr)
    return ids


def load_payments(wave):
    path = os.path.join(PROCESSED, wave, "payments.csv")
    if not os.path.isfile(path):
        sys.exit(f"no payments.csv at {path}\n"
                 f"  run: python3 scripts/ingest_exports.py --into <study> --preprocess")
    with open(path) as f:
        return list(csv.DictReader(f)), path


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wave", required=True,
                    help="<study>/<wave>, e.g. full_sample/2026-09-08-14-01-45")
    ap.add_argument("--ids", help="CSV of Prolific IDs for ONE run")
    ap.add_argument("--label", help="suffix for the output files, e.g. run1")
    ap.add_argument("--coverage", nargs="*",
                    help="check several ID files together: who is in the wave "
                         "but in none of them, and vice versa")
    args = ap.parse_args()

    rows, path = load_payments(args.wave)
    folder = os.path.dirname(path)
    in_wave = {norm(r["prolificID"]): r for r in rows if norm(r["prolificID"])}
    print(f"  wave {args.wave}: {len(in_wave)} participants")

    if args.coverage:
        seen = set()
        for p in args.coverage:
            ids = read_ids(p)
            seen |= ids
            print(f"    {os.path.basename(p):<28} {len(ids):>3} ids, "
                  f"{len(ids & set(in_wave)):>3} in this wave")
        missing = sorted(set(in_wave) - seen)
        extra = sorted(seen - set(in_wave))
        print(f"\n  in the wave but in NO list: {len(missing)}"
              + (" <-- these would go unpaid" if missing else ""))
        for m in missing:
            print(f"    {m}  {in_wave[m]['group']}  ${in_wave[m]['amount']}")
        print(f"  in a list but not in this wave: {len(extra)}")
        for e in extra[:10]:
            print(f"    {e}")
        return

    if not (args.ids and args.label):
        sys.exit("need --ids and --label (or --coverage)")

    ids = read_ids(args.ids)
    hit = {i: in_wave[i] for i in ids if i in in_wave}
    print(f"  {os.path.basename(args.ids)}: {len(ids)} ids, {len(hit)} found in this wave")
    absent = sorted(ids - set(in_wave))
    if absent:
        print(f"  {len(absent)} id(s) NOT in this wave (wrong wave, or never started):")
        for a in absent[:10]:
            print(f"    {a}")

    # Same three tiers preprocessing writes, scoped to this run. paid.log has
    # already been applied upstream via the already_paid column.
    #
    # Into private/, like everything else that carries a Prolific ID. These used
    # to land at the top of the run folder, one `git add .` away from a public
    # repo; .gitignore excludes private/ so that cannot happen.
    priv = os.path.join(folder, "private")
    os.makedirs(priv, exist_ok=True)
    spec = [("bonus", lambda r: r["group"] == "data" and float(r["amount"] or 0) > 0),
            ("lobby", lambda r: r["group"] == "lobby"),
            ("turned_away", lambda r: r["group"] == "no_lobby")]
    print()
    for name, keep in spec:
        sel = [r for r in hit.values()
               if keep(r) and str(r.get("already_paid", "")).upper() != "TRUE"]
        out = os.path.join(priv, f"{name}_{args.label}.csv")
        with open(out, "w", newline="") as f:
            w = csv.writer(f)
            for r in sorted(sel, key=lambda x: -float(x["amount"] or 0)):
                w.writerow([norm(r["prolificID"]), f"{float(r['amount']):.2f}"])
        total = sum(float(r["amount"] or 0) for r in sel)
        print(f"  private/{name}_{args.label}.csv    {len(sel):>3} people  ${total:>7.2f}")
    approve = [r for r in hit.values() if r["group"] == "data"]
    print(f"\n  ALSO approve {len(approve)} submission(s) in this run "
          f"(the $11 base; {sum(1 for r in approve if float(r['amount'] or 0) == 0)} "
          f"of them have a $0 bonus and appear in no paste file)")
    print(f"  in {folder}")


if __name__ == "__main__":
    main()
