#!/usr/bin/env python3
"""Combine the screening outputs into the final study corpus.

Inputs (from screening_tool.html, placed in screening/ unless given as arguments):
  screened_articles_<name>.json   one per screener, for their half of the corpus
  adjudicated_screened_sample.json  the reconciled agreement sample

Output (written to study_corpus/):
  study_corpus.ris / .json / .csv   the included records - what the review studies
  screening_log.csv                 every corpus record with its decision and who made it
  screening_summary.md              counts for the PRISMA screening boxes

Usage:  python3 09_combine.py [file.json ...] [--allow-partial]

By default every record in the corpus must have a decision; --allow-partial writes
the study corpus from whatever has been screened so far (useful mid-way, not final).
"""
import json, csv, os, sys, glob, collections, datetime

OUT    = '/home/prex_san/Documents/survey/final_corpus'
SCREEN = os.path.join(OUT, 'screening')
STUDY  = os.path.join(OUT, 'study_corpus')

F = json.load(open(os.path.join(OUT, 'final_corpus.json')))
by_id = {f"C{r['cid']:04d}": r for r in F}

ALLOW_PARTIAL = '--allow-partial' in sys.argv
argv = [a for a in sys.argv[1:] if not a.startswith('--')]
paths = argv or sorted(glob.glob(os.path.join(SCREEN, '*.json')))
# agreement_*.json holds each reviewer's raw calls on the sample; the adjudicated file
# supersedes them, so they are never ingested here.
SKIP = ('split_manifest.json',)
skipped = [p for p in paths if os.path.basename(p).startswith('agreement_')
           or os.path.basename(p) in SKIP]
paths = [p for p in paths if p not in skipped]
if not paths:
    sys.exit(f"No screening files found.\nExport them from screening_tool.html into {SCREEN}/ "
             f"(screened_articles_<name>.json, adjudicated_screened_sample.json), then rerun.")

# ---------------------------------------------------------------- ingest
decisions = {}                      # corpus_id -> {decision, source, reviewer, reason}
conflicts, unknown, loaded = [], [], []

CRIT = {}
_cp = os.path.join(OUT, 'criteria.json')
if os.path.exists(_cp):
    _c = json.load(open(_cp))
    for grp in ('include', 'exclude'):
        for x in _c.get(grp, []):
            CRIT[str(x['code']).upper()] = x.get('label', '')

def put(cid, decision, source, reviewer, reason, codes=(), authoritative=False):
    if cid not in by_id:
        unknown.append((cid, source)); return
    prev = decisions.get(cid)
    if prev and prev['decision'] != decision:
        # adjudication always wins over a single screener's call
        if authoritative and not prev.get('authoritative'):
            pass
        elif prev.get('authoritative') and not authoritative:
            return
        else:
            conflicts.append((cid, prev['source'], prev['decision'], source, decision))
            return
    decisions[cid] = {'decision': decision, 'source': source, 'reviewer': reviewer,
                      'reason': reason or '', 'codes': [c.upper() for c in (codes or [])],
                      'authoritative': authoritative}

for p in paths:
    try: data = json.load(open(p))
    except Exception as e: sys.exit(f"{os.path.basename(p)}: not readable JSON ({e})")
    name, kind = os.path.basename(p), data.get('kind')
    if kind == 'resolution' or 'records' in data and 'agreed' in data:
        for r in data.get('records', []):
            put(r['corpus_id'], r['final'], name, '+'.join(data.get('reviewers', [])) or 'adjudicated',
                r.get('reason', ''), r.get('codes', ()), authoritative=True)
        for r in data.get('agreed', []):
            put(r['corpus_id'], r['final'], name, '+'.join(data.get('reviewers', [])) or 'adjudicated',
                '', r.get('codes', ()), authoritative=True)
        loaded.append((name, 'adjudicated sample',
                       len(data.get('records', [])) + len(data.get('agreed', []))))
    elif kind == 'decisions' or 'decisions' in data:
        rid = data.get('reviewer_id', name)
        rows = data['decisions']
        for d in rows:
            put(d['corpus_id'], d['decision'], name, rid, d.get('reason', ''), d.get('codes', ()))
        loaded.append((name, f"screener {rid}", len(rows)))
    else:
        sys.exit(f"{name}: unrecognised file - expected a decisions or resolution export.")

# ---------------------------------------------------------------- checks
missing  = [cid for cid in by_id if cid not in decisions]
maybes   = [cid for cid, d in decisions.items() if d['decision'] == 'maybe']
included = sorted([cid for cid, d in decisions.items() if d['decision'] == 'include'])
excluded = [cid for cid, d in decisions.items() if d['decision'] == 'exclude']

