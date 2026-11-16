import json, glob, sys, re
tag = sys.argv[1] if len(sys.argv)>1 else "base"
rows=[]
for f in glob.glob(f"{sys.argv[2] if len(sys.argv)>2 else '.'}/res-{tag}-n*.json"):
    d=json.load(open(f)); r=d["rep"]; rows.append(r)
rows.sort(key=lambda r:r["games"])
print(f"{'tag':<10}{'games':>6}{'rounds/min':>11}{'click->fb p50/p90/p99 (ms)':>30}{'fb->next p50/p90/p99 (ms)':>30}{'round wall p50 (s)':>20}")
for r in rows:
    c=r["click_to_feedback_ms"]; n=r["feedback_to_next_ms"]; w=r["round_wall_ms"]
    print(f"{r['label']:<10}{r['games']:>6}{r['rounds_per_min']:>11}{str((c['p50'],c['p90'],c['p99'])):>30}{str((n['p50'],n['p90'],n['p99'])):>30}{(w['p50']/1000 if isinstance(w['p50'],(int,float)) else w['p50']):>20}")
