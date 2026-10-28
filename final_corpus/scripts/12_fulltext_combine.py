#!/usr/bin/env python3
"""Combine both screeners' full-text decisions and fill in the PRISMA diagram.

Inputs:  fulltext/fulltext_corpus.json      (from 11_fulltext_corpus.py)
         fulltext/fulltext_<name>.json      one export per screener, from tools/fulltext_screening.html
         criteria.json                      for reason labels and the skim order
Outputs: fulltext/fulltext_log.csv          every paper with its decision and reason
         fulltext/included_studies.json/.csv/.ris   the studies included in the review
         fulltext/fulltext_summary.md       counts for the PRISMA boxes, by screener
         prisma_stats.json ('fulltext')     then reruns 02_report.py to redraw the diagram

Papers with a preset in the corpus file (settled from the retrieval notes, or 4 pages or
fewer) take the preset unless the screener decided them in the tool. Each excluded report is
counted once, under the check it failed (the 'primary' field), so the reasons add up to the
number excluded.

Usage:  python3 12_fulltext_combine.py [file.json ...] [--allow-partial]
--allow-partial writes the summary from whatever is screened so far but leaves the
PRISMA diagram on its provisional numbers.
"""
import json, csv, os, sys, glob, datetime, subprocess, collections

OUT = '/home/prex_san/Documents/survey/final_corpus'
FT  = os.path.join(OUT, 'fulltext')
C   = json.load(open(os.path.join(FT, 'fulltext_corpus.json')))
CRIT = json.load(open(os.path.join(OUT, 'criteria.json')))
recs = {r['id']: r for r in C['records']}
owner = {cid: s for s, ids in C['screeners'].items() for cid in ids}

ALLOW_PARTIAL = '--allow-partial' in sys.argv
paths = [a for a in sys.argv[1:] if not a.startswith('--')] or sorted(
    p for p in glob.glob(os.path.join(FT, 'fulltext_*.json'))
    if os.path.basename(p) != 'fulltext_corpus.json')
if not paths:
    sys.exit(f"No exports found. Save each screener's fulltext_<name>.json into {FT}/ and rerun.")

label = {x['code']: x.get('label', '') for x in CRIT['exclude']}
order = [c for st in CRIT.get('fulltext_skim', {}).get('steps', []) for c in st['codes'] if c.startswith('E')] \
        or [x['code'] for x in CRIT['exclude']]

decisions, problems, loaded = {}, [], []
for p in paths:
    d = json.load(open(p))
    if d.get('kind') != 'fulltext-decisions':
        problems.append(f"{os.path.basename(p)}: not a full-text decisions export, skipped"); continue
    who = d.get('screener', '?')
    loaded.append((os.path.basename(p), who, len(d['decisions'])))
    for x in d['decisions']:
        cid = x['corpus_id']
        if cid not in recs:
            problems.append(f"{cid} in {os.path.basename(p)} is not in the corpus"); continue
        if owner.get(cid) != who:
            problems.append(f"{cid} decided by {who} but assigned to {owner.get(cid)}")
        if cid in decisions and decisions[cid]['decision'] != x['decision']:
            problems.append(f"{cid}: conflicting decisions across files ({decisions[cid]['decision']} vs {x['decision']})")
        if x['decision'] == 'exclude' and not x.get('primary'):
            problems.append(f"{cid}: excluded without a reason")
        decisions[cid] = {**x, 'screener': who}

n_preset = 0
for cid, r in recs.items():
    if cid not in decisions and r.get('preset'):
        p = r['preset']
        decisions[cid] = {'corpus_id': cid, 'decision': p['decision'], 'primary': p.get('primary', ''),
                          'codes': [p['primary']] if p.get('primary') else [], 'note': f"pre-set: {p['reason']}",
                          'screener': owner[cid], 'source': 'preset'}
        n_preset += 1
missing = {s: [c for c in ids if c not in decisions] for s, ids in C['screeners'].items()}
n_missing = sum(len(v) for v in missing.values())

print(f"pre-set from the corpus file: {n_preset}")
print("loaded:")
for f, who, k in loaded:
    print(f"  {f:34s} {who:10s} {k:4d} decisions")
for s, ids in missing.items():
    if ids:
        print(f"  {s}: {len(ids)} of {len(C['screeners'][s])} papers not yet decided")
for pr in problems[:20]:
    print("  ! " + pr)
if problems:
    sys.exit(f"{len(problems)} problem(s) above — fix the exports and rerun.")
complete = n_missing == 0
if not complete and not ALLOW_PARTIAL:
    sys.exit(f"{n_missing} papers still undecided. Finish screening, or pass --allow-partial for an interim summary.")

# ---------------------------------------------------------------- counts
cnt = collections.Counter(x['decision'] for x in decisions.values())
prim = collections.Counter(x['primary'] for x in decisions.values() if x['decision'] == 'exclude')
anyc = collections.Counter(c for x in decisions.values() if x['decision'] == 'exclude' for c in x.get('codes', []))
reasons = [{'code': c, 'label': label.get(c, ''), 'n': prim[c]}
           for c in sorted(prim, key=lambda c: (order.index(c) if c in order else 99, c))]
