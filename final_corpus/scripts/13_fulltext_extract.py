#!/usr/bin/env python3
"""Pull the parts of each full-text PDF that screening needs, ready for an LLM summary.

    ../../.venv/bin/python 13_fulltext_extract.py                 # Raghu's papers
    ../../.venv/bin/python 13_fulltext_extract.py --screener Nikhil --pdfs ../../other-pdfs
    ../../.venv/bin/python 13_fulltext_extract.py --only C0001,C0003   # re-run a few

Needs PyMuPDF (`pip install pymupdf`, already in the repo's .venv).

Reads
  fulltext/fulltext_corpus.json      which records are yours and still to screen
  ../../survey-papers/*.pdf          the PDFs (any file names)
  ../../survey-papers/ref.rtf        Zotero bibliography of those PDFs (cross-check only)

Writes, under fulltext/extracts/
  <ID>/extract.md                    what the LLM reads: metadata, format signals,
                                     captions, and the paper text minus related work,
                                     references and appendices, with page markers
  <ID>/meta.json                     the same facts as data, plus figure file names
  <ID>/figures/*.jpg                 each figure cropped from the page, for you to view
  manifest.json                      one row per record: matched PDF, flags, sizes
  match_report.csv                   PDF <-> record matching, for checking by hand

A PDF is matched to a record by DOI (file name, PDF metadata or first pages), then by
title. Springer proceedings volumes (one PDF per book) are cut down to the paper's own
pages using the record's page range and a title search. Anything that can't be matched,
located or read is flagged in the manifest and skipped, never guessed.
"""
import argparse, collections, csv, datetime, difflib, json, os, re, shutil, sys, unicodedata

try:
    import pymupdf
except ImportError:
    sys.exit("PyMuPDF is missing. Run with the repo's venv: ../../.venv/bin/python 13_fulltext_extract.py")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                       # final_corpus/
REPO = os.path.dirname(ROOT)

TEXT_CAP = 60000          # max characters of paper text per extract (~15k tokens)
SECTION_MIN = 2500        # trimming never cuts a section below this
VOLUME_PAGES = 60         # a PDF longer than this is treated as a whole proceedings volume
FIG_ZOOM = 1.6            # render scale for figure crops (1.0 = 72 dpi)

# ---------------------------------------------------------------- text helpers

def norm(s):
    """Lowercase letters and digits only, so titles match despite spacing or hyphenation."""
    s = unicodedata.normalize("NFKD", s or "")
    return re.sub(r"[^a-z0-9]", "", s.lower())

def clean_doi(d):
    d = (d or "").strip().lower()
    d = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", d)
    return d.rstrip(".,;)]}")

DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s\"<>{}]+", re.I)

def rtf_to_text(s):
    s = re.sub(r"\\uc0\\u(\d+)\{\}", lambda m: chr(int(m.group(1))), s)
    s = re.sub(r"\\u(-?\d+)\??", lambda m: chr(int(m.group(1)) % 65536), s)
    s = re.sub(r"\\[a-z]+-?\d* ?", "", s)
    return s.replace("{", "").replace("}", "").strip()

def parse_ref_rtf(path):
    if not os.path.exists(path):
        return []
    raw = open(path, encoding="utf-8", errors="replace").read()
    out = []
    for chunk in raw.split("\\\n"):
        t = rtf_to_text(chunk)
        if len(t) < 20:
            continue
        m = DOI_RE.search(t)
        # APA: Authors (Year). Title. Venue...  -- title is the text after "(year). "
        tm = re.search(r"\((\d{4}|n\.d\.)[a-z]?\)\.\s*(.+?)(?:\.\s|\?\s|$)", t)
        out.append({"text": t, "doi": clean_doi(m.group(0)) if m else "",
                    "title": tm.group(2) if tm else ""})
    return out

# ---------------------------------------------------------------- page reading

BOLD_FONT = re.compile(r"(bold|black|heavy|semibold|demi|cmbx|\bbd\b|-bd|medi|TB$|,B$)", re.I)