for p in skipped:
    b = os.path.basename(p)
    if b.startswith('agreement_'):
        print(f"  skipping {b} - superseded by the adjudicated sample")
print(f"corpus              {len(by_id):>6,}")
for name, role, n in loaded: print(f"  {name:<44} {role:<22} {n:>6,}")
print(f"\nscreened            {len(decisions):>6,}")
print(f"  include           {len(included):>6,}")
print(f"  exclude           {len(excluded):>6,}")
if maybes:    print(f"  maybe (UNSETTLED) {len(maybes):>6,}")
if missing:   print(f"not screened        {len(missing):>6,}")
if conflicts: print(f"CONFLICTS           {len(conflicts):>6,}")
if unknown:   print(f"unknown corpus ids  {len(unknown):>6,}")

blocking = []
if maybes:    blocking.append(f"{len(maybes)} record(s) still marked 'maybe' - reconcile them on the Resolve tab")
if conflicts: blocking.append(f"{len(conflicts)} record(s) given different decisions by different files")
if missing and not ALLOW_PARTIAL:
    blocking.append(f"{len(missing)} record(s) have no decision - a screening file is missing or "
                    f"incomplete. Pass --allow-partial to build the study corpus anyway.")
if unknown:
    blocking.append(f"{len(unknown)} decision(s) reference ids that are not in this corpus - "
                    f"the screening files may come from a different corpus version.")
if blocking:
    print()
    for b in blocking: print("  !", b)
    for cid, s1, d1, s2, d2 in conflicts[:10]:
        print(f"    {cid}: {d1} ({s1})  vs  {d2} ({s2})")
    for cid in maybes[:10]:
        print(f"    {cid}: maybe - {by_id[cid]['title'][:66]}")
    for cid in missing[:10] if (missing and not ALLOW_PARTIAL) else []:
        print(f"    {cid}: no decision - {by_id[cid]['title'][:60]}")
    for cid, src in unknown[:10]:
        print(f"    {cid}: not in corpus (from {src})")
    sys.exit("\nNothing written. Resolve the above, then rerun.")

# ---------------------------------------------------------------- write
os.makedirs(STUDY, exist_ok=True)
recs = [by_id[cid] for cid in included]
recs.sort(key=lambda r: (r['year'] or '0000', r['ntitle']))

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
    cid = f"C{r['cid']:04d}"
    L += [f"DB  - {r['source_db']}", f"ID  - {cid}", f"N1  - corpus_id: {cid}",
          f"N1  - found_in: {'; '.join(r['found_in'])}",
          f"N1  - screened_by: {decisions[cid]['reviewer']}", "ER  - "]
    return L

with open(os.path.join(STUDY, 'study_corpus.ris'), 'w', encoding='utf-8') as fh:
    for r in recs: fh.write('\n'.join(ris_lines(r)) + '\n\n')
json.dump(recs, open(os.path.join(STUDY, 'study_corpus.json'), 'w'),
          ensure_ascii=False, indent=1, default=str)
with open(os.path.join(STUDY, 'study_corpus.csv'), 'w', newline='', encoding='utf-8') as fh:
    w = csv.writer(fh); w.writerow(['corpus_id', 'year', 'type', 'doi', 'title', 'authors', 'venue', 'screened_by'])
    for r in recs:
        cid = f"C{r['cid']:04d}"
        w.writerow([cid, r['year'], r['type'], r.get('doi_raw') or r['doi'], r['title'],
                    '; '.join(r['authors']), r['venue'], decisions[cid]['reviewer']])
with open(os.path.join(STUDY, 'screening_log.csv'), 'w', newline='', encoding='utf-8') as fh:
    w = csv.writer(fh)
    w.writerow(['corpus_id', 'decision', 'codes', 'reviewer', 'source_file', 'reason', 'year', 'title'])
    for cid in sorted(decisions):
        d, r = decisions[cid], by_id[cid]
        w.writerow([cid, d['decision'], ' '.join(d['codes']), d['reviewer'], d['source'],
                    d['reason'], r['year'], r['title']])

