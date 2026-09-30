#!/usr/bin/env python3
"""Split the records NOT in the agreement sample between two screeners.

The agreement sample is double-screened by both reviewers and adjudicated
separately; everything else is screened once, by one reviewer each. Output is
plain RIS, loadable straight into screening_tool.html.
"""
import json, csv, os, random, collections

OUT      = '/home/prex_san/Documents/survey/final_corpus'
AGREE    = os.path.join(OUT, 'agreement')
SCREEN   = os.path.join(OUT, 'screening')
SCREENERS = ['screener_1', 'screener_2']
SEED     = 20260928

os.makedirs(SCREEN, exist_ok=True)
F = json.load(open(os.path.join(OUT, 'final_corpus.json')))
sample_ids = set(json.load(open(os.path.join(AGREE, 'agreement_sample_manifest.json')))['corpus_ids'])

remaining = [r for r in F if f"C{r['cid']:04d}" not in sample_ids]
assert len(remaining) == len(F) - len(sample_ids), 'agreement sample ids do not match the corpus'

# stratify by year so each screener sees the same shape of corpus
by_year = collections.defaultdict(list)
for r in remaining: by_year[r['year'] or 'unknown'].append(r)
rng = random.Random(SEED)
parts = {s: [] for s in SCREENERS}
for y in sorted(by_year):
    pool = sorted(by_year[y], key=lambda r: r['cid'])
    rng.shuffle(pool)
    for i, rec in enumerate(pool):
        parts[SCREENERS[i % len(SCREENERS)]].append(rec)
for s in parts: parts[s].sort(key=lambda r: r['cid'])

def ris_lines(r):
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
          f"N1  - corpus_id: C{r['cid']:04d}", "ER  - "]
    return L

for s, recs in parts.items():
    with open(os.path.join(SCREEN, f'{s}.ris'), 'w', encoding='utf-8') as fh:
        for r in recs: fh.write('\n'.join(ris_lines(r)) + '\n\n')
    with open(os.path.join(SCREEN, f'{s}.csv'), 'w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh); w.writerow(['corpus_id', 'year', 'type', 'doi', 'title', 'venue'])
        for r in recs:
            w.writerow([f"C{r['cid']:04d}", r['year'], r['type'],
                        r.get('doi_raw') or r['doi'], r['title'], r['venue']])

json.dump({'seed': SEED, 'corpus_size': len(F), 'agreement_sample': len(sample_ids),
           'remaining': len(remaining), 'screeners': SCREENERS,
           'assignment': {s: [f"C{r['cid']:04d}" for r in recs] for s, recs in parts.items()}},
          open(os.path.join(SCREEN, 'split_manifest.json'), 'w'), indent=1)

ids = [f"C{r['cid']:04d}" for recs in parts.values() for r in recs]
assert len(ids) == len(set(ids)) == len(remaining), 'split lost or duplicated records'
print(f"corpus {len(F)}  =  agreement sample {len(sample_ids)}  +  remaining {len(remaining)}")
for s, recs in parts.items():
    yrs = collections.Counter(r['year'] for r in recs)
    print(f"  {s}: {len(recs)} records   {min(yrs)}–{max(yrs)}")
print(f"\nwritten to {SCREEN}/")