def page_lines(page):
    """Text blocks of a page, each with its lines and style facts. Keeps PDF reading order."""
    d = page.get_text("dict", flags=pymupdf.TEXTFLAGS_DICT | pymupdf.TEXT_DEHYPHENATE)
    blocks = []
    for b in d["blocks"]:
        if b.get("type") != 0:
            continue
        lines = []
        for l in b["lines"]:
            spans = l["spans"]
            text = "".join(s["text"] for s in spans).strip()
            if not text:
                continue
            vis = [s for s in spans if s["text"].strip()]
            n = sum(len(s["text"]) for s in vis) or 1
            bold = sum(len(s["text"]) for s in vis
                       if (s["flags"] & 16) or BOLD_FONT.search(s["font"])) / n > 0.6
            size = round(max(s["size"] for s in vis), 1)
            lines.append({"text": text, "size": size, "bold": bold, "bbox": l["bbox"]})
        if lines:
            blocks.append({"bbox": b["bbox"], "lines": lines})
    # Springer and others set a heading's number apart from its title ("1" / "Introduction"):
    # join a bare number line onto the next styled line, within or across blocks
    flat = [(bi, li) for bi, b in enumerate(blocks) for li in range(len(b["lines"]))]
    for (bi, li), (bj, lj) in zip(flat, flat[1:]):
        a, nxt = blocks[bi]["lines"][li], blocks[bj]["lines"][lj]
        if BARE_NUM.fullmatch(a["text"]) and (a["bold"] or nxt["text"].isupper()) and nxt["bold"] == a["bold"] \
                and abs(nxt["size"] - a["size"]) < 0.6 and re.match(r"[A-Z]", nxt["text"]):
            nxt["text"] = a["text"] + " " + nxt["text"]
            a["text"] = ""
    for b in blocks:
        b["lines"] = [l for l in b["lines"] if l["text"]]
    return [b for b in blocks if b["lines"]]

BARE_NUM = re.compile(r"(\d{1,2}(\.\d{1,2}){0,3}\.?|[IVX]{1,5}\.)")

def body_size(pages):
    c = collections.Counter()
    for blocks in pages:
        for b in blocks:
            for l in b["lines"]:
                c[l["size"]] += len(l["text"])
    return c.most_common(1)[0][0] if c else 10.0

# ---------------------------------------------------------------- headings & sections

NUM = r"(?:(?:\d{1,2}(?:\.\d{1,2}){0,3})\.?|[IVX]{1,5}\.|[A-H]\.)"
NUMBERED = re.compile(rf"^({NUM})\s*([A-Z][^\n]{{1,110}})$")
KNOWN = re.compile(
    r"^(abstract|introduction|related work|background|method(s|ology)?|materials and methods|"
    r"system( design| overview)?|implementation|evaluation|experiments?|results|discussion|"
    r"limitations?.*|conclusions?.*|future work|references|bibliography|acknowledge?ments?|"
    r"appendix.*|appendices|keywords|ccs concepts|declaration.*|funding.*|data availability.*|"
    r"author contributions.*|conflicts? of interest.*|credit authorship.*|supplementary.*|"
    r"institutional review board statement|informed consent statement|index terms)\s*:?$", re.I)
CAPTION = re.compile(r"^(fig\.?|figure|table)\s*(\d+|[ivx]+)\s*[.:|\-–—]", re.I)

def is_heading(line, body):
    t = line["text"]
    if len(t) > 110 or CAPTION.match(t) or t.endswith((",", ";")) or len(t.split()) > 16:
        return None
    styled = line["bold"] or line["size"] >= body + 0.8 or (t.isupper() and len(t) > 3)
    if KNOWN.match(t) and (styled or t.isupper() or re.fullmatch(r"(?i)references|bibliography", t)):
        return {"num": "", "title": t.rstrip(":")}
    m = NUMBERED.match(t)
    if not m or not re.search(r"[a-zA-Z]{3}", m.group(2)):
        return None
    num = m.group(1).rstrip(".")
    parts = num.split(".")
    if parts[0].isdigit() and (int(parts[0]) > 20 or any(int(p) > 30 for p in parts if p.isdigit())):
        return None                               # table values like "74.60 LLMR"
    # IEEE sets "I. Introduction" / "A. Subsection" in small caps at body size, unbolded
    ieee = re.fullmatch(r"[IVX]{1,5}\.|[A-H]\.", m.group(1)) and len(t.split()) <= 12 and not t.endswith(".")
    if styled or ieee:
        return {"num": num, "title": m.group(2).strip()}
    return None

def continues_number(num, next_text):
    """True if next_text starts a new numbered heading rather than wrapping this one.
    '3D ASSETS' after '4 INCORPORATING …' is a wrap: 3 doesn't follow 4."""
    m = NUMBERED.match(next_text)
    if not m:
        return False
    a, b = num.split(".")[0], m.group(1).rstrip(".").split(".")[0]
    if a.isdigit() and b.isdigit():
        return int(b) >= int(a)
    return True

def level_of(num):
    if not num:
        return 1
    if re.fullmatch(r"[IVX]+|\d+", num):
        return 1
    if re.fullmatch(r"[A-H]", num):
        return 2
    return num.count(".") + 1

