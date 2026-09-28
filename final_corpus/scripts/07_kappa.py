#!/usr/bin/env python3
"""Inter-rater agreement.

    python3 07_kappa.py a.json b.json [c.json ...]   # agreement_*.json from the tool
    python3 07_kappa.py agreement_sample.csv         # the two-column sheet
    python3 07_kappa.py                              # defaults to agreement/agreement_sample.csv

Reports raw agreement, Cohen's kappa (two raters) with a 95% CI, Krippendorff's
alpha (any number of raters), the confusion matrix and every disagreement.
"""
import csv, os, sys, math, json, glob, collections, itertools

AGREE  = '/home/prex_san/Documents/survey/final_corpus/agreement'
SCREEN = '/home/prex_san/Documents/survey/final_corpus/screening'
NORM = {'i': 'include', 'include': 'include', 'inc': 'include', '1': 'include', 'keep': 'include',
        'yes': 'include', 'y': 'include', 'true': 'include',
        'e': 'exclude', 'exclude': 'exclude', 'exc': 'exclude', '0': 'exclude', 'discard': 'exclude',
        'no': 'exclude', 'n': 'exclude', 'false': 'exclude',
        'm': 'maybe', 'maybe': 'maybe', '?': 'maybe', 'unsure': 'maybe'}
ORDER = ['include', 'maybe', 'exclude']
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

def band(k):
    for lo, lbl in [(.81, 'almost perfect'), (.61, 'substantial'), (.41, 'moderate'),
                    (.21, 'fair'), (0, 'slight')]:
        if k >= lo: return lbl
    return 'poor (worse than chance)'

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
        print(f"  interpretation      {band(k)} (Landis & Koch)")
    else:
        print(f"  raw agreement       {agree/n:.3f}  ({agree:,}/{n:,} unanimous)")
        print(f"  Krippendorff alpha  {a:.3f}" if a is not None else "  Krippendorff alpha  n/a")
        print(f"  interpretation      {band(a)} (Landis & Koch bands)" if a is not None else "")
    flat = [v for u in units for v in u]
    inc = flat.count('include') / len(flat)
    print(f"  inclusion rate      {inc:.1%}  (mean across reviewers)")
    if inc < 0.10 or inc > 0.90:
        print("  ! one class is rare, so kappa/alpha are unstable here - read the raw")
        print("    agreement and the matrix alongside them.")

used = {v for u in units for v in u}
labels = [l for l in ORDER if l in used]
report("Agreement as screened", units, labels)
if 'maybe' in used:
    binary = [['exclude' if v == 'exclude' else 'include' for v in u] for u in units]
    report("Agreement with 'maybe' carried forward to full text", binary, ['include', 'exclude'])

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
    if len(dis) > 40: print(f"  ... and {len(dis)-40:,} more")

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
print()
