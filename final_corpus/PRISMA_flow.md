# PRISMA corpus assembly

**Date:** 28 September 2026  
**Records identified:** 3,269  
**Duplicates removed:** 1,006  
**Records for screening:** 2,263 — [`final_corpus.ris`](final_corpus.ris)  

---

## Flow diagram

Vector version for the manuscript: [`prisma_flow_diagram.svg`](prisma_flow_diagram.svg)

```text
  IDENTIFICATION
  ┌────────────────────────────────────────────┐        ┌──────────────────────────────────────────┐
  │ Records identified from databases:         │        │ Records removed before screening:        │
  │     Scopus                 n = 1,900       │        │     Duplicate records removed  n = 1,006 │
  │     IEEE Xplore            n =   840       │───────▶│                                          │
  │     ACM Digital Library    n =   529       │        │                                          │
  │     TOTAL                  n = 3,269       │        │                                          │
  └──────────────────────┬─────────────────────┘        └──────────────────────────────────────────┘
                         │
                         ▼
  SCREENING
  ┌────────────────────────────────────────────┐        ┌──────────────────────────────────────────┐
  │ Records screened            n = 2,263      │───────▶│ Records excluded            n =  ____    │
  └──────────────────────┬─────────────────────┘        └──────────────────────────────────────────┘
                         │
                         ▼
  ┌────────────────────────────────────────────┐        ┌──────────────────────────────────────────┐
  │ Reports sought for retrieval  n =  ____    │───────▶│ Reports not retrieved       n = ____     │
  └──────────────────────┬─────────────────────┘        └──────────────────────────────────────────┘
                         │
                         ▼
  ┌────────────────────────────────────────────┐        ┌──────────────────────────────────────────┐
  │ Reports assessed for eligibility  n = ____ │        │ Reports excluded:                        │
  │                                            │        │     Reason 1                n = ____     │
  │                                            │───────▶│     Reason 2                n = ____     │
  │                                            │        │     Reason 3                n = ____     │
  └──────────────────────┬─────────────────────┘        └──────────────────────────────────────────┘
                         │
                         ▼
  INCLUDED
  ┌────────────────────────────────────────────┐
  │ Studies included in review  n = ____       │
  └────────────────────────────────────────────┘
```

Boxes marked `n = ____` are filled in after title/abstract and full-text screening.

---

## Records per database

| Database            | Identified | Share of search | Removed as duplicate | Retained  |
|---------------------|------------|-----------------|----------------------|-----------|
| Scopus              | 1,900      | 58.1%           | 134                  | 1,766     |
| IEEE Xplore         | 840        | 25.7%           | 477                  | 363       |
| ACM Digital Library | 529        | 16.2%           | 395                  | 134       |
| **Total**           | **3,269**  | **100.0%**      | **1,006**            | **2,263** |

> A record counted as *removed* is not a lost study — the same work is retained via its record
> from another database.

### Per export file

| Export file                                                                 | Database            | Records |
|-----------------------------------------------------------------------------|---------------------|---------|
| acm.bib                                                                     | ACM Digital Library | 529     |
| IEEE Xplore Citation RIS Download 2026.9.28.13.32.1.ris                     | IEEE Xplore         | 100     |
| IEEE Xplore Citation RIS Download 2026.9.28.13.33.40.ris                    | IEEE Xplore         | 100     |
| IEEE Xplore Citation RIS Download 2026.9.28.13.34.16.ris                    | IEEE Xplore         | 100     |
| IEEE Xplore Citation RIS Download 2026.9.28.13.34.42.ris                    | IEEE Xplore         | 100     |
| IEEE Xplore Citation RIS Download 2026.9.28.13.35.51.ris                    | IEEE Xplore         | 100     |
| IEEE Xplore Citation RIS Download 2026.9.28.13.35.8.ris                     | IEEE Xplore         | 100     |
| IEEE Xplore Citation RIS Download 2026.9.28.13.36.17.ris                    | IEEE Xplore         | 100     |
| IEEE Xplore Citation RIS Download 2026.9.28.13.37.2.ris                     | IEEE Xplore         | 40      |
| IEEE Xplore Citation RIS Download 2026.9.28.13.37.27.ris                    | IEEE Xplore         | 100     |
| export_faeceae4-b9ae-472a-ad3b-70c123c9fa6d_2026-09-28T080128.750558238.ris | Scopus              | 1,900   |

---

## Database overlap

Which databases each unique study was found in:

| Found in                                   | Studies | Share |
|--------------------------------------------|---------|-------|
| Scopus                                     | 908     | 40.1% |
| IEEE Xplore + Scopus                       | 583     | 25.8% |
| ACM Digital Library + Scopus               | 391     | 17.3% |
| IEEE Xplore                                | 244     | 10.8% |
| ACM Digital Library                        | 129     | 5.7%  |
| ACM Digital Library + IEEE Xplore + Scopus | 8       | 0.4%  |

Studies supplied by **only one** database: Scopus 908, IEEE Xplore 244, ACM Digital Library 129 — each search contributed material the others missed.

---

## Corpus composition

### Publication type

| Type             | Records | Share |
|------------------|---------|-------|
| Conference paper | 1,537   | 67.9% |
| Journal article  | 639     | 28.2% |
| Book chapter     | 79      | 3.5%  |
| Book             | 7       | 0.3%  |
| Standard         | 1       | 0.0%  |

### Publication year

| Year | Records |                              |
|------|---------|------------------------------|
| 2018 | 18      | █                            |
| 2019 | 44      | ██                           |
| 2020 | 36      | █                            |
| 2021 | 51      | ██                           |
| 2022 | 66      | ██                           |
| 2023 | 152     | ██████                       |
| 2024 | 372     | ██████████████               |
| 2025 | 755     | ███████████████████████████  |
| 2026 | 769     | ████████████████████████████ |

### Top 20 venues

| #  | Records | Venue                                                                                    |
|----|---------|------------------------------------------------------------------------------------------|
| 1  | 90      | Conference on Human Factors in Computing Systems - Proceedings                           |
| 2  | 61      | Lecture Notes in Computer Science                                                        |
| 3  | 48      | IEEE Transactions on Visualization and Computer Graphics                                 |
| 4  | 38      | Proceedings - 2026 IEEE Conference on Virtual Reality and 3D User Interfaces Abstracts a |
| 5  | 37      | IEEE Access                                                                              |
| 6  | 37      | Proceedings of the 2nd International Conference on Artificial Intelligence, Virtual Real |
| 7  | 36      | Proceedings - 2025 IEEE International Symposium on Mixed and Augmented Reality Adjunct,  |
| 8  | 33      | Communications in Computer and Information Science                                       |
| 9  | 30      | Lecture Notes in Computer Science (including subseries Lecture Notes in Artificial Intel |
| 10 | 25      | Proceedings of the 2025 International Conference on Artificial Intelligence, Virtual Rea |
| 11 | 24      | CEUR Workshop Proceedings                                                                |
| 12 | 24      | Proceedings - 2025 IEEE Conference on Virtual Reality and 3D User Interfaces Abstracts a |
| 13 | 23      | Proceedings - 2026 IEEE International Conference on Artificial Intelligence and eXtended |
| 14 | 22      | ACM International Conference Proceeding Series                                           |
| 15 | 15      | Proceedings of the ACM Symposium on Virtual Reality Software and Technology, VRST        |
| 16 | 15      | Lecture Notes in Networks and Systems                                                    |
| 17 | 12      | International Journal of Human-Computer Interaction                                      |
| 18 | 12      | Proceedings - 2024 IEEE International Symposium on Mixed and Augmented Reality Adjunct,  |
| 19 | 11      | Frontiers in Virtual Reality                                                             |
| 20 | 11      | UIST 2025 - Proceedings of the 38th Annual ACM Symposium on User Interface Software and  |

### Metadata completeness

| Field            | Records | Coverage |
|------------------|---------|----------|
| DOI present      | 2,184   | 96.5%    |
| Abstract present | 2,260   | 99.9%    |
| Year present     | 2,263   | 100.0%   |

---

## Files

| File                      | Contents                                                               |
|---------------------------|------------------------------------------------------------------------|
| `final_corpus.ris`        | The corpus: 2,263 records — **screening input**                        |
| `final_corpus.json`       | Same records as JSON, with merge provenance                            |
| `catalog_all_records.csv` | All 3,269 source records, each mapped to its corpus ID and disposition |
| `screening_decisions.md`  | Record of the manual duplicate screening                               |
| `prisma_stats.json`       | Machine-readable version of every count here                           |
| `prisma_flow_diagram.svg` | Flow diagram for the manuscript                                        |
| `scripts/`                | The pipeline that produced all of the above                            |

Each record in `final_corpus.ris` carries `ID` / `N1  - corpus_id` (stable `Cnnnn` identifier),
`N1  - found_in` (contributing databases) and `N1  - source_records_merged` (how many source
records it represents).
