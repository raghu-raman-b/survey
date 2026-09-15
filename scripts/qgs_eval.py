#!/usr/bin/env python3
"""Evaluate a search string against the quasi-gold standard (QGS).

Takes the gold set and one or more search-result CSV exports (Scopus, WoS, IEEE,
ACM, ...), matches them on titles only, and reports:

  sensitivity  gold studies retrieved / gold studies      (recall of the search)
  precision    gold studies retrieved / records retrieved  (a lower bound: retrieved
               records outside the QGS may also be relevant)
  NNR          number needed to read = 1 / precision

Accuracy and specificity are not reported: they need true negatives, i.e. labels for
every record the search did not retrieve, which a QGS does not provide.

Matching:
  exact      titles equal after normalisation (case, accents, punctuation, markup, spacing)
  fuzzy      similarity >= --threshold (default 0.90); counted as retrieved
  near_miss  similarity >= --near-threshold, or one title is a prefix of the other
             (e.g. a truncated subtitle); NOT counted, listed for manual checking

Usage:
    ./bin/python scripts/qgs_eval.py search/scopus.csv search/wos.csv
    ./bin/python scripts/qgs_eval.py search/*.csv --gold screening/llm_gold_set.csv --name string_v2
"""

import argparse
import csv
import html
import io
import re
import sys
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
csv.field_size_limit(sys.maxsize)

# Known title headers across databases and reference managers, in priority order.
TITLE_COLUMNS = ["title", "article title", "document title", "paper title", "primary title", "ti", "display_name"]
# Headers that contain "title" but name the venue or a variant, not the article.
NOT_ARTICLE_TITLE = re.compile(r"source|publication|journal|book|series|conference|proceedings|"
                               r"short|abbrev|translated|original", re.I)
MIN_PREFIX_WORDS = 3


def normalize_title(title):
    title = unicodedata.normalize("NFKD", html.unescape(title or ""))
    title = "".join(ch for ch in title if not unicodedata.combining(ch)).casefold()
    title = re.sub(r"<[^>]+>", " ", title)
    title = re.sub(r"[\W_]+", " ", title)
    return title.strip()


def read_csv(path):
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    header = text.split("\n", 1)[0]
    delimiter = max([",", ";", "\t"], key=header.count)
    reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=delimiter)
    return reader.fieldnames or [], list(reader)


def find_title_column(path, fieldnames, override):
    by_lower = {f.strip().lower(): f for f in fieldnames}
    if override:
        if override.strip().lower() in by_lower:
            return by_lower[override.strip().lower()]
        sys.exit(f"{path}: no column {override!r}. Columns: {fieldnames}")
    for name in TITLE_COLUMNS:
        if name in by_lower:
            return by_lower[name]
    candidates = [f for f in fieldnames if "title" in f.lower() and not NOT_ARTICLE_TITLE.search(f)]
    if len(candidates) == 1:
        return candidates[0]
    sys.exit(f"{path}: cannot tell which column holds article titles "
             f"(candidates: {candidates or 'none'}). Pass --title-column. Columns: {fieldnames}")


def load_titles(path, override):
    fieldnames, rows = read_csv(path)
    column = find_title_column(path, fieldnames, override)
    return column, rows, [(row.get(column) or "").strip() for row in rows]


def similarity(a, b):
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def is_prefix_match(a, b):
    shorter, longer = sorted((a, b), key=len)
    return (shorter != longer and len(shorter.split()) >= MIN_PREFIX_WORDS
            and longer.startswith(shorter + " "))


def best_match(norm, retrieved, near_threshold):
    """Return (score, retrieved entry, prefix_flag) for the closest retrieved title."""
    best_score, best_entry, prefix = 0.0, None, False
    for entry in retrieved:
        cand = entry["norm"]
        if is_prefix_match(norm, cand):
            score = similarity(norm, cand)
            if not prefix or score > best_score:
                best_score, best_entry, prefix = score, entry, True
            continue
        if prefix:
            continue
        # Cheap upper bounds first; the full ratio is the expensive part.
        matcher = SequenceMatcher(None, norm, cand, autojunk=False)
        if matcher.real_quick_ratio() < max(near_threshold, best_score):
            continue
        if matcher.quick_ratio() < max(near_threshold, best_score):
            continue
        score = matcher.ratio()
        if score > best_score:
            best_score, best_entry = score, entry
    return best_score, best_entry, prefix


