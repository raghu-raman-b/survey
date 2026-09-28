#!/usr/bin/env python3
"""Catalog + PRISMA-style deduplication of the survey corpus in exports/."""
import os, re, csv, json, glob, html, unicodedata, difflib, datetime
from collections import defaultdict, Counter

EXPORTS = "/home/prex_san/Documents/survey/exports"
OUTDIR  = "/home/prex_san/Documents/survey/final_corpus"

# ---------------------------------------------------------------- normalisers
LATEX = {
    r'\&':'&', r'\%':'%', r'\_':'_', r'\#':'#', r'\$':'$', r'\{':'{', r'\}':'}',
    r'\textemdash':'—', r'\textendash':'–', r'\textquotesingle':"'",
    r'\ldots':'…', r'\textbackslash':'\\', r'\ ':' ',
}
ACCENT = re.compile(r'\\[`\'"^~=.vuHcdbkr]\s*\{?([A-Za-z])\}?')

def clean_latex(s):
    if not s: return s
    s = ACCENT.sub(r'\1', s)
    for k, v in LATEX.items():
        s = s.replace(k, v)
    s = re.sub(r'\\[a-zA-Z]+\s*', ' ', s)          # leftover macros
    s = s.replace('{', '').replace('}', '')
    s = re.sub(r'\s+', ' ', s).strip()
    return s

TAGSTRIP = re.compile(r'<[^>]+>')
def clean_text(s):
    if not s: return ''
    s = html.unescape(s)
    s = TAGSTRIP.sub('', s)
    return re.sub(r'\s+', ' ', s).strip()

STOP = set("a an the of on in for with and or to from by at as is are be using via toward towards towards".split())

def norm_title(t):
    """Aggressive title key: fold accents, drop punctuation + case."""
    t = clean_text(clean_latex(t or ''))
    t = unicodedata.normalize('NFKD', t)
    t = ''.join(c for c in t if not unicodedata.combining(c))
    t = t.lower()
    t = re.sub(r'\$[^$]*\$', ' ', t)               # inline math
    t = re.sub(r'[^a-z0-9 ]+', ' ', t)
    return re.sub(r'\s+', ' ', t).strip()

def title_tokens(nt):
    return {w for w in nt.split() if w not in STOP and len(w) > 2}

DOI_RE = re.compile(r'10\.\d{4,9}/\S+', re.I)
def norm_doi(d, fold=True):
    if not d: return ''
    d = clean_text(clean_latex(d))
    m = DOI_RE.search(d)
    if not m: return ''
    d = m.group(0).rstrip('.,;)]}>\'"')
    return d.lower() if fold else d

def surname(a):
    """Last name from 'Smith, John' or 'J. Smith' or 'John Smith'."""
    a = clean_text(clean_latex(a or ''))
    if not a: return ''
    if ',' in a:
        s = a.split(',')[0]
    else:
        s = a.split()[-1] if a.split() else ''
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return re.sub(r'[^a-z]', '', s.lower())

def year_of(s):
    m = re.search(r'(19|20)\d{2}', str(s or ''))
    return m.group(0) if m else ''

# ---------------------------------------------------------------- RIS parsing
RIS_TAG = re.compile(r'^([A-Z][A-Z0-9])  - ?(.*)$')

def parse_ris(path):
    recs, cur = [], defaultdict(list)
    with open(path, encoding='utf-8-sig', errors='replace') as fh:
        for line in fh:
            line = line.rstrip('\n').rstrip('\r')
            m = RIS_TAG.match(line)
            if not m:
                continue
            tag, val = m.group(1), m.group(2).strip()
            if tag == 'ER':
                if cur: recs.append(dict(cur))
                cur = defaultdict(list)
            else:
                if val: cur[tag].append(val)
    if cur: recs.append(dict(cur))
    return recs

