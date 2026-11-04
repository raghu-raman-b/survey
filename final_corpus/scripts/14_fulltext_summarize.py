#!/usr/bin/env python3
"""Ask an LLM for a screening briefing on each extracted paper. The LLM never decides.

    python3 14_fulltext_summarize.py prepare            # build prompts + cost estimate, no API calls
    python3 14_fulltext_summarize.py run --limit 5      # try a few papers first
    python3 14_fulltext_summarize.py run                # the rest (skips papers already done)
    python3 14_fulltext_summarize.py batch-submit       # same, through the Batch API (half price, <24 h)
    python3 14_fulltext_summarize.py batch-collect      # fetch batch results when it's finished

Standard library only. Uses the OpenAI Responses API; the key comes from OPENAI_API_KEY
or a line OPENAI_API_KEY=... in the repo's .env (which git ignores).

Reads  fulltext/extracts/<ID>/extract.md (from 13_fulltext_extract.py) and criteria.json
Writes fulltext/extracts/<ID>/summary.json   the briefing, shown by the summary panel in
                                             tools/fulltext_screening.html
       fulltext/extracts/prompt_system.txt   the exact instructions sent, for the methods section
       fulltext/extracts/usage_log.csv       tokens and cost per call

The briefing follows the full-text checks in criteria.json (fulltext_skim) in order and
then RQ1-RQ7. For each it reports what the paper says, with page references and short
quotes, and what is missing or ambiguous. It gives no verdicts.
"""
import argparse, base64, concurrent.futures as cf, csv, datetime, json, os, re, sys, threading, time
import urllib.request, urllib.error, uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REPO = os.path.dirname(ROOT)
EXTRACTS = os.path.join(ROOT, "fulltext", "extracts")
API = "https://api.openai.com/v1"

# USD per million tokens (input, cached input, output), as listed in 2026-11. Terra is from
# OpenAI's model page; Luna from third-party listings. Check https://openai.com/api/pricing
# and override with --price-* for any other model.
MODEL_PRICES = {"gpt-6-luna": (0.10, 0.01, 0.50), "gpt-6.1-terra": (1.00, 0.05, 5.00)}
PRICE = {"input": 0.10, "cached": 0.01, "output": 0.50}
BATCH_DISCOUNT = 0.5

# ---------------------------------------------------------------- prompt

def slug(s):
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")

def load_criteria(path):
    c = json.load(open(path, encoding="utf-8"))
    crit = {x["code"]: x for x in c["include"] + c["exclude"]}
    return c, crit

