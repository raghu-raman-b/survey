# Inter-rater agreement sample

**Drawn:** 28 September 2026 · **Sample:** 226 records = 10.0% of the 2,263-record corpus
**Method:** random sample stratified by publication year (proportional allocation),
`random.Random(20260928)`, reproducible via `../scripts/06_agreement_sample.py`.

The sample tracks the corpus closely on dimensions that were not stratified on:

| | Sample | Corpus |
|---|---|---|
| Scopus | 74.8% | 78.0% |
| IEEE Xplore | 19.0% | 16.0% |
| ACM Digital Library | 6.2% | 5.9% |
| Conference papers | 69.0% | 67.9% |
| Journal articles | 27.9% | 28.2% |

## Files

| File | |
|---|---|
| `agreement_sample.ris` | the 226 records — load into `../screening_tool.html` |
| `agreement_sample.csv` | the same records as a sheet, if you would rather score in a spreadsheet |
| `agreement_sample_manifest.json` | seed, allocation and the exact corpus IDs drawn |

Items are presented in shuffled order, so reviewers do not work through the sample
year by year.

## Protocol

1. Both reviewers open `../screening_tool.html`, set **Phase → Agreement** and their
   reviewer name, and load `agreement_sample.ris`.
2. Screen all 226 **independently** — don't compare notes until both are finished. That
   independence is what makes the statistic mean anything. Judge on title and abstract
   only, applying the same criteria you will use on the rest of the corpus. *Maybe* is
   available in this phase.
   Load `../criteria.json` first and tag each decision with its codes (`I2`, `E1 E4`).
   The codes exist for step 5 — they turn "we disagreed on 40 records" into "we disagree
   about what counts as E1" — and are not used in the screening phase.
3. Each exports from the Corpus tab; the file saves as `agreement_<name>.json`. Put both
   into `../screening/`.
4. Compute agreement:

       python3 ../scripts/07_kappa.py ../screening/agreement_screener_1.json \
                                      ../screening/agreement_screener_2.json

   It reports raw agreement, Cohen's κ with a 95% CI, Krippendorff's α, the confusion
   matrix, the inclusion rate and every disagreement. Run it bare and it will find the
   files and print the command.

   (If you scored in the spreadsheet instead, pass the CSV: it reads any `reviewer_*`
   columns.)
5. Then sit together, load both files on the tool's **Resolve** tab, settle every
   disagreement and every maybe, and export `adjudicated_screened_sample.json`.
   The tab shows each reviewer's codes on their vote and tallies the recurring code pairs
   under *Where the criteria pull apart*. Reword whichever criteria show up there before
   starting Part 2 — that is the whole point of piloting.

## Interpreting the result

Landis & Koch bands: 0.21–0.40 fair · 0.41–0.60 moderate · 0.61–0.80 substantial ·
0.81–1.00 almost perfect.

- **κ ≥ 0.75** — criteria are working. Go on to the divided screening in `../screening/`.
- **κ 0.60–0.75** — usable, but before you go on, reconcile every disagreement and tighten
  the wording of whichever criterion caused them.
- **κ < 0.60** — stop. The criteria are ambiguous, not the reviewers. Revise them, change
  `SEED` in `../scripts/06_agreement_sample.py`, redraw, and re-pilot on the **fresh**
  sample. Re-scoring these same 226 after discussing them inflates κ and tells you nothing.

One caveat to watch: κ is unstable when one category is rare. If the inclusion rate comes
out below ~10%, a handful of disagreements will swing κ hard, and a low value may say more
about prevalence than about reviewer reliability. `07_kappa.py` warns when this applies —
read the raw agreement and confusion matrix alongside κ in that case.

## Reporting

State in the manuscript: the sample size and how it was drawn, that screening was
independent, the κ value with its CI, and how disagreements were resolved (consensus, or a
third reviewer). `../study_corpus/screening_summary.md` carries the screening counts for
the PRISMA boxes once everything is combined.
