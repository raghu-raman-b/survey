# Screening

The 2,263-record corpus is screened in two passes.

| | Records | Screened by |
|---|---|---|
| `../agreement/agreement_sample.ris` | 226 | **both** reviewers, then adjudicated together |
| `screener_1.ris` | 1,020 | screener 1 alone |
| `screener_2.ris` | 1,017 | screener 2 alone |

226 + 1,020 + 1,017 = 2,263. The halves are stratified by publication year and split
with seed 20260928, so `../scripts/08_split_screening.py` reproduces them exactly.
`split_manifest.json` records which corpus IDs went to whom.

## Order of work

**1 — Agreement sample, both reviewers.** Open `../screening_tool.html`, set
**Phase → Agreement** and your reviewer name, load `../agreement/agreement_sample.ris`,
screen all 226 independently. Export → `agreement_<name>.json`.

**2 — Check agreement.**

    python3 ../scripts/07_kappa.py agreement_<a>.json agreement_<b>.json

If κ is below ~0.60, stop: revise the inclusion criteria and re-pilot on a fresh sample
rather than proceeding. See `../agreement/README.md`.

**3 — Adjudicate.** On the tool's **Resolve** tab, load both files. It computes agreement,
then queues every disagreement and every `maybe` for you to settle together.
Export → `adjudicated_screened_sample.json` into this folder.

**4 — Screen the halves.** Set **Phase → Screening**. Each reviewer loads their own
`screener_N.ris` and screens it alone — *Maybe* is off in this phase. Export →
`screened_articles_screener_1.json` / `_2.json` into this folder.

**5 — Combine.**

    python3 ../scripts/09_combine.py

It reads the adjudicated and `screened_articles_*` files here and writes `../study_corpus/`
(the `agreement_*` files are skipped — the adjudicated file supersedes them). It refuses to build
while any record is unsettled (`maybe`), contradicted by two files, or missing a decision
— that check is the point, so don't bypass it with `--allow-partial` for the final run.

## The files the tool produces

| File | Made on | Contains |
|---|---|---|
| `agreement_<name>.json` | Agreement phase → Export | one reviewer's calls on the 226 sample |
| `screened_articles_<name>.json` | Screening phase → Export | one reviewer's calls on their own half |
| `adjudicated_screened_sample.json` | Resolve tab → Export final decisions | settled decisions for the agreement sample |
