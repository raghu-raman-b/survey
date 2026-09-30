#!/usr/bin/env python3
"""Draw the inter-rater agreement sample: 10% of the final corpus, stratified by
publication year so the sample mirrors the corpus. Deterministic (fixed seed)."""
import json, csv, os, random, collections

OUT      = '/home/prex_san/Documents/survey/final_corpus'
AGREE    = os.path.join(OUT, 'agreement')
FRACTION = 0.10
SEED     = 20260928          # fixed so the draw is reproducible and auditable

F = json.load(open(os.path.join(OUT, 'final_corpus.json')))
target = round(len(F) * FRACTION)

# ---- proportional allocation across years, largest-remainder for the rounding --
by_year = collections.defaultdict(list)
for r in F: by_year[r['year'] or 'unknown'].append(r)
exact = {y: len(v) * target / len(F) for y, v in by_year.items()}
alloc = {y: int(e) for y, e in exact.items()}
for y in sorted(by_year, key=lambda y: -(exact[y] - alloc[y]))[:target - sum(alloc.values())]:
    alloc[y] += 1

rng = random.Random(SEED)
sample = []
for y in sorted(by_year):
    pool = sorted(by_year[y], key=lambda r: r['cid'])
    sample += rng.sample(pool, alloc[y])
sample.sort(key=lambda r: r['cid'])
# screening order is shuffled so reviewers do not work through the corpus by year
order = list(sample); rng.shuffle(order)
assert len(sample) == target and len({r['cid'] for r in sample}) == target

def ris_lines(r, n):
    L = [f"TY  - {r['type']}"] + [f"AU  - {a}" for a in r['authors']]
    L.append(f"TI  - {r['title']}")
    for tag, key in (('PY', 'year'), ('T2', 'venue'), ('VL', 'volume'), ('IS', 'issue'),
                     ('SP', 'start_page'), ('EP', 'end_page'), ('PB', 'publisher')):
        if r.get(key): L.append(f"{tag}  - {r[key]}")
    if r.get('doi_raw') or r['doi']: L.append(f"DO  - {r.get('doi_raw') or r['doi']}")
    if r['url']:      L.append(f"UR  - {r['url']}")
    if r['abstract']: L.append(f"AB  - {r['abstract']}")
    L += [f"KW  - {k}" for k in r['keywords']]
    L += [f"DB  - {r['source_db']}", f"ID  - C{r['cid']:04d}",
          f"N1  - corpus_id: C{r['cid']:04d}", f"N1  - agreement_sample_item: {n}", "ER  - "]
    return L

with open(os.path.join(AGREE, 'agreement_sample.ris'), 'w', encoding='utf-8') as fh:
    for i, r in enumerate(order, 1):
        fh.write('\n'.join(ris_lines(r, i)) + '\n\n')

with open(os.path.join(AGREE, 'agreement_sample.csv'), 'w', newline='', encoding='utf-8') as fh:
    w = csv.writer(fh)
    w.writerow(['item', 'corpus_id', 'year', 'type', 'doi', 'title', 'venue', 'abstract',
                'reviewer_1', 'reviewer_2', 'reviewer_1_reason', 'reviewer_2_reason'])
    for i, r in enumerate(order, 1):
        w.writerow([i, f"C{r['cid']:04d}", r['year'], r['type'], r.get('doi_raw') or r['doi'],
                    r['title'], r['venue'], r['abstract'], '', '', '', ''])

json.dump({'seed': SEED, 'fraction': FRACTION, 'n_corpus': len(F), 'n_sample': target,
           'allocation_by_year': {y: alloc[y] for y in sorted(alloc)},
           'corpus_ids': [f"C{r['cid']:04d}" for r in sample]},
          open(os.path.join(AGREE, 'agreement_sample_manifest.json'), 'w'), indent=1)

cs = collections.Counter(r['source_db'] for r in sample)
cf = collections.Counter(r['source_db'] for r in F)
ts = collections.Counter(r['type'] for r in sample)
tf = collections.Counter(r['type'] for r in F)
print(f"corpus {len(F)} -> sample {target} ({100*target/len(F):.1f}%)  seed={SEED}")
print("\n  database       sample%   corpus%")
for k in cf: print(f"  {k:<20} {100*cs[k]/target:5.1f}   {100*cf[k]/len(F):5.1f}")
print("\n  type           sample%   corpus%")
for k in tf: print(f"  {k:<20} {100*ts[k]/target:5.1f}   {100*tf[k]/len(F):5.1f}")
