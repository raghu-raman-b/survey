# How to screen this corpus

Corpus: **2,263 records** in `final_corpus.ris`.
Tool: open `screening_tool.html` in a browser (or the shared link).

Two people screen. Call yourselves **screener_1** and **screener_2** and keep those
names the same everywhere.

The tool has a **Phase** switch in the top bar — set it to match the part you're on.
It decides whether *Maybe* is available and what your export is called.

**Before you start:** fill in `criteria.json` with your real inclusion and exclusion
criteria, keeping the `I1`/`E1` code format, and both of you load it on the Corpus tab.

Codes are used in the **Agreement phase only** — you type `E1 E3` instead of writing a
sentence. Their job is to show you *why* you two disagreed, so you can fix the wording of
whichever criterion caused it. PRISMA wants exclusion reasons at full text, not at
title/abstract, so there is nothing to gain from coding 2,000 records of your own half —
the Screening phase hides the reason box entirely and is just Keep / Discard.

---

## Part 1 — Agreement check (226 records, both of you)

**1.** Both open the tool, set **Phase → Agreement**, type your reviewer name top right,
load `agreement/agreement_sample.ris`.

**2.** Screen all 226. Keep / Maybe / Discard, each with its codes (`I2` to keep, `E1 E4`
to discard). Work independently — don't compare yet.

**3.** Each: **Corpus** tab → *Export decisions (JSON)* → saves as
`agreement_<yourname>.json`. Put both into `screening/`.

**4.** Check agreement:

```
python3 scripts/07_kappa.py screening/agreement_screener_1.json \
                            screening/agreement_screener_2.json
```

- κ **0.60 or above** → go to step 5.
- κ **below 0.60** → stop. Fix the inclusion criteria, change `SEED` in
  `scripts/06_agreement_sample.py`, redraw, and redo Part 1 on the new sample.
  Don't re-score these same 226.

**5.** Sit together. In the tool: **Resolve** tab → load both JSON files.
Settle every disagreement and every maybe. Each reviewer's codes sit on their vote, and
*Where the criteria pull apart* lists the code pairs that recur — those are the criteria
to reword before Part 2. `07_kappa.py` prints the same table.

**6.** *Export final decisions* → save as `screening/adjudicated_screened_sample.json`.

---

## Part 2 — Screening (the other 2,037, one each)

**7.** Set **Phase → Screening**. screener_1 loads `screening/screener_1.ris`
(1,020 records); screener_2 loads `screening/screener_2.ris` (1,017 records).

**8.** Screen your own half. Keep or Discard, nothing else — this phase hides *Maybe*,
the reason box and the codes, so it's two keys and a glance. Nothing here gets
adjudicated, so if you're unsure, Keep it and settle at full text.

**9.** Each: **Corpus** tab → *Export decisions (JSON)* → saves as
`screened_articles_<yourname>.json`. Put both into `screening/`.

`screening/` now holds five files. The combine step uses the bottom three and ignores
the agreement ones, which the adjudicated file supersedes:

```
agreement_screener_1.json            (kept for the record)
agreement_screener_2.json            (kept for the record)
adjudicated_screened_sample.json     <- used
screened_articles_screener_1.json    <- used
screened_articles_screener_2.json    <- used
```

---

## Part 3 — Combine

**10.** Run:

```
python3 scripts/09_combine.py
```

Output lands in `study_corpus/`:

| File | What it is |
|---|---|
| `study_corpus.ris` | **the final set of articles to study** |
| `study_corpus.csv` | same, as a spreadsheet |
| `screening_log.csv` | every record, its decision, who made it |
| `screening_summary.md` | counts for the PRISMA screening boxes |
| `exclusion_reasons.csv` | code counts from the agreement sample |

If it refuses to run, it tells you why — an unsettled maybe, two files disagreeing, or a
record nobody screened. Fix that and rerun. Don't use `--allow-partial` on the final run.

**11.** Redraw the flow diagram with the screening numbers in it:

```
python3 scripts/02_report.py
```

`PRISMA_flow.md` and `prisma_flow_diagram.svg` now carry *records screened*, *records
excluded* and *reports sought for retrieval*. The full-text boxes stay blank until you get
there — that is where PRISMA asks for exclusion reasons, and where your codes earn their
place in the diagram.

---

## Notes

- Export often. The tool remembers your work in the browser, but that isn't a backup.
- In the Agreement phase with criteria loaded, a Keep needs an `I` code and a Discard needs
  an `E` code; the tool won't record the decision without one. Turn that off on the Corpus
  tab if you'd rather.
- Reloading a file you've part-screened picks up at the first undecided record.
- Keyboard while screening: `1` keep · `2` maybe (agreement only) · `3` discard ·
  `←` `→` move · `/` search.
- Decisions carry your reviewer name, so don't rename yourself mid-way.

## What else is here

| | |
|---|---|
| `PRISMA_flow.md` · `prisma_flow_diagram.svg` | how the corpus was built, for the manuscript |
| `screening_decisions.md` | duplicate calls made during deduplication |
| `agreement/README.md` | detail on the agreement sample |
| `screening/README.md` | detail on the split |
| `scripts/README.md` | the pipeline |
