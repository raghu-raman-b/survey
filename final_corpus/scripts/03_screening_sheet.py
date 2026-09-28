#!/usr/bin/env python3
"""Build duplicate_screening.md: every cross-entry near-duplicate pair left in the
corpus, ordered so the real decisions come first. Reads the scratch dump of all
source records plus final_corpus.json; writes the worksheet and its index."""
import json, difflib, collections, re, datetime, os

SCRATCH = os.environ.get('SURVEY_SCRATCH',
    '/tmp/claude-1000/-home-prex-san-Documents-survey/a919e6dd-89b8-4e22-b85f-0eb7120bc154/scratchpad')
OUT = '/home/prex_san/Documents/survey/final_corpus'

R = json.load(open(os.path.join(SCRATCH, '_all_source_records.json')))
for r in R: r['tok'] = set(r['tokens'])
F = json.load(open(os.path.join(OUT, 'final_corpus.json')))
root_of = {i: r['cid'] for r in F for i in r['merged_idxs']}
canon = {r['cid']: r for r in F}

inv = collections.defaultdict(list)
for r in R:
    for t in r['tok']: inv[t].append(r['idx'])
COMMON = {t for t, v in inv.items() if len(v) > 400}

def precolon(t):
    h = t.split(':')[0].strip()
    return h if 0 < len(h) <= 22 and ' ' not in h else ''
def absnorm(a):
    return re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9 ]+', ' ', (a or '').lower())).strip()

best = {}
for r in R:
    toks = r['tok'] - COMMON
    if len(toks) < 2: continue
    cand = collections.Counter()
    for t in toks:
        if len(inv[t]) > 400: continue
        for j in inv[t]:
            if j != r['idx']: cand[j] += 1
    for j, c in cand.items():
        if c < 2: continue
        ca, cb = root_of[r['idx']], root_of[j]
        if ca == cb: continue
        key = tuple(sorted((ca, cb)))
        if key in best: continue
        A, B = canon[key[0]], canon[key[1]]
        jac = len(set(A['tokens']) & set(B['tokens'])) / max(1, len(set(A['tokens']) | set(B['tokens'])))
        ratio = difflib.SequenceMatcher(None, A['ntitle'], B['ntitle']).ratio()
        pa, pb = precolon(A['title']), precolon(B['title'])
        same_sys = bool(pa) and pa.lower() == pb.lower()
        if ratio >= 0.65 or (same_sys and jac >= 0.45):
            na, nb = absnorm(A['abstract']), absnorm(B['abstract'])
            asim = difflib.SequenceMatcher(None, na[:3000], nb[:3000]).ratio() if (na and nb) else None
            best[key] = dict(ratio=round(ratio, 3), jac=round(jac, 3), same_sys=same_sys,
                             asim=(round(asim, 3) if asim is not None else None), A=A, B=B)

BANDS = [('ALMOST CERTAIN DUPLICATE', 'abstracts match — merge unless you spot a reason not to'),
         ('LIKELY SAME WORK',         'extended version, demo abstract, or conference→journal pair'),
         ('UNCLEAR',                  'needs a real look'),
         ('PROBABLY DISTINCT',        'different studies that share title phrasing — probably keep both')]
ORDER = {b: i for i, (b, _) in enumerate(BANDS)}

def band(v):
    a = v['asim']
    if a is not None and a >= 0.90: return 'ALMOST CERTAIN DUPLICATE'
    if a is not None and a >= 0.60: return 'LIKELY SAME WORK'
    if v['ratio'] >= 0.85 or v['same_sys']: return 'LIKELY SAME WORK'
    if a is not None and a < 0.35: return 'PROBABLY DISTINCT'
    return 'UNCLEAR'

def score(v):
    return (v['asim'] or 0) * 0.6 + v['ratio'] * 0.4

pairs = sorted(best.values(), key=lambda v: (ORDER[band(v)], -score(v)))
counts = collections.Counter(band(v) for v in pairs)
TODAY = datetime.date.today()

