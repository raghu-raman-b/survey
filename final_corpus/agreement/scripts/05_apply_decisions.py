#!/usr/bin/env python3
"""Apply the manual screening decisions to the corpus.

Each entry in MERGES is (pair_id, surviving_cid, absorbed_cid, rationale), where pair_id
is the row in the screening worksheet. Everything not listed here was screened and kept as
two separate records.
"""
import json, csv, os, collections, datetime

OUT = '/home/prex_san/Documents/survey/final_corpus'

MERGES = [
    ('P001', 642, 641, 'Retracted article and its retraction notice; identical abstract. '
                'Kept the retraction notice, which is the authoritative later record. '
                'The work is retracted and should be excluded at screening.'),
    ('P002', 81,  42,  'IEEE Std 1589-2020 and its approved draft (P1589/D3); identical abstract. Kept the published standard.'),
    ('P003', 244, 170, 'ArtsIT 2023 paper states it is an extended version of the ACM MM 2022 abstract. Kept the full paper.'),
    ('P005', 199, 90,  'IEEE TCE 2022 journal extension of the ICCE 2020 conference paper. Kept the journal article.'),
    ('P006', 1863,1725,'IEEE VR 2026 full paper and its VRW demo abstract. Kept the full paper.'),
    ('P007', 1963,1209,'IEEE TVCG 2026 journal extension of the VRW 2025 poster. Kept the journal article.'),
    ('P008', 2120,2119,'SIGGRAPH 2026 Immersive Pavilion paper and its IEEE VRW demo abstract. Kept the full paper.'),
]
KEPT_BOTH_NOTE = {
    1264: 'NavAI (P004): kept separate from C2003 — author lists differ substantially.',
}

F = json.load(open(os.path.join(OUT, 'final_corpus.json')))
by_cid = {r['cid']: r for r in F}
# Idempotent: a merge whose absorbed record is already gone has been applied before.
PENDING = []
for pid, surv, ab, why in MERGES:
    if surv not in by_cid:
        raise SystemExit(f"{pid}: surviving record C{surv:04d} missing - rerun 01_dedupe.py first")
    if ab in by_cid:
        PENDING.append((pid, surv, ab, why))
if not PENDING:
    print('all merges already applied; nothing to do')

FILL = ('doi', 'doi_raw', 'abstract', 'venue', 'year', 'volume', 'issue',
        'start_page', 'end_page', 'publisher', 'url', 'issn', 'isbn')
absorbed = {}
for pid, surv, ab, why in PENDING:
    S, Ab = by_cid[surv], by_cid[ab]
    for fld in FILL:
        if not S.get(fld) and Ab.get(fld): S[fld] = Ab[fld]
    if not S['authors'] and Ab['authors']: S['authors'] = Ab['authors']
    if len(Ab.get('keywords', [])) > len(S.get('keywords', [])): S['keywords'] = Ab['keywords']
    S['merged_idxs'] = sorted(set(S['merged_idxs']) | set(Ab['merged_idxs']))
    S['found_in'] = sorted(set(S['found_in']) | set(Ab['found_in']))
    S['n_in_cluster'] = len(S['merged_idxs'])
    S['merge_note'] = f'{pid}: {why}'
    S['absorbed_cids'] = sorted(S.get('absorbed_cids', []) + [ab] + Ab.get('absorbed_cids', []))
    S.setdefault('absorbed_titles', {})[str(ab)] = Ab['title']
    absorbed[ab] = surv
for cid, note in KEPT_BOTH_NOTE.items():
    by_cid[cid]['screening_note'] = note

final = [r for r in F if r['cid'] not in absorbed]
final.sort(key=lambda r: (r['year'] or '0000', r['ntitle']))
print(f"{len(F)} -> {len(final)} records ({len(absorbed)} merged away)")

def ris_lines(r):
    L = [f"TY  - {r['type']}"]
    L += [f"AU  - {a}" for a in r['authors']]
    L.append(f"TI  - {r['title']}")
    if r['year']:      L.append(f"PY  - {r['year']}")
    if r['venue']:     L.append(f"T2  - {r['venue']}")
    if r['volume']:    L.append(f"VL  - {r['volume']}")
    if r['issue']:     L.append(f"IS  - {r['issue']}")
    if r['start_page']:L.append(f"SP  - {r['start_page']}")
    if r['end_page']:  L.append(f"EP  - {r['end_page']}")
    if r['publisher']: L.append(f"PB  - {r['publisher']}")
    if r.get('doi_raw') or r['doi']: L.append(f"DO  - {r.get('doi_raw') or r['doi']}")
    if r['issn']:      L.append(f"SN  - {r['issn']}")
    if r['url']:       L.append(f"UR  - {r['url']}")
    if r['abstract']:  L.append(f"AB  - {r['abstract']}")
    for k in r['keywords']: L.append(f"KW  - {k}")
    L.append(f"DB  - {r['source_db']}")
    L.append(f"ID  - C{r['cid']:04d}")
    L.append(f"N1  - corpus_id: C{r['cid']:04d}")
    L.append(f"N1  - found_in: {'; '.join(r['found_in'])}")
    L.append(f"N1  - source_records_merged: {r['n_in_cluster']}")
    if r.get('absorbed_cids'):
        L.append(f"N1  - absorbed: {', '.join('C%04d' % c for c in r['absorbed_cids'])}")
    L.append("ER  - ")
    return L