def system_prompt(c, crit):
    steps = c["fulltext_skim"]["steps"]
    lines = [
        "You help a human screener in the full-text screening phase of a systematic review titled "
        "\"Generative AI in XR\" (VR, AR, MR). You receive text extracted from one paper's PDF: record "
        "metadata from the database export, format signals (page count, headers and footers, track "
        "words), the section outline, figure and table captions, and the paper text with related work, "
        "references and appendices removed. ⟨p.N⟩ marks the PDF page.",
        "",
        "YOUR ROLE: write a factual briefing on what this paper contains, so the screener can decide "
        "quickly. You do NOT decide. Never say whether a criterion is met or failed, never recommend "
        "include or exclude, never name an exclusion code as the outcome. Report what the paper says "
        "and does, where it says it, and what it leaves out. Plain observations are wanted: \"6 pages; "
        "the footer reads 'CHI EA '24 Adjunct'\", \"No user study, metrics or comparison are reported; "
        "the paper ends with a demo walkthrough\", \"GPT-4 writes Unity C# scripts at runtime\".",
        "",
        "STAY NEUTRAL. Many papers in this set turn out not to fit the review; that is normal and "
        "expected. Describe each paper as it is, in its own terms:",
        "- Report only what the text states. Do not stretch, generalise or reinterpret the paper's "
        "content to fit a check or a research question. If the paper doesn't address something, "
        "write \"not stated\". An empty or \"not stated\" answer is a correct answer, not a failure.",
        "- Give evidence on both sides with equal care: what fits a check and what speaks against it.",
        "- Don't relabel the paper in the review's vocabulary. If the paper says \"AI assistant\" and "
        "never names a model, say exactly that; don't call it an LLM. If it says \"VR-like\" or "
        "\"3D screen\", don't call it VR.",
        "- No adjectives of your own about quality, novelty or importance. Don't repeat the authors' "
        "claims as facts; attribute them (\"the authors report…\").",
        "- Mark anything you infer rather than read with \"(inferred)\" and say from what.",
        "",
        "RULES",
        "- Use only the provided text. Do not use outside knowledge of the paper, its authors or its venue.",
        "- Give page references as [p.N]. Quotes are short (under 30 words) and copied character for "
        "character from the text, keeping its typos, missing letters and odd spacing. If you are "
        "restating or shortening, it is not a quote: put it in the evidence text instead.",
        "- Name models exactly as written (e.g. \"GPT-4o\", \"Stable Diffusion XL\", \"Shap-E\").",
        "- The text is machine-extracted: words may be run together, tables flattened and parts cut "
        "(marked \"[… omitted …]\"). Mention extraction problems that limit what you can tell.",
        "- Plain, compact English. No praise or filler.",
        "",
        "TERMS the checks use (to know what evidence to report, not to judge)",
        "- Learned generative model: trained on data to produce new content - GANs, VAEs, diffusion, "
        "flow and autoregressive models such as LLMs and VLMs, and text-to-3D / text-to-image / TTS "
        "systems built on them. Not in this category: procedural or rule-based generation; "
        "discriminative models (classification, detection, segmentation, pose, tracking, "
        "recommendation); NeRF or Gaussian splatting used only to reconstruct a captured scene. "
        "Report which kind the paper actually describes.",
        "- Essential: the screener judges this. Report what the model does, what the rest of the "
        "system does without it, and whether the paper says what happens without the model.",
        "- XR: VR, AR or MR. Report the actual display and setting the paper describes "
        "(headset, phone AR, desktop, CAVE…), and whether content is generated at runtime or beforehand.",
        "",
        "THE SCREENER'S CHECKS (report the evidence for each, in this order; the criteria text says "
        "what the screener weighs, it is not a verdict for you to give)",
    ]
    for s in steps:
        codes = s["codes"]
        lines.append(f"- {slug(s['title'])}  ({' / '.join(codes)}: {s['title']})")
        for code in codes:
            lines.append(f"    {code}: {crit[code]['description']}")
        lines.append(f"    Where to look: {s['where']}. What the screener weighs: {s['look']}")
        if s.get("auto"):
            lines.append("    The year is in the record metadata; also report any other date the paper shows "
                         "(conference date, 'published online', copyright line) if it differs.")
    lines += ["", "RESEARCH QUESTIONS. These say what the reviewers will extract later from the papers "
              "that are included. They are NOT things this paper is expected to address; most papers "
              "address only a few, many none. For each, report only what the paper explicitly reports. "
              "If it reports nothing on it, write \"not stated\". Don't derive answers from general "
              "descriptions, and don't call a condition \"non-generative\", a measure \"UX\" or a cost "
              "\"computational\" unless the paper's own description makes that plain."]
    for rq in c["research_questions"]:
        lines.append(f"- {rq['code']}: {rq['text']} (Typical places: {rq['look_for']})")
    lines += ["", "Write the paper description fields (one_line to evaluation_summary) first and from the "
              "paper alone, before thinking about the checks or research questions.",
              "Return JSON matching the schema. Every field is required; use \"not stated\" or an empty list when nothing applies."]
    return "\n".join(lines)