RIS_TY_FIX = {
    'label.ris.referencetype.book_chapter': 'CHAP',
    'label.ris.referencetype.book': 'BOOK',
    'label.ris.referencetype.conference_paper': 'CONF',
    'label.ris.referencetype.article': 'JOUR',
}
def fix_ty(ty):
    ty = (ty or '').strip()
    return RIS_TY_FIX.get(ty.lower(), ty.upper() if ty else 'GEN')

def ris_to_record(r, src, fname):
    g = lambda t: (r.get(t) or [''])[0]
    title = g('TI') or g('T1')
    venue = g('T2') or g('JO') or g('JA') or g('T3')
    return dict(
        source_db=src, source_file=fname,
        type=fix_ty(g('TY')),
        title=clean_text(title),
        authors=[clean_text(a) for a in r.get('AU', []) + r.get('A1', [])],
        year=year_of(g('PY') or g('Y1') or g('DA')),
        doi=norm_doi(g('DO') or g('DI')),
        doi_raw=norm_doi(g('DO') or g('DI'), fold=False),
        venue=clean_text(venue),
        volume=g('VL') or g('VO'), issue=g('IS'),
        start_page=g('SP'), end_page=g('EP'),
        publisher=clean_text(g('PB')),
        abstract=clean_text(g('AB') or g('N2')),
        keywords=[clean_text(k) for k in r.get('KW', [])],
        url=g('UR') or g('L2'),
        issn=g('SN'), isbn=g('SN') if r.get('TY') == ['BOOK'] else '',
        notes=[clean_text(n) for n in r.get('N1', [])],
        raw=r,
    )

# ------------------------------------------------------------ BibTeX parsing
def parse_bibtex(path):
    txt = open(path, encoding='utf-8-sig', errors='replace').read()
    entries, i, n = [], 0, len(txt)
    while True:
        at = txt.find('@', i)
        if at < 0: break
        ob = txt.find('{', at)
        if ob < 0: break
        etype = txt[at+1:ob].strip().lower()
        # scan to matching close brace
        depth, j = 1, ob + 1
        while j < n and depth:
            c = txt[j]
            if c == '{': depth += 1
            elif c == '}': depth -= 1
            j += 1
        body = txt[ob+1:j-1]
        i = j
        if etype in ('comment', 'preamble', 'string'):
            continue
        key, _, rest = body.partition(',')
        entries.append((etype, key.strip(), rest))
    return entries

def split_fields(rest):
    """Split 'a = {x}, b = {y}' honouring nested braces and quotes."""
    out, k, i, n = {}, None, 0, len(rest)
    while i < n:
        eq = rest.find('=', i)
        if eq < 0: break
        name = rest[i:eq].strip().strip(',').strip().lower()
        j = eq + 1
        while j < n and rest[j] in ' \t\r\n': j += 1
        if j >= n: break
        if rest[j] == '{':
            depth, k0 = 1, j + 1
            j += 1
            while j < n and depth:
                if rest[j] == '{': depth += 1
                elif rest[j] == '}': depth -= 1
                j += 1
            val = rest[k0:j-1]
        elif rest[j] == '"':
            k0 = j + 1; j += 1
            while j < n and rest[j] != '"': j += 1
            val = rest[k0:j]; j += 1
        else:
            k0 = j
            while j < n and rest[j] != ',': j += 1
            val = rest[k0:j].strip()
        if name:
            out[name] = val
        nxt = rest.find(',', j)
        i = (nxt + 1) if nxt >= 0 else n
    return out

BIB2RIS = {'inproceedings':'CONF','conference':'CONF','proceedings':'CONF',
           'article':'JOUR','book':'BOOK','inbook':'CHAP','incollection':'CHAP',
           'phdthesis':'THES','mastersthesis':'THES','techreport':'RPRT','misc':'GEN'}