with open(os.path.join(OUT, 'final_corpus.ris'), 'w', encoding='utf-8') as fh:
    for r in final:
        fh.write('\n'.join(ris_lines(r)) + '\n\n')
json.dump(final, open(os.path.join(OUT, 'final_corpus.json'), 'w'),
          ensure_ascii=False, indent=1, default=str)

# ---- refresh the all-records catalogue with the post-screening disposition ---
cid_of, keep_idx_of = {}, {}
for r in final:
    for i in r['merged_idxs']:
        cid_of[i] = r['cid']
    keep_idx_of[r['cid']] = r['idx']
rows = list(csv.DictReader(open(os.path.join(OUT, 'catalog_all_records.csv'))))
with open(os.path.join(OUT, 'catalog_all_records.csv'), 'w', newline='', encoding='utf-8') as fh:
    w = csv.writer(fh)
    w.writerow(['source_record_id', 'source_db', 'source_file', 'status', 'corpus_id',
                'cluster_size', 'type', 'year', 'doi', 'title', 'authors', 'venue'])
    for row in rows:
        i = int(row['source_record_id'][1:])
        cid = cid_of.get(i)
        rec = next(r for r in final if r['cid'] == cid)
        w.writerow([row['source_record_id'], row['source_db'], row['source_file'],
                    'retained' if i == keep_idx_of[cid] else 'duplicate-removed',
                    f"C{cid:04d}", rec['n_in_cluster'], row['type'], row['year'],
                    row['doi'], row['title'], row['authors'], row['venue']])

# ---------------------------------------------------- stats + decisions record
TOT = len(rows)
stats = json.load(open(os.path.join(OUT, 'prisma_stats.json')))
stats.update({
    'n_identified': TOT, 'n_unique': len(final), 'n_removed': TOT - len(final),
    'retained_by_db': dict(collections.Counter(r['source_db'] for r in final)),
    'removed_by_db': dict(collections.Counter(
        row['source_db'] for row in csv.DictReader(open(os.path.join(OUT, 'catalog_all_records.csv')))
        if row['status'] == 'duplicate-removed')),
    'found_in_combos': {' + '.join(k): v for k, v in sorted(
        collections.Counter(tuple(r['found_in']) for r in final).items(), key=lambda x: -x[1])},
    'cluster_sizes': dict(sorted(collections.Counter(r['n_in_cluster'] for r in final).items())),
    'types': dict(collections.Counter(r['type'] for r in final).most_common()),
    'years': dict(sorted(collections.Counter(r['year'] for r in final).items())),
    'top_venues': collections.Counter(r['venue'] for r in final if r['venue']).most_common(20),
    'missing_doi': sum(1 for r in final if not r['doi']),
    'missing_abstract': sum(1 for r in final if not r['abstract']),
    'missing_year': sum(1 for r in final if not r['year']),
    'n_manual_merges': len(MERGES),
    'run_date': datetime.date.today().isoformat(),
})
for k in ('removed_by_method', 'within_db_removed', 'n_flagged', 'n_review'):
    stats.pop(k, None)
json.dump(stats, open(os.path.join(OUT, 'prisma_stats.json'), 'w'), indent=1, ensure_ascii=False)

N_REVIEWED = 91          # candidate pairs adjudicated in the screening round
D = []; A = D.append
A("# Manual duplicate screening — decisions\n")
A(f"**Date:** {datetime.date.today().strftime('%d %B %Y')}  ")
A(f"**Pairs reviewed:** {N_REVIEWED}  ")
A(f"**Pairs merged:** {len(MERGES)}  ")
A(f"**Pairs kept as separate records:** {N_REVIEWED - len(MERGES)}\n")
A("Candidate pairs were surfaced by title similarity and adjudicated by hand against titles,")
A("DOIs, venues, authors and abstracts.\n")
A("## Merged\n")
A("| Pair | Kept | Dropped | Reason |")
A("|---|---|---|---|")
for pid, surv, ab, why in MERGES:
    dropped = (by_cid[ab]['title'] if ab in by_cid
               else by_cid[surv].get('absorbed_titles', {}).get(str(ab), ''))
    A(f"| {pid} | `C{surv:04d}` {by_cid[surv]['title'][:58]} | `C{ab:04d}` {dropped[:58]} | {why} |")
A("")
A("## Kept as separate records\n")
A(f"The remaining {N_REVIEWED - len(MERGES)} pairs were judged to be distinct studies. The great majority")
A("share only topic phrasing (for example *\"Generative AI and Augmented Reality for X\"*). Notable calls:\n")
for cid, note in KEPT_BOTH_NOTE.items(): A(f"- {note}")
A("- All pairs graded *unclear* were resolved in favour of keeping both records.\n")
A("Retired identifiers (merged away, never reused): " +
  ", ".join(f"`C{a:04d}`" for _, _s, a, _w in sorted(MERGES, key=lambda x: x[2])) + ".\n")
open(os.path.join(OUT, 'screening_decisions.md'), 'w').write('\n'.join(D))
print('wrote screening_decisions.md; final corpus =', len(final))
