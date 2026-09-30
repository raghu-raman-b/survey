#!/usr/bin/env python3
"""Inter-rater agreement.

    python3 07_kappa.py a.json b.json [c.json ...]   # agreement_*.json from the tool
    python3 07_kappa.py agreement_sample.csv         # the two-column sheet
    python3 07_kappa.py                              # defaults to agreement/agreement_sample.csv

Reports raw agreement, Cohen's kappa (two raters) with a 95% CI, Krippendorff's
alpha (any number of raters), the confusion matrix and every disagreement.

The pass/redo threshold is binary kappa >= 0.80 (alpha for three or more raters), with
'maybe' counted as include: the Screening phase only decides include vs exclude, and a
maybe goes to full text just like an include. 0.80 follows McHugh (2012, Biochemia
Medica 22(3):276-282) and Krippendorff's 0.800 for reliable data; the interpretation
bands are McHugh's, not Landis & Koch's.
"""
import csv, os, sys, math, json, glob, collections, itertools, io, datetime

AGREE   = '/home/prex_san/Documents/survey/final_corpus/agreement'
SCREEN  = '/home/prex_san/Documents/survey/final_corpus/screening'
RESULTS = '/home/prex_san/Documents/survey/final_corpus/agreement_results'

# Everything printed also goes into a report under agreement_results/, one file per
# run, so each pilot round keeps its own record.
class Tee:
    def __init__(self, *streams): self.streams = streams
    def write(self, s):
        for st in self.streams: st.write(s)
    def flush(self):
        for st in self.streams: st.flush()
REPORT = io.StringIO()
STARTED = datetime.datetime.now()
sys.stdout = Tee(sys.__stdout__, REPORT)
print(f"Agreement report - {STARTED:%Y-%m-%d %H:%M}")
print(f"command: python3 07_kappa.py {' '.join(sys.argv[1:])}".rstrip() + "\n")
NORM = {'i': 'include', 'include': 'include', 'inc': 'include', '1': 'include', 'keep': 'include',
        'yes': 'include', 'y': 'include', 'true': 'include',
        'e': 'exclude', 'exclude': 'exclude', 'exc': 'exclude', '0': 'exclude', 'discard': 'exclude',
        'no': 'exclude', 'n': 'exclude', 'false': 'exclude',
        'm': 'maybe', 'maybe': 'maybe', '?': 'maybe', 'unsure': 'maybe'}
ORDER = ['include', 'maybe', 'exclude']
THRESHOLD = 0.80       # binary kappa (maybe -> include) needed before Part 2
def norm(v):
    v = (v or '').strip().lower()
    return NORM.get(v) if v else None

# ------------------------------------------------------------------ loading
args = sys.argv[1:]
raters = {}            # name -> {corpus_id: label}
codes  = {}            # name -> {corpus_id: [code, ...]}
titles = {}

if args and all(a.lower().endswith('.json') for a in args):
    if len(args) < 2: sys.exit("Give at least two reviewer files.")
    for p in args:
        d = json.load(open(p))
        name = d.get('reviewer_id') or os.path.basename(p)
        rows = d.get('decisions', d)
        m = {}
        for r in rows:
            lab = norm(r.get('decision'))
            if r.get('corpus_id') and lab:
                m[r['corpus_id']] = lab
                codes.setdefault(name, {})[r['corpus_id']] = [c.upper() for c in (r.get('codes') or [])]
                if r.get('title'): titles.setdefault(r['corpus_id'], r['title'])
        if not m: sys.exit(f"{os.path.basename(p)}: no usable decisions.")
        if name in raters: name = f"{name} ({os.path.basename(p)})"
        raters[name] = m
        print(f"{os.path.basename(p):<44} {name:<16} {len(m):>6,} decisions")