def bib_to_record(etype, key, rest, fname, src):
    f = split_fields(rest)
    authors = []
    if f.get('author'):
        authors = [clean_text(clean_latex(a)) for a in re.split(r'\s+and\s+', f['author']) if a.strip()]
    kws = []
    if f.get('keywords'):
        kws = [clean_text(clean_latex(k)) for k in re.split(r'[;,]\s*', f['keywords']) if k.strip()]
    pages = clean_text(f.get('pages', '')).replace('–', '-').replace('—', '-')
    sp, ep = '', ''
    if pages:
        parts = re.split(r'-+', pages)
        sp = parts[0].strip()
        ep = parts[-1].strip() if len(parts) > 1 else ''
    venue = f.get('booktitle') or f.get('journal') or f.get('series') or ''
    return dict(
        source_db=src, source_file=fname,
        type=BIB2RIS.get(etype, 'GEN'),
        title=clean_text(clean_latex(f.get('title', ''))),
        authors=authors,
        year=year_of(f.get('year') or f.get('issue_date')),
        doi=norm_doi(f.get('doi') or f.get('url')),
        doi_raw=norm_doi(f.get('doi') or f.get('url'), fold=False),
        venue=clean_text(clean_latex(venue)),
        volume=clean_text(f.get('volume', '')), issue=clean_text(f.get('number', '')),
        start_page=sp, end_page=ep,
        publisher=clean_text(clean_latex(f.get('publisher', ''))),
        abstract=clean_text(clean_latex(f.get('abstract', ''))),
        keywords=kws,
        url=clean_text(f.get('url', '')),
        issn=clean_text(f.get('issn', '')), isbn=clean_text(f.get('isbn', '')),
        notes=[f'BibTeX key: {key}'] + ([f"series: {clean_text(clean_latex(f['series']))}"] if f.get('series') else []),
        raw={'bibkey': key, 'entrytype': etype, **{k: clean_text(clean_latex(v)) for k, v in f.items() if k != 'abstract'}},
    )

# ------------------------------------------------------------------- ingest
records = []
per_file = []

for path in sorted(glob.glob(os.path.join(EXPORTS, '*.ris'))):
    fname = os.path.basename(path)
    src = 'IEEE Xplore' if fname.lower().startswith('ieee') else None
    raws = parse_ris(path)
    if src is None:
        dbs = Counter((r.get('DB') or ['?'])[0] for r in raws)
        src = dbs.most_common(1)[0][0] if dbs else 'Unknown'
    for r in raws:
        records.append(ris_to_record(r, src, fname))
    per_file.append((fname, src, len(raws)))

for path in sorted(glob.glob(os.path.join(EXPORTS, '*.bib'))):
    fname = os.path.basename(path)
    src = 'ACM Digital Library'
    ents = parse_bibtex(path)
    for etype, key, rest in ents:
        records.append(bib_to_record(etype, key, rest, fname, src))
    per_file.append((fname, src, len(ents)))

for i, r in enumerate(records):
    r['idx'] = i
    r['ntitle'] = norm_title(r['title'])
    r['tokens'] = title_tokens(r['ntitle'])
    r['surnames'] = [s for s in (surname(a) for a in r['authors']) if s]

print(f"Parsed {len(records)} records from {len(per_file)} files")
json.dump({'per_file': per_file}, open('/tmp/pf.json', 'w'))

# --------------------------------------------------------------- union-find
parent = list(range(len(records)))
def find(x):
    while parent[x] != x:
        parent[x] = parent[parent[x]]; x = parent[x]
    return x
def union(a, b):
    ra, rb = find(a), find(b)
    if ra != rb:
        parent[max(ra, rb)] = min(ra, rb)
        return True
    return False

dup_links = []   # (kept_idx_hint, other_idx, method, score, note)

# Stage 1 -- exact DOI
by_doi = defaultdict(list)
for r in records:
    if r['doi']:
        by_doi[r['doi']].append(r['idx'])
doi_links = 0
for d, idxs in by_doi.items():
    for other in idxs[1:]:
        if union(idxs[0], other):
            doi_links += 1
            dup_links.append((idxs[0], other, 'doi', 1.0, d))

# Stage 2 -- identical normalised title
by_title = defaultdict(list)
for r in records:
    if len(r['ntitle']) >= 10:
        by_title[r['ntitle']].append(r['idx'])
