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

## Retrieval and full-text screening

    python3 10_retrieval_sheet.py       # study_corpus/ -> retrieval/retrieval_tracker.xlsx (split in two)
    python3 11_fulltext_corpus.py       # completed tracker -> fulltext/fulltext_corpus.json
    python3 12_fulltext_combine.py      # fulltext/fulltext_<name>.json x2 -> PRISMA boxes

`11_fulltext_corpus.py` reads `retrieval/retrieval_tracker_complete.xlsx` and writes the
file both screeners load into `../../tools/fulltext_screening.html`. It pre-sets what is
already known: papers marked not retrievable with a note like "Short Paper", "Abstract",
"Demo" or "WiP" are excluded under E1, the rest of the not-retrievable ones are not
retrieved (neither appears in the tool), and acquired papers of 4 pages or fewer are pre-set
to E1 but stay visible under "Pre-set" so they can be overridden. It also records the
retrieval counts in `prisma_stats.json`, so the diagram shows them (dashed, as provisional)
until full-text screening is combined.

In the tool each screener picks their name and sees only their own papers that need
screening. Per paper: copy the title into Zotero → "Got it" starts the clock → one check
at a time, in the order of `fulltext_skim` in `criteria.json`. The first failed check
excludes the paper with that E code; passing every check includes it. The RQs appear as
"also note" hints under the checks they belong to (`fulltext_skim.steps[].rqs`). Export
`fulltext_<name>.json` into `fulltext/`.

`12_fulltext_combine.py` fills in the presets for papers nobody decided, then blocks on papers decided by the wrong screener, conflicting
decisions, exclusions with no reason, and undecided papers (`--allow-partial` writes an
interim summary only and leaves the diagram alone). Each excluded report is counted once,
under the check it failed. It writes `fulltext/fulltext_log.csv`,
`included_studies.json/.csv/.ris` and `fulltext_summary.md`, then reruns `02_report.py`.

## LLM briefings for full-text screening (optional)

Run from the repo root. Step 13 needs PyMuPDF, which is in the repo's `.venv`
(`python3 -m venv .venv && .venv/bin/pip install pymupdf`); step 14 is standard library.

    .venv/bin/python final_corpus/scripts/13_fulltext_extract.py       # PDFs -> fulltext/extracts/<ID>/
    python3 final_corpus/scripts/14_fulltext_summarize.py prepare      # prompt + cost estimate, no API calls
    python3 final_corpus/scripts/14_fulltext_summarize.py run --limit 5
    python3 final_corpus/scripts/14_fulltext_summarize.py batch-submit # or `run` for all, at full price
    python3 final_corpus/scripts/14_fulltext_summarize.py batch-collect

`13_fulltext_extract.py` matches each PDF in `survey-papers/` to a record (DOI in the file
name, DOI in the PDF, then title), cuts papers out of whole Springer proceedings volumes,
and writes per paper: `extract.md` (record metadata, format signals such as page count,
headers/footers and track words, the section outline, figure and table captions, and the
text without related work, references or appendices, with ⟨p.N⟩ page markers),
`meta.json`, `figures/*.jpg` (each figure cropped from the page) and `paper.pdf` (a hard
link to the PDF, or just the paper's pages when it sits in a proceedings volume;
`--pdfs-only` adds these to existing extracts). `manifest.json` and
`match_report.csv` list what was matched, skipped or flagged. `ref.rtf` is used as a cross-check.

`14_fulltext_summarize.py` sends each extract to the OpenAI Responses API (default model
`gpt-6-luna`, key from `OPENAI_API_KEY` or `.env`) with instructions built from
`criteria.json`, and saves `summary.json` next to the extract. The briefing follows the
`fulltext_skim` checks in order, then RQ1–RQ7. For each it reports what the paper says, with
page references and short quotes, and what is unclear. **It never gives a verdict**: the
screener decides. The exact instructions are saved as `prompt_system.txt` for the methods
section; every call's tokens and cost go to `usage_log.csv`. `--budget 5` stops before the
total in that log passes $5. `--model gpt-6.1-terra --save-as summary_terra.json` writes a
second briefing beside the first, for comparing models without replacing what the panel shows.

In the tool, Setup → **Briefings** → choose `final_corpus/fulltext/extracts`. The Screen tab
then shows the briefing, figures and format signals in a third column (or a drawer on
narrower screens; **B** toggles it), with the evidence for the current check highlighted.
**P** opens the paper's PDF in a tab, and every page reference in the briefing opens it at that page.
The `extracts/` folder holds copyrighted paper text and figures, so git ignores it.

## Step numbering

`04` was a threshold sweep used once to reconcile this corpus against another tool's
duplicate count; it was removed after the question was settled. The remaining numbers
were left as they are so they keep matching the documentation.