L = []; A = L.append
A("# Duplicate screening worksheet\n")
A(f"**Generated:** {TODAY.strftime('%d %B %Y')}  ")
A(f"**Pairs to decide:** {len(pairs)}  ")
A(f"**Corpus:** `final_corpus.ris` ({len(F):,} records after automatic DOI/title deduplication)\n")
A("## How to use this\n")
A("Every pair below is currently **two separate records** in the corpus. They were too similar to")
A("ignore but not similar enough to merge automatically.\n")
A("For each pair, decide: *are these two reports of the same study, or two different studies?*\n")
A("- **Reply with the IDs you want to KEEP AS TWO SEPARATE RECORDS** — e.g. `keep P004, P011, P023`.")
A("- **Every pair you do not list gets merged**: the less complete record is dropped and the corpus")
A("  shrinks by one per merged pair.\n")
A("`Title sim.` and `Abstract sim.` are 0–1 string-similarity scores. **Abstract similarity is the")
A("one to trust** — above ~0.90 the two records are near-certainly the same paper; below ~0.35 they")
A("are near-certainly different. Title similarity alone is noisy here because so many papers share")
A("phrasing like *\"Generative AI and Augmented Reality for X\"*.\n")
A("Pairs are grouped by verdict band, hardest decisions first. The last band is 82 pairs that only")
A("share topic wording — skim it, it is mostly confirmation.\n")
A("| Verdict band | Pairs | What it means |")
A("|---|---|---|")
for b, hint in BANDS:
    if counts.get(b): A(f"| **{b}** | {counts[b]} | {hint} |")
A("")

cur = None
for i, v in enumerate(pairs, 1):
    b = band(v)
    if b != cur:
        A(f"\n---\n\n# {b}\n"); cur = b
    a, bb = v['A'], v['B']
    A(f"## P{i:03d} · C{a['cid']:04d} vs C{bb['cid']:04d}\n")
    asim = 'n/a (abstract missing)' if v['asim'] is None else f"{v['asim']:.3f}"
    A(f"**Title sim.** {v['ratio']:.3f}  ·  **Abstract sim.** {asim}" +
      ("  ·  **same system/acronym name**" if v['same_sys'] else "") + "\n")
    for tag, rec in (('A', a), ('B', bb)):
        A(f"**{tag} — `C{rec['cid']:04d}`** · {rec['title']}\n")
        meta = [rec['year']] + ([rec['venue']] if rec['venue'] else []) + [rec['source_db']]
        A(f"*{'  ·  '.join(meta)}*  ")
        A(f"DOI: `{rec.get('doi_raw') or rec['doi'] or '— none —'}`  ")
        if rec['authors']:
            au = '; '.join(rec['authors'][:6]) + (' et al.' if len(rec['authors']) > 6 else '')
            A(f"Authors: {au}")
        A("")
        if tag == 'B' and v['asim'] is not None and v['asim'] >= 0.97:
            A("> _Abstract is essentially identical to A._\n")
        else:
            A(f"> {rec['abstract'] or '_(no abstract in the export)_'}\n")
    A(f"**Decision:** ☐ keep both → list `P{i:03d}`   ☐ merge → do nothing\n")

A("\n---\n")
A("## Reply template\n")
A("```")
A("keep P0xx, P0yy, P0zz")
A("```")
A("Everything not listed gets merged.\n")

open(os.path.join(OUT, 'duplicate_screening.md'), 'w').write('\n'.join(L))
json.dump({f"P{i:03d}": {'a': v['A']['cid'], 'b': v['B']['cid'], 'band': band(v),
                         'title_sim': v['ratio'], 'abstract_sim': v['asim']}
           for i, v in enumerate(pairs, 1)},
          open(os.path.join(OUT, 'duplicate_screening_index.json'), 'w'), indent=1)
print(f"{len(pairs)} pairs ->", dict(counts))