exact_title_links = 0
for t, idxs in by_title.items():
    for other in idxs[1:]:
        if union(idxs[0], other):
            exact_title_links += 1
            dup_links.append((idxs[0], other, 'exact-title', 1.0, t[:80]))

# Stage 3 -- fuzzy title (inverted-index blocking on rare tokens)
inv = defaultdict(list)
for r in records:
    for t in r['tokens']:
        inv[t].append(r['idx'])
COMMON = {t for t, v in inv.items() if len(v) > 400}

fuzzy_links, flagged = 0, []
for r in records:
    toks = r['tokens'] - COMMON
    if len(r['ntitle']) < 15 or len(toks) < 2:
        continue
    cand = Counter()
    for t in toks:
        if len(inv[t]) > 400: continue
        for j in inv[t]:
            if j > r['idx']:
                cand[j] += 1
    need = max(2, int(0.55 * len(toks)))
    for j, c in cand.items():
        if c < need: continue
        o = records[j]
        if find(r['idx']) == find(j): continue
        jac = len(r['tokens'] & o['tokens']) / max(1, len(r['tokens'] | o['tokens']))
        ratio = difflib.SequenceMatcher(None, r['ntitle'], o['ntitle']).ratio()
        if ratio < 0.90 and jac < 0.85: continue
        # author / year corroboration
        sa, sb = set(r['surnames']), set(o['surnames'])
        auth_ok = (not sa or not sb) or bool(sa & sb)
        yr_ok = (not r['year'] or not o['year']) or abs(int(r['year']) - int(o['year'])) <= 1
        RETR = re.compile(r'^(retracted|retraction notice|erratum|corrigendum|correction to|withdrawn)', re.I)
        ma, mb = RETR.match(r['ntitle'] or ''), RETR.match(o['ntitle'] or '')
        if bool(ma) != bool(mb) or (ma and mb and ma.group(1).lower() != mb.group(1).lower()):
            flagged.append((r['idx'], j, round(ratio, 3), round(jac, 3),
                            'retraction/erratum pair - kept separate', ''))
            continue
        strong = ratio >= 0.97 or jac >= 0.95
        if (strong and (auth_ok or yr_ok)) or (ratio >= 0.90 and auth_ok and yr_ok):
            if union(r['idx'], j):
                fuzzy_links += 1
                dup_links.append((r['idx'], j, 'fuzzy-title', round(max(ratio, jac), 3),
                                  f"ratio={ratio:.3f} jac={jac:.3f}"))
        else:
            flagged.append((r['idx'], j, round(ratio, 3), round(jac, 3), auth_ok, yr_ok))

# ------------------------------------------------------------ cluster + pick
clusters = defaultdict(list)
for r in records:
    clusters[find(r['idx'])].append(r['idx'])

DB_RANK = {'ACM Digital Library': 0, 'IEEE Xplore': 1, 'Scopus': 2}
def completeness(r):
    return (bool(r['doi']), bool(r['abstract']), len(r['keywords']) > 0,
            bool(r['authors']), bool(r['venue']), bool(r['start_page']),
            len(r['abstract']))

def pick(idxs):
    return sorted(idxs, key=lambda i: (
        tuple(0 if b else 1 for b in completeness(records[i])[:6]),
        -completeness(records[i])[6],
        DB_RANK.get(records[i]['source_db'], 9), i))[0]

final = []
for root, idxs in sorted(clusters.items()):
    keep = pick(idxs)
    r = dict(records[keep])
    r['n_in_cluster'] = len(idxs)
    r['found_in'] = sorted({records[i]['source_db'] for i in idxs})
    r['merged_idxs'] = sorted(idxs)
    # backfill sparse fields from siblings
    for i in idxs:
        s = records[i]
        for fld in ('doi', 'doi_raw', 'abstract', 'venue', 'year', 'volume', 'issue',
                    'start_page', 'end_page', 'publisher', 'url', 'issn', 'isbn'):
            if not r.get(fld) and s.get(fld):
                r[fld] = s[fld]
        if not r['authors'] and s['authors']:
            r['authors'] = s['authors']
        if len(s['keywords']) > len(r['keywords']):
            r['keywords'] = s['keywords']
        if len(s['abstract']) > len(r['abstract']):
            r['abstract'] = s['abstract']
    final.append(r)

