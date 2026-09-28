#!/usr/bin/env python3
"""Render PRISMA_flow.md + prisma_flow_diagram.svg from prisma_stats.json."""
import json, os, datetime
from xml.sax.saxutils import escape

OUT = "/home/prex_san/Documents/survey/final_corpus"
S = json.load(open(os.path.join(OUT, 'prisma_stats.json')))
n = lambda x: f"{x:,}"
pct = lambda a, b: f"{100*a/b:.1f}%"

ID = S['identified_by_db']
DBS = sorted(ID, key=lambda k: -ID[k])
TOT, UNIQ, REM = S['n_identified'], S['n_unique'], S['n_removed']
SC   = S.get('screening')            # filled in by 09_combine.py once screening is done
SCRN = f"{SC['screened']:,}"  if SC else "____"
SEXC = f"{SC['excluded']:,}"  if SC else "____"
SINC = f"{SC['included']:,}"  if SC else "____"
REASONS = (SC or {}).get('exclusion_reasons', [])
RUN = S.get('run_date') or datetime.date.today().isoformat()
PRETTY = datetime.date.fromisoformat(RUN).strftime('%d %B %Y')

# ------------------------------------------------------------------- SVG
W, BOXL_X, BOXL_W, BOXR_X, BOXR_W = 1000, 150, 400, 600, 372
FONT = "Helvetica, Arial, sans-serif"
svg, arrows = [], []

def box(x, y, w, h, lines, dashed=False):
    svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="3" fill="#ffffff" '
               f'stroke="#000" stroke-width="1.2"{" stroke-dasharray=\"5 3\"" if dashed else ""}/>')
    ty = y + 21
    for i, ln in enumerate(lines):
        svg.append(f'<text x="{x+12}" y="{ty}" font-family="{FONT}" font-size="12.5" '
                   f'font-weight="{"bold" if i == 0 else "normal"}" fill="#000">{escape(ln)}</text>')
        ty += 17

def arrow(x1, y1, x2, y2):
    arrows.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#000" '
                  f'stroke-width="1.2" marker-end="url(#ah)"/>')

def bandbox(y, h, label):
    svg.append(f'<rect x="30" y="{y}" width="34" height="{h}" rx="3" fill="#e8e8e8" stroke="#000" stroke-width="1"/>')
    cy = y + h / 2
    svg.append(f'<text x="47" y="{cy}" font-family="{FONT}" font-size="13" font-weight="bold" '
               f'fill="#000" text-anchor="middle" transform="rotate(-90 47 {cy})">{escape(label)}</text>')

y = 46
L1 = [f"Records identified from databases (n = {n(TOT)}):"] + \
     [f"    {db} (n = {n(ID[db])})" for db in DBS]
R1 = ["Records removed before screening:", f"    Duplicate records removed (n = {n(REM)})"]
h1 = 26 + 17 * max(len(L1), len(R1))
bandbox(y, h1, "Identification")
box(BOXL_X, y, BOXL_W, h1, L1)
box(BOXR_X, y, BOXR_W, h1, R1)
arrow(BOXL_X + BOXL_W, y + h1 / 2, BOXR_X - 2, y + h1 / 2)
prev = y + h1

y = prev + 46
scr_top = y - 12
box(BOXL_X, y, BOXL_W, 40, [f"Records screened (n = {n(UNIQ)})"])
# PRISMA 2020 wants a bare count here; reasons belong to the full-text box below.
_eh = 40
box(BOXR_X, y, BOXR_W, _eh, [f"Records excluded (n = {SEXC})"], dashed=not SC)
arrow(BOXL_X + BOXL_W / 2, prev, BOXL_X + BOXL_W / 2, y - 2)
arrow(BOXL_X + BOXL_W, y + 20, BOXR_X - 2, y + 20)
prev = y + 40

prev = max(prev, y + _eh)
for left, right, rh in [([f"Reports sought for retrieval (n = {SINC})"], ["Reports not retrieved (n = ____)"], 40),
                        (["Reports assessed for eligibility (n = ____)"],
                         ["Reports excluded:", "    Reason 1 (n = ____)",
                          "    Reason 2 (n = ____)", "    Reason 3 (n = ____)"], 92)]:
    y = prev + 40
    box(BOXL_X, y, BOXL_W, 40, left, dashed=(left[0].endswith("____)")))
    box(BOXR_X, y, BOXR_W, rh, right, dashed=True)
    arrow(BOXL_X + BOXL_W / 2, prev, BOXL_X + BOXL_W / 2, y - 2)
    arrow(BOXL_X + BOXL_W, y + 20, BOXR_X - 2, y + 20)
    prev = y + 40
bandbox(scr_top, prev - scr_top + 12, "Screening")

y = prev + 46
bandbox(y - 10, 62, "Included")
box(BOXL_X, y, BOXL_W, 40, ["Studies included in review (n = ____)"], dashed=True)
arrow(BOXL_X + BOXL_W / 2, prev, BOXL_X + BOXL_W / 2, y - 2)
H = y + 40 + 40