RELATED = re.compile(r"related (work|research|stud)|literature|prior work|previous work|state of the art|state-of-the-art", re.I)
BACKMATTER = re.compile(r"^(references|bibliography|acknowledge?ments?|appendix|appendices|declaration|funding|"
                        r"data availability|author contributions|conflicts? of interest|credit authorship|"
                        r"supplementary|institutional review board|informed consent|ethics statement)", re.I)
INTRO = re.compile(r"introduction", re.I)

def classify(title):
    if BACKMATTER.match(title):
        return "back"
    if RELATED.search(title):
        return "related"
    if INTRO.search(title):
        return "intro"
    return "body"

# ---------------------------------------------------------------- figures

def column_of(bbox, W, single_col):
    x0, _, x1, _ = bbox
    if single_col or (x1 - x0) > 0.55 * W:
        return (0.04 * W, 0.96 * W)
    return (0.03 * W, W / 2 + 4) if (x0 + x1) / 2 < W / 2 else (W / 2 - 4, 0.97 * W)

def overlaps_x(b, col):
    return min(b[2], col[1]) - max(b[0], col[0]) > 10

def find_figures(page, blocks, body):
    """Crop rectangles for each 'Figure N' caption: the graphics above it, down to the caption."""
    W, H = page.rect.width, page.rect.height
    wide = [b for b in blocks if sum(len(l["text"]) for l in b["lines"]) > 200]
    single_col = bool(wide) and sum((b["bbox"][2] - b["bbox"][0]) > 0.55 * W for b in wide) > len(wide) / 2
    try:
        graphics = [pymupdf.Rect(i["bbox"]) for i in page.get_image_info()]
        draws = page.get_drawings()
        if len(draws) < 6000:
            graphics += [pymupdf.Rect(d["rect"]) for d in draws if d["rect"].width * d["rect"].height > 4]
    except Exception:
        graphics = []
    figs = []
    for bi, b in enumerate(blocks):
        first = b["lines"][0]["text"]
        m = CAPTION.match(first)
        if not m or m.group(1).lower().startswith("tab"):
            continue
        cap = " ".join(l["text"] for l in b["lines"])
        col = column_of(b["bbox"], W, single_col)
        cy0 = b["bbox"][1]
        top = 0.04 * H
        for o in blocks:                      # body paragraphs or other captions above, same column
            if o is b or o["bbox"][3] > cy0 + 2 or not overlaps_x(o["bbox"], col):
                continue
            chars = sum(len(l["text"]) for l in o["lines"])
            sizes = [l["size"] for l in o["lines"]]
            is_par = chars > 180 and abs(sum(sizes) / len(sizes) - body) < 0.7
            if is_par or CAPTION.match(o["lines"][0]["text"]):
                top = max(top, o["bbox"][3])
        g = [r for r in graphics if r.y1 <= cy0 + 3 and r.y0 >= top - 3 and overlaps_x(r, col)]
        if g:
            top = max(top, min(r.y0 for r in g) - 4)
        clip = pymupdf.Rect(col[0], top, col[1], b["bbox"][3] + 2)
        if clip.height - (b["bbox"][3] - cy0) < 30:
            # caption sits above its figure: take the area below it, to the next paragraph
            bottom = 0.96 * H
            for o in blocks:
                if o["bbox"][1] > b["bbox"][3] and overlaps_x(o["bbox"], col) and \
                        sum(len(l["text"]) for l in o["lines"]) > 180:
                    bottom = min(bottom, o["bbox"][1])
            clip = pymupdf.Rect(col[0], cy0 - 2, col[1], bottom)
        figs.append({"block": bi, "num": m.group(2), "caption": cap, "clip": clip})
    return figs

# ---------------------------------------------------------------- matching

def load_records(corpus_path, screener):
    data = json.load(open(corpus_path, encoding="utf-8"))
    recs = data["records"]
    todo = [r for r in recs if r.get("assigned_to") == screener
            and r["retrieval"]["kind"] == "acquired" and not r.get("preset")]
    return recs, todo

def pdf_probe(path):
    doc = pymupdf.open(path)
    head = ""
    for i in range(min(2, doc.page_count)):
        head += doc[i].get_text("text") + "\n"
    meta = doc.metadata or {}
    return doc, head, meta