final.sort(key=lambda r: (r['year'] or '0000', r['ntitle']))
json.dump({'doi': doi_links, 'exact': exact_title_links, 'fuzzy': fuzzy_links,
           'n_records': len(records), 'n_final': len(final),
           'flagged': len(flagged)}, open('/tmp/stats.json', 'w'))
print('dup links  doi=%d exact-title=%d fuzzy=%d  -> unique=%d (flagged near-misses=%d)'
      % (doi_links, exact_title_links, fuzzy_links, len(final), len(flagged)))

# ----------------------------------------------------------------- write out
os.makedirs(OUTDIR, exist_ok=True)

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
    L.append("ER  - ")
    return L

for n, r in enumerate(final, 1):
    r['cid'] = n

with open(os.path.join(OUTDIR, 'final_corpus.ris'), 'w', encoding='utf-8') as fh:
    for r in final:
        fh.write('\n'.join(ris_lines(r)) + '\n\n')

# full catalogue of every source record + its disposition
with open(os.path.join(OUTDIR, 'catalog_all_records.csv'), 'w', newline='', encoding='utf-8') as fh:
    w = csv.writer(fh)
    w.writerow(['source_record_id','source_db','source_file','status','corpus_id',
                'cluster_size','type','year','doi','title','authors','venue'])
    cid_of = {}
    for r in final:
        for i in r['merged_idxs']:
            cid_of[i] = (r['cid'], r['merged_idxs'][0] if False else r['idx'], len(r['merged_idxs']))
    for r in records:
        cid, keep_idx, csize = cid_of.get(r['idx'], ('', '', 1))
        status = 'retained' if r['idx'] == keep_idx else 'duplicate-removed'
        w.writerow([f"S{r['idx']:05d}", r['source_db'], r['source_file'], status,
                    f"C{cid:04d}" if cid else '', csize, r['type'], r['year'], r['doi'],
                    r['title'], '; '.join(r['authors']), r['venue']])

json.dump(final, open(os.path.join(OUTDIR, 'final_corpus.json'), 'w'),
          ensure_ascii=False, indent=1, default=str)
print('written to', OUTDIR)

# ----------------------------------------------------------- stats for report
stats = {
    'per_file': per_file,
    'identified_by_db': dict(Counter(r['source_db'] for r in records)),
    'n_identified': len(records),
    'n_unique': len(final),
    'n_removed': len(records) - len(final),
    'removed_by_db': dict(Counter(records[i]['source_db'] for r in final for i in r['merged_idxs'] if i != r['idx'])),
    'retained_by_db': dict(Counter(r['source_db'] for r in final)),
    'found_in_combos': {' + '.join(k): v for k, v in
                        sorted(Counter(tuple(r['found_in']) for r in final).items(), key=lambda x: -x[1])},
    'cluster_sizes': dict(sorted(Counter(r['n_in_cluster'] for r in final).items())),
    'types': dict(Counter(r['type'] for r in final).most_common()),
    'years': dict(sorted(Counter(r['year'] for r in final).items())),
    'top_venues': Counter(r['venue'] for r in final if r['venue']).most_common(20),
    'missing_doi': sum(1 for r in final if not r['doi']),
    'missing_abstract': sum(1 for r in final if not r['abstract']),
    'missing_year': sum(1 for r in final if not r['year']),
}
stats['run_date'] = datetime.date.today().isoformat()
json.dump(stats, open(os.path.join(OUTDIR, 'prisma_stats.json'), 'w'), indent=1, ensure_ascii=False)
print('identified %d -> unique %d' % (len(records), len(final)))