def schema(c):
    S = lambda d="": {"type": "string", "description": d} if d else {"type": "string"}
    quotes = {"type": "array", "description": "Short exact quotes backing the evidence.",
              "items": {"type": "object", "additionalProperties": False, "required": ["page", "text"],
                        "properties": {"page": {"type": "integer"}, "text": S()}}}
    obj = lambda props: {"type": "object", "additionalProperties": False,
                         "required": list(props), "properties": props}
    check = obj({"evidence": S("What the paper shows that bears on this check, for and against, with [p.N] refs. No verdict."),
                 "quotes": quotes,
                 "gaps": S("What is missing, ambiguous or worth opening the PDF for; empty string if nothing.")})
    rq = obj({"notes": S("Only what the paper explicitly reports on this, with [p.N] refs. 'not stated' if it reports nothing."),
              "quotes": quotes})
    ns = " As the paper states it; 'not stated' if it doesn't say."
    steps = c["fulltext_skim"]["steps"]
    rqs = {r["code"]: rq for r in c["research_questions"]}
    rqs["RQ2"] = obj({
        "output_type": S("What the model generates (e.g. 3D asset, scene layout, texture, image, speech, motion, dialogue, code)." + ns),
        "models": S("Generative models named in the paper and how they are used (prompted, fine-tuned, trained)." + ns),
        "infrastructure": S("Where generation runs (cloud API, local server/GPU, on the headset or phone)." + ns),
        "timing": S("When content is generated (at runtime during use, or beforehand)." + ns),
        "domain": S("The application area the paper names." + ns),
        "xr_platform": S("Display type, device and engine the paper names (e.g. Quest 3, HoloLens 2, phone AR, Unity)." + ns),
        "notes": S("Anything else relevant to RQ2."), "quotes": quotes})
    return obj({
        "one_line": S("One sentence: what this paper is and does."),
        "paper_type": S("What kind of paper it reads as (system paper, empirical study, technique paper, case study, "
                        "survey, position paper, demo, workshop/short paper, book chapter...), with the reasons."),
        "aim": S("What the authors set out to do and why."),
        "contributions": {"type": "array", "items": S(), "description": "The stated contributions, as the paper lists them."},
        "how_it_works": S("The system or method in a compact paragraph: inputs, pipeline stages, which model does what, XR side."),
        "evaluation_summary": S("How it was evaluated: type (user study / technical metrics / benchmark / expert review), "
                                "design, participants (n), conditions and baselines, measures, main results. "
                                "If nothing is evaluated, say so plainly and say what the paper offers instead."),
        "checks": obj({slug(s["title"]): check for s in steps}),
        "research_questions": obj(rqs),
        "figures_to_look_at": S("Which figures best show the system (e.g. 'Figure 2 [p.4]: architecture'), or 'none'."),
        "extraction_issues": S("Problems with the extracted text that limit this briefing; empty string if none."),
    })

# ---------------------------------------------------------------- API plumbing

def api_key():
    """OPENAI_API_KEY from the environment, else from final_corpus/.env or the repo's .env
    (names OPENAI_API_KEY or OPEN-AI-KEY, spaces around '=' allowed)."""
    k = os.environ.get("OPENAI_API_KEY")
    for env in (os.path.join(ROOT, ".env"), os.path.join(REPO, ".env")):
        if k or not os.path.exists(env):
            continue
        for line in open(env):
            name, sep, val = line.partition("=")
            if sep and name.strip() in ("OPENAI_API_KEY", "OPEN-AI-KEY"):
                k = val.strip().strip("\"'")
                break
    if not k:
        sys.exit("No API key: set OPENAI_API_KEY, or put OPENAI_API_KEY=... in final_corpus/.env")
    return k

def http(method, path, key, body=None, raw=None, ctype="application/json", tries=6):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    for attempt in range(tries):
        req = urllib.request.Request(API + path, data=data, method=method,
                                     headers={"Authorization": f"Bearer {key}", "Content-Type": ctype})
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                out = r.read()
                return json.loads(out) if r.headers.get_content_type() == "application/json" else out
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="replace")[:500]
            if e.code in (429, 500, 502, 503, 504) and attempt < tries - 1:
                time.sleep(min(60, 2 ** attempt * 3))
                continue
            raise RuntimeError(f"HTTP {e.code}: {msg}")
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:   # incl. connection resets
            if attempt < tries - 1:
                time.sleep(5)
                continue
            raise RuntimeError(str(e))