# ------------------------------------------------- reason-code tallies
exc_codes = collections.Counter(c for cid in excluded for c in decisions[cid]['codes'] if c.startswith('E'))
inc_codes = collections.Counter(c for cid in included for c in decisions[cid]['codes'] if c.startswith('I'))
uncoded_exc = sum(1 for cid in excluded if not any(c.startswith('E') for c in decisions[cid]['codes']))
if exc_codes or inc_codes:
    with open(os.path.join(STUDY, 'exclusion_reasons.csv'), 'w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh); w.writerow(['code', 'label', 'decision', 'records', 'share_of_decision'])
        for code, n_ in exc_codes.most_common():
            w.writerow([code, CRIT.get(code, ''), 'exclude', n_, f"{100*n_/len(excluded):.1f}%"])
        for code, n_ in inc_codes.most_common():
            w.writerow([code, CRIT.get(code, ''), 'include', n_, f"{100*n_/len(included):.1f}%"])
    print(f"\nreason codes: {len(exc_codes)} exclude, {len(inc_codes)} include"
          + (f"  ({uncoded_exc:,} exclusions uncoded)" if uncoded_exc else ""))

TODAY = datetime.date.today()
by_rev = collections.Counter(d['reviewer'] for d in decisions.values())
inc_by_rev = collections.Counter(decisions[c]['reviewer'] for c in included)
yrs = collections.Counter(r['year'] for r in recs)
types = collections.Counter(r['type'] for r in recs)
TL = {'CONF': 'Conference paper', 'JOUR': 'Journal article', 'CHAP': 'Book chapter',
      'BOOK': 'Book', 'STD': 'Standard'}
M = []; A = M.append
A("# Screening summary\n")
A(f"**Date:** {TODAY.strftime('%d %B %Y')}  ")
A(f"**Records screened:** {len(decisions):,}  ")
A(f"**Included:** {len(included):,}  ")
A(f"**Excluded:** {len(excluded):,}\n")
A("## Sources\n")
A("| File | Role | Records |")
A("|---|---|---|")
for name, role, n in loaded: A(f"| `{name}` | {role} | {n:,} |")
A("")
A("## By reviewer\n")
A("| Reviewer | Screened | Included | Inclusion rate |")
A("|---|---|---|---|")
for rev in sorted(by_rev):
    A(f"| {rev} | {by_rev[rev]:,} | {inc_by_rev[rev]:,} | {100*inc_by_rev[rev]/by_rev[rev]:.1f}% |")
A(f"| **Total** | **{len(decisions):,}** | **{len(included):,}** | **{100*len(included)/len(decisions):.1f}%** |")
A("")
A("## For the PRISMA flow\n")
A(f"- Records screened: **{len(decisions):,}**")
A(f"- Records excluded at title/abstract: **{len(excluded):,}**")
A(f"- Reports sought for retrieval: **{len(included):,}**\n")
if exc_codes:
    A("### Exclusion reasons\n")
    A("A record may carry more than one code, so the codes sum to more than the records excluded.\n")
    A("| Code | Reason | Records | Share of exclusions |")
    A("|---|---|---|---|")
    for code, n_ in exc_codes.most_common():
        A(f"| `{code}` | {CRIT.get(code, '—')} | {n_:,} | {100*n_/len(excluded):.1f}% |")
    if uncoded_exc: A(f"| — | *(no code recorded)* | {uncoded_exc:,} | {100*uncoded_exc/len(excluded):.1f}% |")
    A("")
if inc_codes:
    A("### Inclusion reasons\n")
    A("| Code | Reason | Records |")
    A("|---|---|---|")
    for code, n_ in inc_codes.most_common():
        A(f"| `{code}` | {CRIT.get(code, '—')} | {n_:,} |")
    A("")
A("## Included set\n")
A("| Type | Records |")
A("|---|---|")
for k, v in types.most_common(): A(f"| {TL.get(k, k)} | {v:,} |")
A("")
A("| Year | Records |")
A("|---|---|")
for y in sorted(yrs): A(f"| {y} | {yrs[y]:,} |")
A("")
open(os.path.join(STUDY, 'screening_summary.md'), 'w').write('\n'.join(M))

_sp = os.path.join(OUT, 'prisma_stats.json')
_st = json.load(open(_sp))
_st['screening'] = {
    'screened': len(decisions), 'excluded': len(excluded), 'included': len(included),
    'exclusion_reasons': [{'code': c, 'label': CRIT.get(c, ''), 'n': n_} for c, n_ in exc_codes.most_common()],
    'uncoded_exclusions': uncoded_exc,
    'by_reviewer': {r: {'screened': by_rev[r], 'included': inc_by_rev[r]} for r in by_rev},
    'updated': TODAY.isoformat(),
}
json.dump(_st, open(_sp, 'w'), indent=1, ensure_ascii=False)
print("prisma_stats.json updated - rerun 02_report.py to redraw the flow diagram")
if missing: print(f"\n! partial build: {len(missing):,} record(s) still unscreened")
print(f"\nstudy corpus: {len(recs):,} records -> {STUDY}/")