def pct(part, whole):
    return f"{100 * part / whole:.1f}%" if whole else "n/a"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("search_results", nargs="+", type=Path, help="search-result CSV export(s)")
    parser.add_argument("--gold", type=Path, default=ROOT / "screening/llm_gold_set.csv")
    parser.add_argument("--title-column", help="title column in the search-result CSVs (auto-detected)")
    parser.add_argument("--threshold", type=float, default=0.90, help="fuzzy match threshold (default 0.90)")
    parser.add_argument("--near-threshold", type=float, default=0.75,
                        help="report near misses at or above this similarity (default 0.75)")
    parser.add_argument("--target-sensitivity", type=float, default=0.80,
                        help="sensitivity the search string should reach (default 0.80)")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "qgs")
    parser.add_argument("--name", default="qgs", help="output file prefix, e.g. a search string version")
    args = parser.parse_args()

    _, gold_rows, gold_titles = load_titles(args.gold, None)

    retrieved, by_norm, sources, total_rows = [], {}, [], 0
    for path in args.search_results:
        column, rows, titles = load_titles(path, args.title_column)
        total_rows += len(rows)
        kept = 0
        for title in titles:
            norm = normalize_title(title)
            if not norm:
                continue
            kept += 1
            if norm in by_norm:
                by_norm[norm]["files"].add(path.name)
                continue
            by_norm[norm] = {"norm": norm, "title": title, "files": {path.name}}
            retrieved.append(by_norm[norm])
        sources.append(f"{path} ({len(rows)} rows, {kept} with titles, column {column!r})")
    if not retrieved:
        sys.exit("No titles found in the search results.")

    matches = []
    for row, title in zip(gold_rows, gold_titles):
        norm = normalize_title(title)
        if norm in by_norm:
            entry, score, match_type = by_norm[norm], 1.0, "exact"
        else:
            score, entry, prefix = best_match(norm, retrieved, args.near_threshold)
            if entry is not None and not prefix and score >= args.threshold:
                match_type = "fuzzy"
            elif entry is not None and (prefix or score >= args.near_threshold):
                match_type = "near_miss"
            else:
                match_type, entry = "none", None
        matches.append({
            "gold_id": row.get("id", ""), "gold_title": title, "year": row.get("year", ""),
            "match_type": match_type, "similarity": f"{score:.3f}" if entry else "",
            "matched_title": entry["title"] if entry else "",
            "matched_in": ";".join(sorted(entry["files"])) if entry else "",
        })

    n_gold, n_retrieved = len(matches), len(retrieved)
    exact = sum(m["match_type"] == "exact" for m in matches)
    fuzzy = sum(m["match_type"] == "fuzzy" for m in matches)
    near = sum(m["match_type"] == "near_miss" for m in matches)
    found = exact + fuzzy
    sensitivity = found / n_gold if n_gold else 0.0
    precision = found / n_retrieved

    args.out_dir.mkdir(parents=True, exist_ok=True)
    matches_path = args.out_dir / f"{args.name}_matches.csv"
    with matches_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(matches[0]))
        writer.writeheader()
        writer.writerows(matches)

    verdict = "meets" if sensitivity >= args.target_sensitivity else "BELOW"
    lines = [
        "QGS evaluation of search string",
        "=" * 60,
        f"Generated:   {datetime.now():%Y-%m-%d %H:%M:%S}",
        f"Gold set:    {args.gold} ({n_gold} studies)",
        "Search results:",
        *[f"  {s}" for s in sources],
        f"  {total_rows} rows total, {n_retrieved} unique titles after normalisation",
        f"Matching:    exact, fuzzy >= {args.threshold}, near miss >= {args.near_threshold} or title prefix",
        "",
        "Metrics",
        "-" * 60,
        f"  gold studies retrieved         {found:>5} of {n_gold}  ({exact} exact, {fuzzy} fuzzy)",
        f"  sensitivity (recall)           {pct(found, n_gold):>7}   {verdict} target {args.target_sensitivity:.0%}",
        f"  sensitivity, exact only        {pct(exact, n_gold):>7}",
        f"  sensitivity, if near misses    {pct(found + near, n_gold):>7}   ({near} near miss(es) to check)",
        f"    are confirmed",
        f"  precision (QGS lower bound)    {100 * precision:>6.2f}%",
        f"  NNR (records read per gold hit) {(1 / precision if precision else float('inf')):>6.1f}",
        f"  gold studies missed            {n_gold - found - near:>5}",
        "",
        "Precision counts only QGS studies as relevant, so the true precision of the",
        "search is at least this value. Accuracy/specificity need labels for records",
        "the search did not retrieve, which a QGS does not provide.",
    ]

    def section(title, kind, show_match):
        rows = [m for m in matches if m["match_type"] == kind]
        out = ["", f"{title} ({len(rows)})", "-" * 60]
        for m in rows:
            out.append(f"  [{m['gold_id']:>3}] {m['year']} {m['gold_title']}")
            if show_match:
                out.append(f"        ~ {m['similarity']} {m['matched_title']}  ({m['matched_in']})")
        return out if rows else out + ["  (none)"]

    lines += section("Missed: refine the search string for these", "none", False)
    lines += section("Near misses: check manually, not counted as retrieved", "near_miss", True)
    lines += section("Fuzzy matches: verify these pairs", "fuzzy", True)
    report = "\n".join(lines) + "\n"
    report_path = args.out_dir / f"{args.name}_report.txt"
    report_path.write_text(report, encoding="utf-8")
    print(report)
    print(f"Wrote {report_path} and {matches_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
