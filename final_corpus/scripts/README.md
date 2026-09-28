# Pipeline

Stdlib only, no third-party dependencies. Deterministic — the same exports reproduce the
same corpus IDs. Paths are set at the top of `01_dedupe.py` (`EXPORTS`, `OUTDIR`).

## A. Building the corpus

    python3 01_dedupe.py           # exports/ -> final_corpus.{ris,json}, catalog, prisma_stats.json
    python3 03_screening_sheet.py  # -> duplicate_screening.md (worksheet for the manual duplicate review)
    python3 05_apply_decisions.py  # applies MERGES -> final corpus + screening_decisions.md
    python3 02_report.py           # -> PRISMA_flow.md + prisma_flow_diagram.svg

Run in that order. `03` is only needed when re-opening the duplicate review; the calls it
produced are recorded in `MERGES` at the top of `05_apply_decisions.py`, which is the file
to edit if a merge decision changes. `05` is idempotent.

## B. Drawing the samples

    python3 06_agreement_sample.py  # -> agreement/  : 226 records (10%), stratified by year
    python3 08_split_screening.py   # -> screening/  : screener_1.ris (1,020), screener_2.ris (1,017)

The two are disjoint and together cover the corpus: 226 + 1,020 + 1,017 = 2,263.
`08` reads the agreement manifest and holds those records out.

## C. Screening

Reviewers work in `../screening_tool.html`. Its **Phase** switch decides what each export
is called:

| Phase | Reviewer loads | Export lands as |
|---|---|---|
| Agreement | `agreement/agreement_sample.ris` | `agreement_<name>.json` |
| Screening | `screening/screener_N.ris` | `screened_articles_<name>.json` |

Both go into `screening/`. Adjudicating on the tool's Resolve tab produces
`adjudicated_screened_sample.json`.

    python3 07_kappa.py a.json b.json   # inter-rater agreement between two reviewer files
    python3 09_combine.py               # screening/*.json -> study_corpus/

`07_kappa.py` reads the tool's JSON exports (two or more), or the `reviewer_*` columns of
a CSV sheet. It reports raw agreement, Cohen's κ with a 95% CI, Krippendorff's α, the
confusion matrix and every disagreement. Run it bare and it finds the agreement files and
prints the command to use.

`09_combine.py` skips `agreement_*.json` — the adjudicated file supersedes those — and
blocks on unsettled `maybe`s, contradictions between files, and records with no decision
at all. `--allow-partial` overrides only the last of those, for a mid-way build; don't use
it on the final run.

## Step numbering

`04` was a threshold sweep used once to reconcile this corpus against another tool's
duplicate count; it was removed after the question was settled. The remaining numbers
were left as they are so they keep matching the documentation.