else:
    if not args:
        auto = sorted(glob.glob(os.path.join(SCREEN, 'agreement_*.json')))
        if len(auto) >= 2:
            sys.exit("Found agreement files - rerun naming them:\n  python3 07_kappa.py "
                     + " ".join(os.path.relpath(a) for a in auto))
    path = args[0] if args else os.path.join(AGREE, 'agreement_sample.csv')
    rows = list(csv.DictReader(open(path, encoding='utf-8')))
    cols = [c for c in (rows[0] if rows else {}) if c.startswith('reviewer_') and not c.endswith('_reason')]
    if len(cols) < 2: sys.exit(f"{path}: need at least two reviewer_* columns.")
    for c in cols: raters[c] = {}
    for r in rows:
        cid = r.get('corpus_id') or r.get('item')
        for c in cols:
            lab = norm(r.get(c))
            if lab: raters[c][cid] = lab
        if r.get('title'): titles[cid] = r['title']
    print(f"{os.path.basename(path)}: {len(rows):,} rows, {len(cols)} reviewers")

names = list(raters)
common = sorted(set.intersection(*[set(m) for m in raters.values()]))
print(f"\nrecords screened by all {len(names)} reviewers: {len(common):,}")
if not common:
    sys.exit("\nNo overlap between these reviewers - agreement needs records both of them screened.")

units = [[raters[n][c] for n in names] for c in common]

# ------------------------------------------------------------------ maths
def cohen(pairs, labels):
    n = len(pairs)
    obs = collections.Counter(pairs)
    r1 = collections.Counter(a for a, _ in pairs)
    r2 = collections.Counter(b for _, b in pairs)
    po = sum(obs[(l, l)] for l in labels) / n
    pe = sum((r1[l] / n) * (r2[l] / n) for l in labels)
    k = (po - pe) / (1 - pe) if pe < 1 else float('nan')
    se = math.sqrt(po * (1 - po) / (n * (1 - pe) ** 2)) if pe < 1 else float('nan')
    return k, se, po, pe, obs, r1, r2

def alpha(units):
    """Krippendorff's alpha, nominal metric."""
    o = collections.Counter(); total = 0.0
    for vals in units:
        m = len(vals)
        if m < 2: continue
        for a, b in itertools.permutations(range(m), 2):
            o[(vals[a], vals[b])] += 1 / (m - 1); total += 1 / (m - 1)
    if not total: return None
    nc = collections.Counter()
    for (c, _), v in o.items(): nc[c] += v
    Do = sum(v for (c, d), v in o.items() if c != d)
    De = sum(nc[c] * nc[d] / (total - 1) for c in nc for d in nc if c != d)
    return 1 - Do / De if De else None

def band(k):            # McHugh (2012)
    for lo, lbl in [(.90, 'almost perfect'), (.80, 'strong'), (.60, 'moderate'),
                    (.40, 'weak'), (.21, 'minimal'), (0, 'none')]:
        if k >= lo: return lbl
    return 'worse than chance'

def report(title, units, labels):
    n = len(units)
    agree = sum(1 for u in units if len(set(u)) == 1)
    a = alpha(units)
    print(f"\n{'='*64}\n{title}  (n = {n:,})\n{'='*64}")
    if len(names) == 2:
        pairs = [(u[0], u[1]) for u in units]
        k, se, po, pe, obs, r1, r2 = cohen(pairs, labels)
        w = max(len(l) for l in labels) + 2
        print(f"  {'':3}{'→':<{w}}" + ''.join(f"{l:>{w}}" for l in labels) + f"{'total':>{w}}")
        for x in labels:
            print(f"  {'':3}{x:<{w}}" + ''.join(f"{obs[(x,y)]:>{w}}" for y in labels) + f"{r1[x]:>{w}}")
        print(f"  {'':3}{'total':<{w}}" + ''.join(f"{r2[y]:>{w}}" for y in labels) + f"{n:>{w}}")
        print(f"\n  rows = {names[0]}   columns = {names[1]}")
        print(f"\n  raw agreement       {po:.3f}  ({agree:,}/{n:,})")
        print(f"  expected by chance  {pe:.3f}")
        print(f"  Cohen's kappa       {k:.3f}   [95% CI {k-1.96*se:.3f}, {min(1.0, k+1.96*se):.3f}]")
        print(f"  Krippendorff alpha  {a:.3f}" if a is not None else "  Krippendorff alpha  n/a")
        print(f"  interpretation      {band(k)} (McHugh 2012)")
        stat = ("Cohen's kappa", k, k - 1.96 * se, min(1.0, k + 1.96 * se))
    else:
        print(f"  raw agreement       {agree/n:.3f}  ({agree:,}/{n:,} unanimous)")
        print(f"  Krippendorff alpha  {a:.3f}" if a is not None else "  Krippendorff alpha  n/a")
        print(f"  interpretation      {band(a)} (McHugh bands)" if a is not None else "")
        stat = ("Krippendorff alpha", a, None, None)
    flat = [v for u in units for v in u]
    inc = flat.count('include') / len(flat)
    print(f"  inclusion rate      {inc:.1%}  (mean across reviewers)")
    if inc < 0.10 or inc > 0.90:
        print("  ! one class is rare, so kappa/alpha are unstable here - read the raw")
        print("    agreement and the matrix alongside them.")
    return stat