doc = (f'<?xml version="1.0" encoding="UTF-8"?>\n'
       f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">\n'
       f'<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
       f'orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#000"/></marker></defs>\n'
       f'<rect width="{W}" height="{H}" fill="#ffffff"/>\n'
       f'<text x="{W/2}" y="28" font-family="{FONT}" font-size="15" font-weight="bold" '
       f'text-anchor="middle" fill="#000">PRISMA 2020 flow diagram: identification of studies via databases</text>\n'
       + '\n'.join(svg) + '\n' + '\n'.join(arrows) + '\n</svg>\n')
open(os.path.join(OUT, 'prisma_flow_diagram.svg'), 'w').write(doc)

# ------------------------------------------------------------------ markdown
def tbl(rows, head):
    w = [max(len(str(r[i])) for r in [head] + rows) for i in range(len(head))]
    out = ['| ' + ' | '.join(str(head[i]).ljust(w[i]) for i in range(len(head))) + ' |',
           '|' + '|'.join('-' * (w[i] + 2) for i in range(len(head))) + '|']
    for r in rows:
        out.append('| ' + ' | '.join(str(r[i]).ljust(w[i]) for i in range(len(head))) + ' |')
    return '\n'.join(out)

LW, RW, GAP, IND = 46, 44, 8, 2
def _b(t, w): return "│ " + t.ljust(w - 3) + "│"
def _top(w):  return "┌" + "─" * (w - 2) + "┐"
def _bot(w):  return "└" + "─" * (w - 2) + "┘"
def _botT(w): return "└" + "─" * ((w - 2)//2) + "┬" + "─" * (w - 3 - (w - 2)//2) + "┘"
def stage(left, right=None, exit_down=True):
    ll, rl = list(left), list(right or [])
    h = max(len(ll), len(rl)); mid = h // 2
    out = [" " * IND + _top(LW) + " " * GAP + (_top(RW) if rl else "")]
    for i in range(h):
        lrow = _b(ll[i] if i < len(ll) else "", LW)
        if not rl:
            out.append(" " * IND + lrow); continue
        link = ("─" * (GAP - 1) + "▶") if i == mid else " " * GAP
        out.append(" " * IND + lrow + link + _b(rl[i] if i < len(rl) else "", RW))
    out.append(" " * IND + (_botT(LW) if exit_down else _bot(LW)) + " " * GAP + (_bot(RW) if rl else ""))
    return out
def conn():
    c = IND + 1 + (LW - 2)//2
    return [" " * c + "│", " " * c + "▼"]

md = []; A = md.append
A("# PRISMA corpus assembly\n")
A(f"**Date:** {PRETTY}  ")
A(f"**Records identified:** {n(TOT)}  ")
A(f"**Duplicates removed:** {n(REM)}  ")
A(f"**Records for screening:** {n(UNIQ)} — [`final_corpus.ris`](final_corpus.ris)  ")
if SC:
    A(f"**Screened:** {SCRN} · **Excluded:** {SEXC} · **Taken to full text:** {SINC}")
A("")
A("---\n")
A("## Flow diagram\n")
A("Vector version for the manuscript: [`prisma_flow_diagram.svg`](prisma_flow_diagram.svg)\n")
flow  = ["  IDENTIFICATION"]
flow += stage([f"Records identified from databases:"] +
              [f"    {db:<22} n = {n(ID[db]):>5}" for db in DBS] +
              [f"    {'TOTAL':<22} n = {n(TOT):>5}"],
              ["Records removed before screening:",
               f"    Duplicate records removed  n = {n(REM):>5}"])
flow += conn() + ["  SCREENING"]
flow += stage([f"Records screened            n = {n(UNIQ):>5}"],
              [f"Records excluded            n = {SEXC:>5}"])
flow += conn()
flow += stage([f"Reports sought for retrieval  n = {SINC:>5}"], ["Reports not retrieved       n = ____"])
flow += conn()
flow += stage(["Reports assessed for eligibility  n = ____"],
              ["Reports excluded:", "    Reason 1                n = ____",
               "    Reason 2                n = ____", "    Reason 3                n = ____"])
flow += conn() + ["  INCLUDED"]
flow += stage([f"Studies included in review  n = ____"], exit_down=False)
A("```text")
for ln in flow: A(ln.rstrip())
A("```\n")
A("Boxes marked `n = ____` are filled in after full-text screening.\n" if SC
  else "Boxes marked `n = ____` are filled in after title/abstract and full-text screening.\n")
if SC:
    A("---\n")
    A("## Screening\n")
    A(tbl([["Records screened", n(SC['screened'])],
           ["Excluded at title/abstract", n(SC['excluded'])],
           ["Taken forward to full text", n(SC['included'])]], ['', 'Records']))
    A("")
    if REASONS:
        _base = SC.get('coded_pool', 0)
        A("### Why records were excluded, in the agreement sample\n")
        A(f"Reason codes were recorded during the agreement phase only ({n(_base)} records), not")
        A("across the full corpus — PRISMA asks for exclusion reasons at full text, not at")
        A("title/abstract. These figures characterise the criteria; they are not the breakdown of")
        A(f"all {n(SC['excluded'])} exclusions. A record can carry more than one code.\n")
        A(tbl([[f"`{r['code']}`", r['label'] or '—', n(r['n'])] for r in REASONS],
              ['Code', 'Reason', 'Records in sample']))
        A("")
    if SC.get('by_reviewer'):
        A("### By reviewer\n")
        A(tbl([[r, n(v['screened']), n(v['included']), pct(v['included'], v['screened'])]
               for r, v in sorted(SC['by_reviewer'].items())],
              ['Reviewer', 'Screened', 'Included', 'Inclusion rate']))
        A("")
A("---\n")
A("## Records per database\n")
rows = [[db, n(ID[db]), pct(ID[db], TOT), n(S['removed_by_db'].get(db, 0)),
         n(S['retained_by_db'].get(db, 0))] for db in DBS]
rows.append(['**Total**', f"**{n(TOT)}**", '**100.0%**', f"**{n(REM)}**", f"**{n(UNIQ)}**"])
A(tbl(rows, ['Database', 'Identified', 'Share of search', 'Removed as duplicate', 'Retained']))
A("")
A("> A record counted as *removed* is not a lost study — the same work is retained via its record")
A("> from another database.\n")
A("### Per export file\n")
A(tbl([[f, db, n(c)] for f, db, c in sorted(S['per_file'], key=lambda x: (x[1], x[0]))],
      ['Export file', 'Database', 'Records']))
A("")
A("---\n")
A("## Database overlap\n")
A("Which databases each unique study was found in:\n")
A(tbl([[k, n(v), pct(v, UNIQ)] for k, v in S['found_in_combos'].items()],
      ['Found in', 'Studies', 'Share']))
A("")
A("Studies supplied by **only one** database: " +
  ", ".join(f"{db} {n(S['found_in_combos'].get(db, 0))}" for db in DBS) +
  " — each search contributed material the others missed.\n")
A("---\n")
A("## Corpus composition\n")
TYPE_LABEL = {'CONF': 'Conference paper', 'JOUR': 'Journal article', 'CHAP': 'Book chapter',
              'BOOK': 'Book', 'STD': 'Standard', 'RPRT': 'Report', 'THES': 'Thesis', 'GEN': 'Other'}
A("### Publication type\n")
A(tbl([[TYPE_LABEL.get(k, k), n(v), pct(v, UNIQ)] for k, v in S['types'].items()],
      ['Type', 'Records', 'Share']))
A("")
A("### Publication year\n")
ymax = max(S['years'].values())
A(tbl([[k, n(v), '█' * max(1, round(28 * v / ymax))] for k, v in S['years'].items()],
      ['Year', 'Records', '']))
A("")
A("### Top 20 venues\n")
A(tbl([[i, n(c), v[:88]] for i, (v, c) in enumerate(S['top_venues'], 1)],
      ['#', 'Records', 'Venue']))
A("")
A("### Metadata completeness\n")
A(tbl([['DOI present', n(UNIQ - S['missing_doi']), pct(UNIQ - S['missing_doi'], UNIQ)],
       ['Abstract present', n(UNIQ - S['missing_abstract']), pct(UNIQ - S['missing_abstract'], UNIQ)],
       ['Year present', n(UNIQ - S['missing_year']), pct(UNIQ - S['missing_year'], UNIQ)]],
      ['Field', 'Records', 'Coverage']))
A("")
A("---\n")
A("## Files\n")
A(tbl([
    ['`final_corpus.ris`', f'The corpus: {n(UNIQ)} records — **screening input**'],
    ['`final_corpus.json`', 'Same records as JSON, with merge provenance'],
    ['`catalog_all_records.csv`', f'All {n(TOT)} source records, each mapped to its corpus ID and disposition'],
    ['`screening_decisions.md`', 'Record of the manual duplicate screening'],
    ['`prisma_stats.json`', 'Machine-readable version of every count here'],
    ['`prisma_flow_diagram.svg`', 'Flow diagram for the manuscript'],
    ['`scripts/`', 'The pipeline that produced all of the above'],
], ['File', 'Contents']))
A("")
A("Each record in `final_corpus.ris` carries `ID` / `N1  - corpus_id` (stable `Cnnnn` identifier),")
A("`N1  - found_in` (contributing databases) and `N1  - source_records_merged` (how many source")
A("records it represents).\n")

open(os.path.join(OUT, 'PRISMA_flow.md'), 'w').write('\n'.join(md))
print("wrote PRISMA_flow.md + prisma_flow_diagram.svg")