stats = {
    'sought': len(recs), 'not_retrieved': cnt['not_retrieved'],
    'assessed': cnt['include'] + cnt['exclude'], 'excluded': cnt['exclude'],
    'included': cnt['include'], 'reasons': reasons, 'complete': complete,
    'undecided': n_missing,
    'by_screener': {s: dict(collections.Counter(decisions[c]['decision'] for c in ids if c in decisions))
                    for s, ids in C['screeners'].items()},
    'preset': n_preset,
    'updated': datetime.date.today().isoformat(),
}

# ---------------------------------------------------------------- write
with open(os.path.join(FT, 'fulltext_log.csv'), 'w', newline='', encoding='utf-8') as fh:
    w = csv.writer(fh)
    w.writerow(['corpus_id', 'screener', 'decision', 'reason', 'source', 'note',
                'retrieval_note', 'secs', 'year', 'type', 'doi', 'title'])
    for cid in sorted(recs):
        x, r = decisions.get(cid, {}), recs[cid]
        w.writerow([cid, owner[cid], x.get('decision', 'UNDECIDED'), x.get('primary', ''),
                    x.get('source', 'screener') if x else '', x.get('note', ''), r['retrieval']['note'],
                    x.get('secs', ''), r['year'], r['type'], r['doi'], r['title']])

inc = [cid for cid in sorted(recs) if decisions.get(cid, {}).get('decision') == 'include']
inc_recs = [{**{k: v for k, v in recs[c].items() if k != 'preset'}, 'screener': owner[c]} for c in inc]
json.dump(inc_recs, open(os.path.join(FT, 'included_studies.json'), 'w'), indent=1, ensure_ascii=False)
with open(os.path.join(FT, 'included_studies.csv'), 'w', newline='', encoding='utf-8') as fh:
    w = csv.writer(fh)
    w.writerow(['corpus_id', 'year', 'type', 'doi', 'title', 'authors', 'venue', 'screener'])
    for r in inc_recs:
        w.writerow([r['id'], r['year'], r['type'], r['doi'], r['title'], '; '.join(r['authors']),
                    r['venue'], r['screener']])
with open(os.path.join(FT, 'included_studies.ris'), 'w', encoding='utf-8') as fh:
    for r in inc_recs:
        L = [f"TY  - {r['type']}", f"ID  - {r['id']}", f"TI  - {r['title']}"]
        L += [f"AU  - {a}" for a in r['authors']]
        for tag, key in [('PY', 'year'), ('T2', 'venue'), ('VL', 'volume'), ('IS', 'issue'),
                         ('SP', 'start_page'), ('EP', 'end_page'), ('PB', 'publisher'), ('DO', 'doi'), ('AB', 'abstract')]:
            if r.get(key):
                L.append(f"{tag}  - {r[key]}")
        L += [f"N1  - corpus_id: {r['id']}", "ER  - "]
        fh.write('\n'.join(L) + '\n\n')

md = [f"# Full-text screening summary\n",
      f"**Date:** {datetime.date.today():%d %B %Y}  ",
      f"**Status:** {'complete' if complete else f'INTERIM — {n_missing} papers undecided'}\n",
      "## For the PRISMA flow\n",
      f"- Reports sought for retrieval: **{stats['sought']}**",
      f"- Reports not retrieved: **{stats['not_retrieved']}**",
      f"- Reports assessed for eligibility: **{stats['assessed']}**",
      f"- Reports excluded: **{stats['excluded']}**"]
md += [f"    - {r['code']} {r['label']}: **{r['n']}**" for r in reasons]
md += [f"- Studies included in review: **{stats['included']}**\n",
       "Each excluded report is counted once, under the check it failed. "
       f"{n_preset} papers were pre-set from the retrieval notes or their page count.\n"]
md += ["", "## By screener\n", "| Screener | Assigned | Include | Exclude | Not retrieved | Undecided |",
       "|---|---|---|---|---|---|"]
for s, ids in C['screeners'].items():
    b = stats['by_screener'][s]
    md.append(f"| {s} | {len(ids)} | {b.get('include', 0)} | {b.get('exclude', 0)} | "
              f"{b.get('not_retrieved', 0)} | {len(missing[s])} |")
open(os.path.join(FT, 'fulltext_summary.md'), 'w').write('\n'.join(md) + '\n')

print(f"\nsought {stats['sought']} · not retrieved {stats['not_retrieved']} · assessed {stats['assessed']} · "
      f"excluded {stats['excluded']} · included {stats['included']}")
for r in reasons:
    print(f"  {r['code']:3s} {r['label']:40s} {r['n']}")
print(f"wrote {FT}/fulltext_log.csv, included_studies.*, fulltext_summary.md")

if complete:
    STATS = os.path.join(OUT, 'prisma_stats.json')
    S = json.load(open(STATS)); S['fulltext'] = stats
    json.dump(S, open(STATS, 'w'), indent=1)
    subprocess.run([sys.executable, os.path.join(OUT, 'scripts', '02_report.py')], check=True)
else:
    print("interim run: PRISMA diagram left unchanged")