def request_body(a, sysmsg, sch, paper_id):
    md = open(os.path.join(EXTRACTS, paper_id, "extract.md"), encoding="utf-8").read()
    content = [{"type": "input_text", "text": md}]
    if a.with_figures:
        meta = json.load(open(os.path.join(EXTRACTS, paper_id, "meta.json"), encoding="utf-8"))
        for f in [f for f in meta["figures"] if f.get("file")][:a.max_figures]:
            b64 = base64.b64encode(open(os.path.join(EXTRACTS, paper_id, f["file"]), "rb").read()).decode()
            content += [{"type": "input_text", "text": f"{f['label']} [p.{f['page']}]"},
                        {"type": "input_image", "image_url": f"data:image/jpeg;base64,{b64}", "detail": "low"}]
    body = {"model": a.model,
            "input": [{"role": "developer", "content": sysmsg},     # same text every call -> cached
                      {"role": "user", "content": content}],
            "text": {"format": {"type": "json_schema", "name": "screening_briefing", "strict": True, "schema": sch}},
            "prompt_cache_key": "fulltext-screening-briefing",
            "store": False}
    if a.reasoning:
        body["reasoning"] = {"effort": a.reasoning}
    if a.max_output:
        body["max_output_tokens"] = a.max_output
    return body

def output_text(resp):
    for item in resp.get("output", []):
        for c in item.get("content", []) or []:
            if c.get("type") == "output_text":
                return c["text"]
    raise RuntimeError(f"no text in response (status {resp.get('status')})")

def cost(usage, batch=False, price=PRICE):
    inp = usage.get("input_tokens", 0)
    cached = (usage.get("input_tokens_details") or {}).get("cached_tokens", 0)
    out = usage.get("output_tokens", 0)
    f = BATCH_DISCOUNT if batch else 1.0
    return ((inp - cached) * price["input"] * f + cached * price["cached"] + out * price["output"] * f) / 1e6

_log_lock = threading.Lock()

def log_usage(paper_id, model, usage, batch):
    path = os.path.join(EXTRACTS, "usage_log.csv")
    new = not os.path.exists(path)
    with _log_lock, open(path, "a", newline="") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["time", "id", "model", "mode", "input", "cached", "output", "usd"])
        w.writerow([datetime.datetime.now().isoformat(timespec="seconds"), paper_id, model,
                    "batch" if batch else "sync", usage.get("input_tokens"),
                    (usage.get("input_tokens_details") or {}).get("cached_tokens", 0),
                    usage.get("output_tokens"), round(cost(usage, batch), 5)])

def _qnorm(s, loose=False):
    s = re.sub(r"[^a-z0-9]", "", s.lower().replace("ﬁ", "fi").replace("ﬂ", "fl"))
    # loose: also ignore f/i/l, which PDF ligatures often drop ("flled" for "filled")
    return re.sub(r"[fil]", "", s) if loose else s

def verify_quotes(data, extract_md):
    """Mark each quote verified: true if it is in the extracted text (ignoring spacing,
    punctuation and lost ligatures), false if not. The panel flags the false ones."""
    exact, loose = _qnorm(extract_md), _qnorm(extract_md, True)
    groups = list(data.get("checks", {}).values()) + list(data.get("research_questions", {}).values())
    bad = 0
    for g in groups:
        for q in g.get("quotes", []):
            t = q.get("text", "")
            q["verified"] = bool(t) and (_qnorm(t) in exact or _qnorm(t, True) in loose)
            bad += not q["verified"]
    return bad