def match_pdfs(pdf_dir, todo, all_recs):
    by_doi = {clean_doi(r["doi"]): r for r in all_recs if r.get("doi")}
    mine = {r["id"] for r in todo}
    title_idx = [(norm(r["title"]), r) for r in all_recs if len(norm(r["title"])) >= 15]
    rows, single, volumes = [], {}, collections.defaultdict(list)
    files = sorted(f for f in os.listdir(pdf_dir) if f.lower().endswith(".pdf"))
    for f in files:
        stem = f[:-4]
        path = os.path.join(pdf_dir, f)
        try:
            doc, head, meta = pdf_probe(path)
        except Exception as e:
            rows.append({"pdf": f, "status": "unreadable", "detail": str(e)[:120]})
            continue
        pages = doc.page_count
        found, how = [], ""
        # 1) DOI in the file name (ACM 3613904.3642579, De Gruyter 10.1515_x, Springer ISBN)
        s = stem.lower().replace(" (1)", "")
        for d, r in by_doi.items():
            suffix = d.split("/", 1)[-1]
            if s in (suffix, d.replace("/", "_")) or (re.fullmatch(r"97[89][-\d]+", s) and suffix.startswith(s + "_")):
                found.append(r)
        if found:
            how = "doi-in-filename"
        # 2) DOI printed in PDF metadata or first two pages
        if not found and pages <= VOLUME_PAGES:
            blob = " ".join(str(v) for v in meta.values()) + " " + head
            for m in DOI_RE.finditer(blob):
                r = by_doi.get(clean_doi(m.group(0)))
                if r and r not in found:
                    found.append(r)
            how = "doi-in-pdf" if found else how
            if len(found) > 1:                # cited DOIs on page 1: keep the one whose title is there
                hn = norm(head)
                found = [r for r in found if norm(r["title"])[:40] in hn] or found[:1]
        # 3) title on the first pages, or in PDF metadata
        if not found and pages <= VOLUME_PAGES:
            hn = norm(head)
            hits = [r for t, r in title_idx if t[:60] in hn]
            if hits:
                found, how = [max(hits, key=lambda r: len(r["title"]))], "title-on-page"
            elif meta.get("title"):
                mt = norm(meta["title"])
                best = max(title_idx, key=lambda tr: difflib.SequenceMatcher(None, mt, tr[0]).ratio())
                if len(mt) > 15 and difflib.SequenceMatcher(None, mt, best[0]).ratio() > 0.88:
                    found, how = [best[1]], "title-in-metadata"
        is_volume = pages > VOLUME_PAGES
        if is_volume and not found:
            rows.append({"pdf": f, "pages": pages, "status": "volume-unmatched",
                         "detail": "no record DOI carries this ISBN; title search runs below"})
            volumes[f] = []
            continue
        if not found:
            rows.append({"pdf": f, "pages": pages, "status": "unmatched", "detail": (meta.get("title") or head[:80]).replace("\n", " ")})
            continue
        for r in found:
            rows.append({"pdf": f, "pages": pages, "status": "matched", "how": how, "id": r["id"],
                         "mine": r["id"] in mine, "title": r["title"][:90]})
            if is_volume:
                volumes[f].append(r)
            else:
                single.setdefault(r["id"], []).append(f)
    return rows, single, volumes

_PAGE_TEXT = {}

def volume_pages(doc):
    """Normalised text of every page of a volume, read once."""
    key = doc.name
    if key not in _PAGE_TEXT:
        _PAGE_TEXT[key] = [norm(p.get_text("text")[:4000]) for p in doc]
    return _PAGE_TEXT[key]

def locate_in_volume(doc, rec):
    """PDF page range of one paper inside a proceedings volume, or None."""
    t = norm(rec["title"])[:45]
    if len(t) < 15:
        return None
    texts = volume_pages(doc)
    hits = [i for i, txt in enumerate(texts) if t in txt[:900]]
    # skip table-of-contents pages: the paper's first page also has an abstract
    starts = [i for i in hits if "abstract" in texts[i]]
    if not starts:
        return None
    start = starts[0]
    try:
        n = int(rec["end_page"]) - int(rec["start_page"]) + 1
    except (TypeError, ValueError):
        n = 0
    if not 1 <= n <= 60:
        n = 0
        for j in range(start + 1, min(start + 40, doc.page_count)):
            if re.search(r"^\s*references\s*$", doc[j].get_text("text"), re.I | re.M):
                n = j - start + 1
                break
        n = n or 20
    return start, min(start + n, doc.page_count) - 1

# ---------------------------------------------------------------- one paper

TRACK = re.compile(r"\b(adjunct|extended abstracts?|late[- ]breaking|posters?|demos?|demonstrations?|"
                   r"work[- ]in[- ]progress|wip|short papers?|doctoral consortium|workshops?|companion|"
                   r"student research competition|abstracts)\b", re.I)
STOP_EN = set("the of and to in a is that for with on as by this we are be from an or which at".split())

