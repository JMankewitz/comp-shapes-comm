#!/usr/bin/env python3
"""Record that a wave's bonus.csv / lobby.csv have actually been paid.

Run this AFTER pasting into Prolific and seeing the payment go through -- not
before. The ledger exists to stop the same list being pasted twice; it is only
useful if a row in it means "Prolific accepted this", never "I intended to".

The previous ledger was back-filled from export data instead, so it marked
people as paid who had not been, and silently shrank the next paste file. That
is the failure this script is shaped to avoid: it logs exactly the rows that
were in the files you pasted, and nothing else.

Usage:
    python3 scripts/mark_paid.py pilot_v1/2026-08-25-18-24-02            # both
    python3 scripts/mark_paid.py pilot_v1/2026-08-25-18-24-02 --only bonus
    python3 scripts/mark_paid.py pilot_v1/2026-08-25-18-24-02 --dry-run
"""

import argparse
import datetime
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROCESSED = os.path.join(REPO, "data", "processed_data", "exp_2")
PAID_LOG = os.path.join(REPO, "data", "paid.log")

FILES = {"bonus": "bonus.csv", "lobby": "lobby.csv",
         "turned_away": "turned_away.csv"}


def load_paid():
    """{(prolificID, category)} already recorded."""
    seen = set()
    if os.path.isfile(PAID_LOG):
        with open(PAID_LOG) as f:
            for line in f:
                if line.startswith("#"):
                    continue
                parts = [x.strip() for x in line.split(",")]
                if len(parts) >= 3:
                    # Key on the ID alone -- see the note in 00_preprocessing.R:
                    # keying on (id, category) means a tier rename re-lists
                    # people who were already paid.
                    seen.add(parts[0].split("@")[0])
    return seen


def read_pairs(path):
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [x.strip() for x in line.split(",")]
            if len(parts) >= 2:
                out.append((parts[0], parts[1]))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("wave", help="<study>/<wave>, e.g. pilot_v1/2026-08-25-18-24-02")
    ap.add_argument("--only", choices=sorted(FILES), default=None,
                    help="record just one category (default: both)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    folder = os.path.join(PROCESSED, args.wave)
    if not os.path.isdir(folder):
        sys.exit(f"no processed wave at {folder}")

    cats = [args.only] if args.only else sorted(FILES)
    already = load_paid()
    rows, skipped = [], 0

    for cat in cats:
        path = os.path.join(folder, FILES[cat])
        if not os.path.isfile(path):
            print(f"  {FILES[cat]}: not present, skipping")
            continue
        pairs = read_pairs(path)
        fresh = [(p, a) for p, a in pairs if p.split("@")[0] not in already]
        skipped += len(pairs) - len(fresh)
        print(f"  {FILES[cat]}: {len(pairs)} row(s), {len(fresh)} new")
        rows += [(p, cat, a) for p, a in fresh]

    if skipped:
        print(f"  {skipped} already in the ledger -- not re-logged")
    if not rows:
        print("\nNothing new to record.")
        return
    if args.dry_run:
        print(f"\n--dry-run: would record {len(rows)}")
        for p, cat, a in rows:
            print(f"    {p},{cat},{a}")
        return

    stamp = datetime.date.today().isoformat()
    with open(PAID_LOG, "a") as f:
        for p, cat, a in rows:
            f.write(f"{p},{cat},{a},{stamp}\n")
    total = sum(float(a) for _, _, a in rows)
    print(f"\nrecorded {len(rows)} payment(s), ${total:.2f}, in data/paid.log")
    print("Re-run preprocessing to refresh bonus.csv/lobby.csv for this wave.")


if __name__ == "__main__":
    main()