used = {v for u in units for v in u}
labels = [l for l in ORDER if l in used]
gate = report("Agreement as screened", units, labels)
if 'maybe' in used:
    binary = [['exclude' if v == 'exclude' else 'include' for v in u] for u in units]
    gate = report("Agreement with 'maybe' carried forward to full text  <- threshold",
                  binary, ['include', 'exclude'])

dis = [(c, u) for c, u in zip(common, units) if len(set(u)) > 1 or 'maybe' in u]
if dis:
    print(f"\n{'='*64}\nTo reconcile: {len(dis):,} record(s) - disagreements and maybes\n{'='*64}")
    for c, u in dis[:40]:
        bits = []
        for n, v in zip(names, u):
            cs = codes.get(n, {}).get(c) or []
            bits.append(f"{n}={v}" + (f" [{' '.join(cs)}]" if cs else ""))
        print("  " + c + "  " + "  ".join(bits))
        if titles.get(c): print(f"        {titles[c][:70]}")
    if len(dis) > 40:                   # terminal stops at 40; the report file gets them all
        sys.__stdout__.write(f"  ... and {len(dis)-40:,} more - full list in the report file\n")
        for c, u in dis[40:]:
            bits = []
            for n, v in zip(names, u):
                cs = codes.get(n, {}).get(c) or []
                bits.append(f"{n}={v}" + (f" [{' '.join(cs)}]" if cs else ""))
            REPORT.write("  " + c + "  " + "  ".join(bits) + "\n")
            if titles.get(c): REPORT.write(f"        {titles[c][:70]}\n")

    friction = collections.Counter()
    for c, _u in dis:
        key = tuple((' '.join(codes.get(n, {}).get(c) or []) or '-') for n in names)
        if any(k != '-' for k in key): friction[key] += 1
    if friction:
        print(f"\n  Where the criteria pull apart ({' vs '.join(names)}):")
        for key, k_n in friction.most_common(10):
            print(f"    {k_n:>4}x  " + "  vs  ".join(key))
        print("\n  A pair that keeps recurring is a boundary worth rewording before you")
        print("  screen the rest of the corpus.")
    print("\n  Settle these on the Resolve tab of screening_tool.html.")
else:
    print("\nNo disagreements and no maybes - nothing to reconcile.")

name, val, lo, hi = gate
print(f"\n{'='*64}\nThreshold: binary {name} >= {THRESHOLD:.2f}\n{'='*64}")
if val is None or math.isnan(val):
    print("  Not computable - every rating falls in one category. Read the raw agreement.")
else:
    ci = f"  [95% CI {lo:.3f}, {hi:.3f}]" if lo is not None else ""
    if val >= THRESHOLD:
        print(f"  {val:.3f}{ci}  PASS - reconcile on the Resolve tab, then go to Part 2.")
    else:
        print(f"  {val:.3f}{ci}  REDO - reword the criteria that pull apart, change SEED in")
        print("  06_agreement_sample.py, redraw, and screen the new sample.")
print()

sys.stdout = sys.__stdout__
os.makedirs(RESULTS, exist_ok=True)
out = os.path.join(RESULTS, f"agreement_report_{STARTED:%Y%m%d_%H%M%S}.txt")
with open(out, 'w', encoding='utf-8') as f:
    f.write(REPORT.getvalue())
rel = os.path.relpath(out)
print(f"report written to {out if rel.startswith('..') else rel}")