def build_extract(rec, pdf_name, pdf_path, first, last, out_dir, how):
    doc = pymupdf.open(pdf_path)
    W0 = doc[first].rect
    pages = [page_lines(doc[i]) for i in range(first, last + 1)]
    body = body_size(pages)
    flags = []
    total_chars = sum(len(l["text"]) for p in pages for b in p for l in b["lines"])
    if total_chars < 2000:
        flags.append("no-text (scanned?)")

    # ---- format signals: header/footer of the first two pages, track words, ACM reference line
    hf = []
    for k, blocks in enumerate(pages[:2]):
        H = doc[first + k].rect.height
        for b in blocks:
            if b["bbox"][1] < 0.08 * H or b["bbox"][3] > 0.90 * H:
                t = " ".join(l["text"] for l in b["lines"])
                if 3 < len(t) < 300:
                    hf.append(f"p.{first + k + 1}: {t}")
    head_txt = "\n".join(" ".join(l["text"] for l in b["lines"]) for p in pages[:2] for b in p)
    acm = re.search(r"ACM Reference Format:?\s*(.{0,500}?)(https?://doi\S+|\n\n|$)", head_txt, re.S)
    track = sorted({m.group(0).lower() for m in TRACK.finditer(" ".join(hf) + " " + rec.get("venue", "")
                                                               + " " + (acm.group(1) if acm else ""))})
    words = re.findall(r"[a-zA-Z]+", head_txt.lower())
    en_ratio = round(sum(w in STOP_EN for w in words) / max(1, len(words)), 3)
    if words and en_ratio < 0.08:
        flags.append("maybe-not-English")

    # ---- figures, then the running text
    fig_dir = os.path.join(out_dir, "figures")
    figures, fig_blocks, fig_rects = [], set(), collections.defaultdict(list)
    for k, blocks in enumerate(pages):
        page = doc[first + k]
        for fg in find_figures(page, blocks, body):
            fig_blocks.add((k, fg["block"]))
            fig_rects[k].append(fg["clip"])
            name = f"fig{fg['num']}_p{first + k + 1}.jpg"
            try:
                os.makedirs(fig_dir, exist_ok=True)
                pix = page.get_pixmap(matrix=pymupdf.Matrix(FIG_ZOOM, FIG_ZOOM), clip=fg["clip"] & page.rect)
                pix.save(os.path.join(fig_dir, name), jpg_quality=78)
            except Exception:
                name = None
            figures.append({"label": f"Figure {fg['num']}", "page": first + k + 1,
                            "caption": fg["caption"], "file": name and f"figures/{name}"})
    table_caps = []

    segs = []          # (kind, payload): ("h", heading dict) or ("t", text, page)
    for k, blocks in enumerate(pages):
        H = doc[first + k].rect.height
        for bi, b in enumerate(blocks):
            if (k, bi) in fig_blocks:
                continue
            x0, y0, x1, y1 = b["bbox"]
            if y1 < 0.06 * H or y0 > 0.94 * H:                     # running header / footer
                continue
            r = pymupdf.Rect(b["bbox"])
            if any((r & fr).get_area() > 0.6 * max(r.get_area(), 1) for fr in fig_rects[k]):
                continue                                           # labels inside a figure
            first_line = b["lines"][0]["text"]
            if CAPTION.match(first_line) and first_line.lower().startswith("tab"):
                table_caps.append({"label": first_line.split(":")[0].split(".")[0][:12],
                                   "page": first + k + 1, "caption": " ".join(l["text"] for l in b["lines"])[:400]})
            buf = []
            lines = b["lines"]
            i = 0
            while i < len(lines):
                h = is_heading(lines[i], body)
                if h:
                    if buf:
                        segs.append(("t", " ".join(buf), first + k + 1)); buf = []
                    # wrapped headings: following lines in the same style join the title
                    while i + 1 < len(lines) and not continues_number(h["num"], lines[i + 1]["text"]) \
                            and lines[i + 1]["bold"] == lines[i]["bold"] and lines[i + 1]["size"] == lines[i]["size"] \
                            and len(lines[i + 1]["text"]) < 60 and h["num"] and lines[i]["text"].isupper() == lines[i + 1]["text"].isupper() \
                            and (lines[i]["bold"] or lines[i]["size"] >= body + 0.8):
                        i += 1
                        h["title"] += " " + lines[i]["text"]
                    h["page"] = first + k + 1
                    segs.append(("h", h))
                else:
                    buf.append(lines[i]["text"])
                i += 1
            if buf:
                segs.append(("t", " ".join(buf), first + k + 1))

    # ---- group into sections
    sections = [{"num": "", "title": "(front matter: title, authors, abstract)", "page": first + 1,
                 "level": 1, "cls": "front", "parts": []}]
    seen_back = False
    top_cls = "front"
    for s in segs:
        if s[0] == "h":
            h = s[1]
            lvl = level_of(h["num"])
            cls = classify(h["title"])
            if h["title"].lower().startswith("abstract"):
                cls = "front"
            if lvl > 1 and cls == "body":
                cls = top_cls                  # subsections follow their parent
            if cls == "back":
                seen_back = True
            if seen_back:
                cls = "back"
            if lvl == 1:
                top_cls = cls
            sections.append({"num": h["num"], "title": h["title"], "page": h["page"], "level": lvl,
                             "cls": cls, "parts": []})
        else:
            sec = sections[-1]
            if not sec["parts"] or sec["parts"][-1][1] != s[2]:
                sec["parts"].append([f"⟨p.{s[2]}⟩ ", s[2]])
            sec["parts"][-1][0] += s[1] + "\n"

    n_heads = len(sections) - 1
    if n_heads < 3:
        flags.append("few-headings (text kept whole up to references)")
        whole, stop = [], False
        for s in sections:
            for p in s["parts"]:
                txt = p[0]
                m = re.search(r"\n(?:⟨p\.\d+⟩ )?(references|bibliography)\s*\n", txt, re.I)
                if m:
                    whole.append(txt[:m.start()]); stop = True; break
                whole.append(txt)
            if stop:
                break
        kept = [{"head": "(full text, no section structure found)", "text": "".join(whole), "cls": "body"}]
    else:
        kept = []
        for s in sections:
            text = "".join(p[0] for p in s["parts"])
            if s["cls"] in ("related", "back"):
                continue
            if s["cls"] == "front" and s is sections[0]:
                text = text[:6000]
            head = ("#" * min(s["level"] + 2, 5)) + f" {s['num']} {s['title']}".replace("  ", " ") + f"  [p.{s['page']}]"
            kept.append({"head": head, "text": text, "cls": s["cls"]})

    # ---- trim to the cap: cut the middle of the longest sections first, intro before others
    def size():
        return sum(len(k["text"]) for k in kept)
    trimmed = 0
    while size() > TEXT_CAP:
        cand = [k for k in kept if len(k["text"]) > SECTION_MIN + 300]
        if not cand:
            break
        k = max(cand, key=lambda k: len(k["text"]) * (1.6 if k["cls"] == "intro" else 1))
        over = size() - TEXT_CAP
        cut = min(over + 200, len(k["text"]) - SECTION_MIN)
        keep_head = (len(k["text"]) - cut) // 2
        k["text"] = k["text"][:keep_head] + f"\n[… {cut} characters omitted …]\n" + k["text"][keep_head + cut:]
        trimmed += cut
    if trimmed:
        flags.append(f"trimmed {trimmed} chars")

    # ---- write
    authors = rec.get("authors") or []
    pg_rec = f"{rec.get('start_page')}–{rec.get('end_page')}" if rec.get("start_page") else "not given"
    out = [f"# {rec['id']} — {rec['title']}", "",
           "## Record metadata (from the search export)",
           f"- Type: {rec.get('type')}  |  Year: {rec.get('year')}  |  Venue: {rec.get('venue') or '—'}",
           f"- Authors: {'; '.join(authors[:8])}{' et al.' if len(authors) > 8 else ''}",
           f"- DOI: {rec.get('doi') or '—'}  |  Pages in record: {pg_rec}  |  Found in: {', '.join(rec.get('found_in') or [])}",
           f"- Keywords: {', '.join((rec.get('keywords') or [])[:15]) or '—'}", "",
           "## Format signals (for the format and language check)",
           f"- Pages of this paper in the PDF: {last - first + 1}" + (f" (PDF pp. {first + 1}–{last + 1} of a {doc.page_count}-page volume)" if doc.page_count > VOLUME_PAGES else ""),
           f"- Track or venue words seen: {', '.join(track) or 'none'}",
           f"- English stopword ratio on first pages: {en_ratio} (English text is usually above 0.2)"]
    if acm:
        out.append(f"- ACM Reference Format: {re.sub(r'\s+', ' ', acm.group(1)).strip()[:400]}")
    out.append("- Page headers and footers, first two pages:")
    out += [f"  - {re.sub(r'\s+', ' ', h)[:250]}" for h in hf[:10]] or ["  - none found"]
    out += ["", "## Section outline (✓ = text included below, ✗ = left out)"]
    for s in sections[1:]:
        mark = "✗" if s["cls"] in ("related", "back") else "✓"
        out.append(f"{'  ' * (s['level'] - 1)}- {mark} {s['num']} {s['title']}  [p.{s['page']}]".replace("  [", " [").replace("-  ", "- "))
    if n_heads == 0:
        out.append("- (no headings detected)")
    out += ["", "## Figure and table captions"]
    out += [f"- {f['label']} [p.{f['page']}]: {re.sub(r'\s+', ' ', f['caption'])[:500]}" for f in figures]
    out += [f"- {t['label']} [p.{t['page']}]: {re.sub(r'\s+', ' ', t['caption'])}" for t in table_caps]
    if not figures and not table_caps:
        out.append("- none found")
    out += ["", "## Paper text", "(Related work, references, acknowledgements and appendices are left out. ⟨p.N⟩ marks the PDF page.)", ""]
    for k in kept:
        out += [k["head"], "", k["text"].strip(), ""]
    md = "\n".join(out)
    open(os.path.join(out_dir, "extract.md"), "w", encoding="utf-8").write(md)

    meta = {"id": rec["id"], "title": rec["title"], "pdf": pdf_name, "match": how,
            "pdf_pages": [first + 1, last + 1], "page_count": last - first + 1,
            "volume_pages": doc.page_count if doc.page_count > VOLUME_PAGES else None,
            "body_font": body, "headings": n_heads,
            "sections": [{"num": s["num"], "title": s["title"], "page": s["page"], "kept": s["cls"] not in ("related", "back")}
                         for s in sections[1:]],
            "track_words": track, "header_footer": hf[:10], "english_ratio": en_ratio,
            "figures": figures, "tables": table_caps, "extract_chars": len(md), "flags": flags}
    json.dump(meta, open(os.path.join(out_dir, "meta.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return meta

# ---------------------------------------------------------------- local PDF copy for the panel

def place_pdf(out_dir, pdf_path, first, last, whole):
    """Put the paper's PDF in its extract folder as paper.pdf, so the panel can open it.
    A whole PDF is hard-linked (no extra disk space) or copied; a paper inside a
    proceedings volume gets just its own pages. Returns the page offset: PDF page N of the
    source is page N - offset of paper.pdf."""
    dst = os.path.join(out_dir, "paper.pdf")
    if os.path.exists(dst):
        os.remove(dst)
    if whole:
        try:
            os.link(pdf_path, dst)
        except OSError:
            shutil.copyfile(pdf_path, dst)
        return 0
    src = pymupdf.open(pdf_path)
    part = pymupdf.open()
    part.insert_pdf(src, from_page=first, to_page=last)
    part.save(dst, garbage=3, deflate=True)
    return first

def add_pdfs(out_root, pdf_dir):
    """Add paper.pdf to every existing extract, without redoing the extraction."""
    n = 0
    for rid in sorted(os.listdir(out_root)):
        mp = os.path.join(out_root, rid, "meta.json")
        if not os.path.exists(mp):
            continue
        meta = json.load(open(mp, encoding="utf-8"))
        first, last = meta["pdf_pages"][0] - 1, meta["pdf_pages"][1] - 1
        meta["page_offset"] = place_pdf(os.path.join(out_root, rid), os.path.join(pdf_dir, meta["pdf"]),
                                        first, last, whole=not meta.get("volume_pages"))
        meta["local_pdf"] = "paper.pdf"
        json.dump(meta, open(mp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        n += 1
    print(f"Added paper.pdf to {n} extracts.")

# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--screener", default="Raghu")
    ap.add_argument("--pdfs", default=os.path.join(REPO, "survey-papers"))
    ap.add_argument("--corpus", default=os.path.join(ROOT, "fulltext", "fulltext_corpus.json"))
    ap.add_argument("--out", default=os.path.join(ROOT, "fulltext", "extracts"))
    ap.add_argument("--only", default="", help="comma-separated record IDs to (re)build")
    ap.add_argument("--pdfs-only", action="store_true", help="just add paper.pdf to existing extracts")
    a = ap.parse_args()
    if a.pdfs_only:
        return add_pdfs(a.out, a.pdfs)

    all_recs, todo = load_records(a.corpus, a.screener)
    if not todo:
        sys.exit(f"No acquired, undecided papers assigned to {a.screener!r}.")
    only = {x.strip() for x in a.only.split(",") if x.strip()}
    os.makedirs(a.out, exist_ok=True)
    print(f"{len(todo)} papers to screen for {a.screener}; matching PDFs in {a.pdfs} …")

    rows, single, volumes = match_pdfs(a.pdfs, todo, all_recs)
    mine = {r["id"]: r for r in todo}
    vol_docs = {f: pymupdf.open(os.path.join(a.pdfs, f)) for f in volumes}
    # volume PDFs with no ISBN match: look for any still-unmatched paper's title inside them
    unplaced = [r for r in todo if r["id"] not in single and not any(r in v for v in volumes.values())]
    vol_place = {}
    for f, recs in volumes.items():
        for r in list(recs) + (unplaced if not recs else []):
            if r["id"] not in mine or r["id"] in vol_place:
                continue
            loc = locate_in_volume(vol_docs[f], r)
            if loc:
                vol_place[r["id"]] = (f, loc)
                if r not in recs:
                    rows.append({"pdf": f, "pages": vol_docs[f].page_count, "status": "matched",
                                 "how": "title-in-volume", "id": r["id"], "mine": True, "title": r["title"][:90]})

    # ref.rtf cross-check
    refs = parse_ref_rtf(os.path.join(a.pdfs, "ref.rtf"))
    by_doi = {clean_doi(r["doi"]): r for r in todo if r.get("doi")}
    by_title = {norm(r["title"])[:50]: r for r in todo}
    in_refs = set()
    for e in refs:
        r = by_doi.get(e["doi"]) or by_title.get(norm(e["title"])[:50])
        if r:
            in_refs.add(r["id"])

    manifest, counts = [], collections.Counter()
    for r in todo:
        rid = r["id"]
        if only and rid not in only:
            continue
        out_dir = os.path.join(a.out, rid)
        row = {"id": rid, "title": r["title"], "type": r["type"], "year": r["year"],
               "in_ref_rtf": rid in in_refs, "pdf": None, "status": "", "flags": []}
        try:
            if rid in single:
                files = single[rid]
                if len(files) > 1:
                    row["flags"].append("duplicate PDFs: " + " | ".join(files))
                pdf = files[0]
                d = pymupdf.open(os.path.join(a.pdfs, pdf))
                first, last = 0, d.page_count - 1
                how = next(x["how"] for x in rows if x.get("id") == rid and x["pdf"] == pdf)
            elif rid in vol_place:
                pdf, (first, last) = vol_place[rid]
                how = "volume"
            else:
                in_vol = [f for f, recs in volumes.items() if any(x["id"] == rid for x in recs)]
                row["status"] = "skipped"
                row["flags"].append(f"paper not found inside volume {in_vol[0]}" if in_vol else "no PDF found")
                manifest.append(row); counts[row["status"]] += 1
                shutil.rmtree(out_dir, ignore_errors=True)
                continue
            shutil.rmtree(out_dir, ignore_errors=True)
            os.makedirs(out_dir)
            meta = build_extract(r, pdf, os.path.join(a.pdfs, pdf), first, last, out_dir, how)
            meta["page_offset"] = place_pdf(out_dir, os.path.join(a.pdfs, pdf), first, last,
                                            whole=not meta.get("volume_pages"))
            meta["local_pdf"] = "paper.pdf"
            json.dump(meta, open(os.path.join(out_dir, "meta.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            row.update(pdf=pdf, status="extracted", pages=meta["page_count"], headings=meta["headings"],
                       figures=len(meta["figures"]), chars=meta["extract_chars"])
            row["flags"] += meta["flags"]
        except Exception as e:
            row["status"] = "error"
            row["flags"].append(f"{type(e).__name__}: {e}"[:200])
        manifest.append(row)
        counts[row["status"]] += 1
        print(f"\r  {sum(counts.values())}/{len(todo) if not only else len(only)}", end="", flush=True)
    print()

    if not only:
        json.dump({"created": datetime.datetime.now().isoformat(timespec="seconds"), "screener": a.screener,
                   "papers": manifest}, open(os.path.join(a.out, "manifest.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        with open(os.path.join(a.out, "match_report.csv"), "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, ["pdf", "pages", "status", "how", "id", "mine", "title", "detail"])
            w.writeheader()
            for x in rows:
                w.writerow(x)
        stray = sorted({x["pdf"] for x in rows if x.get("status") == "matched" and not x.get("mine")})
        print(f"\nExtracted {counts['extracted']}, skipped {counts['skipped']}, errors {counts['error']}.")
        print(f"PDFs unmatched: {sum(1 for x in rows if x['status'] in ('unmatched', 'unreadable'))}"
              f"  |  PDFs matching someone else's record: {len(stray)}"
              f"  |  papers not listed in ref.rtf: {sum(1 for x in manifest if not x['in_ref_rtf'])}"
              " (ref.rtf lists proceedings volumes as books, so their papers count here)")
        flagged = [x for x in manifest if x["flags"] or x["status"] != "extracted"]
        if flagged:
            print("\nNeeds a look:")
            for x in flagged:
                print(f"  {x['id']}  {x['status']:<9}  {'; '.join(x['flags'])}")
    print(f"\nOutput: {a.out}")

if __name__ == "__main__":
    main()
