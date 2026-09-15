#!/usr/bin/env python3
"""Convert an RIS export into a clean CSV for screening / analysis.

Handles the quirks seen in bibliometrix/Crossref-style exports:
  * values that wrap onto untagged continuation lines (incl. blank/CRLF lines)
  * JATS / PubMed XML markup inside abstracts (structured sections are kept
    as "Purpose: ... Findings: ...")
  * "NA" placeholders for missing values
  * records without an abstract (dropped, since they can't be screened)
  * duplicate records (by DOI, falling back to title)

Usage:
    python scripts/ris_to_csv.py references/references-2026-09-15.ris
    python scripts/ris_to_csv.py a.ris b.ris -o references/combined.csv
"""

import argparse
import csv
import html
import re
import sys
import unicodedata
from pathlib import Path

TAG_LINE = re.compile(r"^([A-Z][A-Z0-9])  -(?: (.*))?$")

# Output column -> RIS tag(s) it is read from (first non-empty wins).
COLUMNS = {
    "type": ["TY"],
    "authors": ["AU", "A1"],
    "title": ["TI", "T1"],
    "year": ["PY", "Y1"],
    "abstract": ["AB", "N2"],
    "source": ["JF", "T2", "JO"],
    "volume": ["VL"],
    "issue": ["IS"],
    "start_page": ["SP"],
    "end_page": ["EP"],
    "publisher": ["PB"],
    "doi": ["DO"],
}
FIELDNAMES = ["id", "title", "abstract", "authors", "first_author", "n_authors",
              "year", "doi", "type", "source", "volume", "issue",
              "start_page", "end_page", "publisher"]

# Tags whose boundaries separate words; all other tags (italic, sup, ...) are inline.
BLOCK_TAGS = {"p", "sec", "title", "abstracttext", "list", "list-item", "break", "br", "div"}
XML_TAG = re.compile(r"</?([A-Za-z][\w.-]*:)?([A-Za-z][\w.-]*)(?:\s[^<>]*)?/?>")
SECTION_TITLE = re.compile(r"<(?:[\w.-]+:)?title\b[^>]*>(.*?)</(?:[\w.-]+:)?title>", re.S | re.I)
ABSTRACT_LABEL = re.compile(r"<AbstractText\b[^>]*\bLabel=\"([^\"]*)\"[^>]*>", re.I)
LEADING_ABSTRACT = re.compile(r"^\W*(?i:abstract)(?:\s*[:.\-–—]\s*|\s+(?=[A-Z]))")


def parse_ris(text):
    """Yield one dict per record mapping tag -> list of values."""
    record, tag = {}, None
    for raw in text.splitlines():
        line = raw.rstrip("\r\n")
        m = TAG_LINE.match(line)
        if m:
            tag, value = m.group(1), (m.group(2) or "")
            if tag == "ER":
                if record:
                    yield record
                record, tag = {}, None
                continue
            record.setdefault(tag, []).append(value)
        elif tag is not None:
            # Continuation of the previous tag's value.
            record[tag][-1] += "\n" + line
    if record:
        yield record


def clean_markup(value):
    """Strip XML markup, keeping structured-abstract section labels."""
    def title_repl(m):
        label = XML_TAG.sub("", m.group(1)).strip()
        return " " if label.lower() in ("", "abstract", "summary") else f" {label}: "

    value = SECTION_TITLE.sub(title_repl, value)
    value = ABSTRACT_LABEL.sub(lambda m: f" {m.group(1).strip()}: ", value)
    value = XML_TAG.sub(lambda m: " " if m.group(2).lower() in BLOCK_TAGS else "", value)
    return value


def clean_text(value):
    if value is None:
        return ""
    # Pretty-printed XML puts inline elements on their own indented lines;
    # rejoin lines, then remove the space that leaves before punctuation.
    value = " ".join(part.strip() for part in value.splitlines())
    value = html.unescape(clean_markup(value))
    value = unicodedata.normalize("NFC", value)
    value = re.sub(r"\s+", " ", value).strip()
    value = re.sub(r"\s+([,.;:!?)\]])", r"\1", value)
    value = re.sub(r"([(\[])\s+", r"\1", value)
    return "" if value.upper() == "NA" else value


def normalize_doi(doi):
    doi = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", doi.strip(), flags=re.I)
    return doi.lower()


def to_row(record):
    row = {}
    for column, tags in COLUMNS.items():
        values = next((record[t] for t in tags if t in record), [])
        # Some exporters emit one AU line per author, others one line joined by "; ".
        joined = "; ".join(v for v in (clean_text(v) for v in values) if v)
        row[column] = joined

    row["abstract"] = LEADING_ABSTRACT.sub("", row["abstract"])
    row["doi"] = normalize_doi(row["doi"])
    row["year"] = (re.search(r"\d{4}", row["year"]) or [""])[0]

    authors = [a.strip() for a in row["authors"].split(";") if a.strip()]
    row["authors"] = "; ".join(authors)
    row["first_author"] = authors[0] if authors else ""
    row["n_authors"] = len(authors)
    return row


def dedupe_key(row):
    if row["doi"]:
        return "doi:" + row["doi"]
    return "title:" + re.sub(r"[^a-z0-9]", "", row["title"].lower())


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("inputs", nargs="+", type=Path, help="RIS file(s)")
    parser.add_argument("-o", "--output", type=Path,
                        help="output CSV (default: first input with .csv extension)")
    parser.add_argument("--keep-duplicates", action="store_true",
                        help="do not drop records with a repeated DOI/title")
    parser.add_argument("--keep-missing-abstracts", action="store_true",
                        help="do not drop records that have no abstract")
    args = parser.parse_args()
    output = args.output or args.inputs[0].with_suffix(".csv")

    rows, seen, duplicates, no_abstract = [], {}, [], []
    for path in args.inputs:
        text = path.read_text(encoding="utf-8-sig")
        for record in parse_ris(text):
            row = to_row(record)
            # Checked before dedupe so a copy that has an abstract wins.
            if not row["abstract"] and not args.keep_missing_abstracts:
                no_abstract.append(row["title"])
                continue
            key = dedupe_key(row)
            if key in seen and not args.keep_duplicates:
                duplicates.append((row["title"], seen[key]))
                continue
            row["id"] = len(rows) + 1
            seen[key] = row["id"]
            rows.append(row)

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    def missing(col):
        return sum(1 for r in rows if not r[col])

    print(f"Wrote {len(rows)} records to {output}", file=sys.stderr)
    print(f"  missing: abstract={missing('abstract')} doi={missing('doi')} "
          f"title={missing('title')} year={missing('year')} authors={missing('authors')}",
          file=sys.stderr)
    if no_abstract:
        print(f"  dropped {len(no_abstract)} record(s) without an abstract:", file=sys.stderr)
        for title in no_abstract:
            print(f"    - {title[:80]!r}", file=sys.stderr)
    if duplicates:
        print(f"  dropped {len(duplicates)} duplicate(s):", file=sys.stderr)
        for title, kept_id in duplicates:
            print(f"    - {title[:80]!r} (duplicate of id {kept_id})", file=sys.stderr)


if __name__ == "__main__":
    main()