def save_summary(paper_id, model, text, usage, batch, save_as="summary.json"):
    data = json.loads(text)
    md = open(os.path.join(EXTRACTS, paper_id, "extract.md"), encoding="utf-8").read()
    data["_unverified_quotes"] = verify_quotes(data, md)
    data["_meta"] = {"model": model, "created": datetime.datetime.now().isoformat(timespec="seconds"),
                     "usage": usage, "mode": "batch" if batch else "sync"}
    json.dump(data, open(os.path.join(EXTRACTS, paper_id, save_as), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

def spent_so_far():
    path = os.path.join(EXTRACTS, "usage_log.csv")
    if not os.path.exists(path):
        return 0.0
    return sum(float(r["usd"] or 0) for r in csv.DictReader(open(path)))

# ---------------------------------------------------------------- commands

def papers(a):
    man = json.load(open(os.path.join(EXTRACTS, "manifest.json"), encoding="utf-8"))
    ids = [p["id"] for p in man["papers"] if p["status"] == "extracted"]
    missing = [i for i in ids if not os.path.exists(os.path.join(EXTRACTS, i, "extract.md"))]
    if missing:
        print(f"Skipping {len(missing)} papers whose extract.md is missing (re-run 13_fulltext_extract.py): "
              + ", ".join(missing[:10]) + (" …" if len(missing) > 10 else ""))
        ids = [i for i in ids if i not in missing]
    if a.only:
        want = {x.strip() for x in a.only.split(",")}
        ids = [i for i in ids if i in want]
    if not a.redo:
        ids = [i for i in ids if not os.path.exists(os.path.join(EXTRACTS, i, a.save_as))]
    return ids[: a.limit] if a.limit else ids

def estimate(a, ids, sysmsg, sch):
    tok = lambda s: len(s) / 4.0          # rough: ~4 characters per token for English
    fixed = tok(sysmsg) + tok(json.dumps(sch)) + 40
    per, img_tokens = [], 0
    for i in ids:
        per.append(tok(open(os.path.join(EXTRACTS, i, "extract.md"), encoding="utf-8").read()))
        if a.with_figures:
            meta = json.load(open(os.path.join(EXTRACTS, i, "meta.json"), encoding="utf-8"))
            img_tokens += min(a.max_figures, sum(1 for f in meta["figures"] if f.get("file"))) * a.image_tokens
    n = len(ids)
    uncached = sum(per) + img_tokens + (fixed if n else 0)          # first call writes the cache
    cached = fixed * max(0, n - 1)
    out = a.est_output * n
    p = PRICE
    sync = (uncached * p["input"] + cached * p["cached"] + out * p["output"]) / 1e6
    batch = (uncached * p["input"] * BATCH_DISCOUNT + cached * p["cached"] + out * p["output"] * BATCH_DISCOUNT) / 1e6
    return {"n": n, "fixed": fixed, "per": per, "img": img_tokens, "out": out, "sync": sync, "batch": batch}

def cmd_prepare(a, sysmsg, sch):
    e = estimate(a, papers(a), sysmsg, sch)
    open(os.path.join(EXTRACTS, "prompt_system.txt"), "w", encoding="utf-8").write(sysmsg)
    json.dump(sch, open(os.path.join(EXTRACTS, "prompt_schema.json"), "w"), indent=1)
    n, per = e["n"], e["per"]
    print(f"Papers to summarise: {n}")
    print(f"Fixed prompt (instructions + schema): ~{e['fixed']:,.0f} tokens, cached after the first call")
    if n:
        print(f"Paper extracts: ~{sum(per):,.0f} tokens total, ~{sum(per)/n:,.0f} avg, ~{max(per):,.0f} max")
    if a.with_figures:
        print(f"Figure images: ~{e['img']:,.0f} tokens (≤{a.max_figures} per paper at ~{a.image_tokens} each)")
    print(f"Output: ~{e['out']:,.0f} tokens (~{a.est_output} per briefing; reasoning tokens, if any, bill as output)")
    print(f"\nEstimated cost on {a.model} (in ${PRICE['input']}/cached ${PRICE['cached']}/out ${PRICE['output']} per M):")
    print(f"  standard: ${e['sync']:.2f}    batch: ${e['batch']:.2f}")
    print(f"Spent so far (usage_log.csv): ${spent_so_far():.2f}")
    print(f"\nWrote prompt_system.txt and prompt_schema.json to {EXTRACTS}")

def cmd_run(a, sysmsg, sch):
    key = api_key()
    ids = papers(a)
    prior = spent_so_far()
    print(f"{len(ids)} papers -> {a.model}, {a.workers} at a time"
          + (f"; budget ${a.budget:.2f}, already spent ${prior:.2f}" if a.budget else ""))
    total, done, failed, skipped = 0.0, 0, [], []
    lock = threading.Lock()
    per_paper = [0.0]                       # running average cost, to stop before the budget runs out

    def one(pid):
        with lock:
            guess = per_paper[0] or estimate(a, [pid], sysmsg, sch)["sync"]
            if a.budget and prior + total + guess * a.workers > a.budget:
                skipped.append(pid)
                return None
        resp = http("POST", "/responses", key, request_body(a, sysmsg, sch, pid))
        if resp.get("status") not in (None, "completed"):
            raise RuntimeError(f"status {resp.get('status')}: {resp.get('incomplete_details')}")
        usage = resp.get("usage", {})
        save_summary(pid, a.model, output_text(resp), usage, False, a.save_as)
        log_usage(pid, a.model, usage, False)
        return cost(usage)

    with cf.ThreadPoolExecutor(a.workers) as ex:
        futs = {ex.submit(one, pid): pid for pid in ids}
        for f in cf.as_completed(futs):
            pid = futs[f]
            try:
                c = f.result()
                if c is None:
                    continue
                with lock:
                    total += c; done += 1
                    per_paper[0] = total / done
                print(f"  {pid} ok   ({done}/{len(ids)}, ${total:.3f} this run)")
            except Exception as e:
                failed.append(pid)
                print(f"  {pid} FAILED: {e}")
    print(f"\nDone {done}, failed {len(failed)}, cost ${total:.3f} (total spent ${prior + total:.2f}).")
    if skipped:
        print(f"Stopped before {len(skipped)} papers to stay under the ${a.budget:.2f} budget.")
    if failed:
        print("Re-run the same command to retry the failed ones: " + ",".join(failed))

def cmd_batch_submit(a, sysmsg, sch):
    key = api_key()
    ids = papers(a)
    if not ids:
        sys.exit("Nothing to submit.")
    est, prior = estimate(a, ids, sysmsg, sch)["batch"], spent_so_far()
    print(f"{len(ids)} papers, estimated ${est:.2f} at batch price; spent so far ${prior:.2f}.")
    if a.budget and prior + est > a.budget:
        sys.exit(f"That would go over the ${a.budget:.2f} budget. Use --limit to send fewer papers.")
    lines = [json.dumps({"custom_id": pid, "method": "POST", "url": "/v1/responses",
                         "body": request_body(a, sysmsg, sch, pid)}) for pid in ids]
    payload = ("\n".join(lines) + "\n").encode()
    boundary = uuid.uuid4().hex
    raw = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"purpose\"\r\n\r\nbatch\r\n"
           f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"briefings.jsonl\"\r\n"
           f"Content-Type: application/jsonl\r\n\r\n").encode() + payload + f"\r\n--{boundary}--\r\n".encode()
    f = http("POST", "/files", key, raw=raw, ctype=f"multipart/form-data; boundary={boundary}")
    b = http("POST", "/batches", key, {"input_file_id": f["id"], "endpoint": "/v1/responses",
                                       "completion_window": "24h"})
    state = os.path.join(EXTRACTS, "batches.json")
    hist = json.load(open(state)) if os.path.exists(state) else []
    hist.append({"batch": b["id"], "file": f["id"], "n": len(ids), "model": a.model, "save_as": a.save_as,
                 "submitted": datetime.datetime.now().isoformat(timespec="seconds")})
    json.dump(hist, open(state, "w"), indent=1)
    print(f"Submitted batch {b['id']} with {len(ids)} papers. Run batch-collect later (results within 24 h).")

def cmd_batch_collect(a, sysmsg, sch):
    key = api_key()
    state = os.path.join(EXTRACTS, "batches.json")
    if not os.path.exists(state):
        sys.exit("No batches submitted yet.")
    hist = json.load(open(state))
    for h in hist:
        if h.get("collected"):
            continue
        b = http("GET", f"/batches/{h['batch']}", key)
        print(f"{h['batch']}: {b['status']}  {b.get('request_counts')}")
        if b["status"] != "completed":
            continue
        ok = bad = 0
        total = 0.0
        for fid in (b.get("output_file_id"), b.get("error_file_id")):
            if not fid:
                continue
            raw = http("GET", f"/files/{fid}/content", key)
            raw = raw.decode() if isinstance(raw, bytes) else json.dumps(raw)
            for line in raw.splitlines():
                if not line.strip():
                    continue
                r = json.loads(line)
                pid = r["custom_id"]
                body = (r.get("response") or {}).get("body") or {}
                try:
                    if (r.get("response") or {}).get("status_code") != 200:
                        raise RuntimeError(r.get("error") or body.get("error"))
                    usage = body.get("usage", {})
                    save_summary(pid, h["model"], output_text(body), usage, True, h.get("save_as", "summary.json"))
                    log_usage(pid, h["model"], usage, True)
                    total += cost(usage, True); ok += 1
                except Exception as e:
                    bad += 1
                    print(f"  {pid} FAILED: {e}")
        h["collected"] = datetime.datetime.now().isoformat(timespec="seconds")
        print(f"  saved {ok}, failed {bad}, cost ${total:.3f}")
    json.dump(hist, open(state, "w"), indent=1)

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("command", choices=["prepare", "run", "batch-submit", "batch-collect"])
    ap.add_argument("--model", default="gpt-6-luna")
    ap.add_argument("--criteria", default=os.path.join(ROOT, "criteria.json"))
    ap.add_argument("--only", default="", help="comma-separated record IDs")
    ap.add_argument("--limit", type=int, default=0, help="at most this many papers")
    ap.add_argument("--redo", action="store_true", help="also redo papers that already have a summary")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--reasoning", default="", help="reasoning effort (low/medium/high) if the model takes one")
    ap.add_argument("--max-output", type=int, default=0)
    ap.add_argument("--with-figures", action="store_true", help="also send figure crops as images")
    ap.add_argument("--max-figures", type=int, default=4)
    ap.add_argument("--image-tokens", type=int, default=600, help="estimate only: tokens per low-detail image")
    ap.add_argument("--est-output", type=int, default=1800, help="estimate only: output tokens per briefing")
    ap.add_argument("--budget", type=float, default=0, help="stop before total spend (usage_log.csv) passes this, in USD")
    ap.add_argument("--save-as", default="summary.json",
                    help="file name per paper; the panel shows summary.json, so use e.g. summary_terra.json to compare models")
    ap.add_argument("--price-input", type=float)
    ap.add_argument("--price-cached", type=float)
    ap.add_argument("--price-output", type=float)
    a = ap.parse_args()
    known = MODEL_PRICES.get(a.model)
    if not known and None in (a.price_input, a.price_cached, a.price_output):
        sys.exit(f"No prices known for {a.model}; pass --price-input, --price-cached and --price-output.")
    base = dict(zip(("input", "cached", "output"), known or (0, 0, 0)))
    PRICE.update({k: v if v is not None else base[k] for k, v in
                  (("input", a.price_input), ("cached", a.price_cached), ("output", a.price_output))})
    c, crit = load_criteria(a.criteria)
    sysmsg, sch = system_prompt(c, crit), schema(c)
    {"prepare": cmd_prepare, "run": cmd_run, "batch-submit": cmd_batch_submit,
     "batch-collect": cmd_batch_collect}[a.command](a, sysmsg, sch)

if __name__ == "__main__":
    main()
