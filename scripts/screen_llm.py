#!/usr/bin/env python3
"""Screen references with an OpenAI model to build an LLM quasi-gold set (QGS).

Each record (title + abstract) is sent with system_prompt.txt to the Responses API.
Every call is appended to a JSONL log, so an interrupted run resumes where it left
off (only records screened with the same model, effort and prompt are reused).

Outputs (in --out-dir):
  llm_screening_raw.jsonl       every call: parsed answer, token usage, cost
  llm_screening_results.csv     all screened records with verdicts and evidence
  llm_gold_set.csv              records the rules classify as "include"
  llm_uncertain.csv             records for human review
  llm_screening_report.txt      counts, coverage, token/cache/cost stats

Usage (from the project venv):
    ./bin/python scripts/screen_llm.py --limit 3        # smoke test
    ./bin/python scripts/screen_llm.py                  # screen everything
"""

import argparse
import csv
import hashlib
import json
import os
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import openai
from openai import OpenAI

ROOT = Path(__file__).resolve().parent.parent

# USD per 1M tokens, Standard tier (developers.openai.com/api/docs/pricing, checked 2026-09-15).
# Input tokens are billed at exactly one of input / cached / cache_write.
PRICING = {
    "gpt-5.6-luna": {"input": 0.20, "cached": 0.02, "cache_write": 0.25, "output": 1.20},
}

CRITERIA = ["C1_generative_ai", "C2_xr_central", "C3_genai_central_to_xr", "C4_primary_study",
            "C5_evaluation", "C6_english", "C7_time_frame"]
RQS = ["RQ1", "RQ2", "RQ3", "RQ4"]
DECISIONS = ["include", "uncertain", "exclude"]

CRITERION_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["yes", "no", "unclear"]},
        "evidence": {"type": "string"},
    },
    "required": ["verdict", "evidence"],
    "additionalProperties": False,
}
SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "criteria": {
            "type": "object",
            "properties": {c: CRITERION_SCHEMA for c in CRITERIA},
            "required": CRITERIA,
            "additionalProperties": False,
        },
        "rqs": {"type": "array", "items": {"type": "string", "enum": RQS}},
        "relevance": {"type": "integer", "enum": [0, 1, 2, 3]},
        "decision": {"type": "string", "enum": DECISIONS},
        "rationale": {"type": "string"},
    },
    "required": ["id", "criteria", "rqs", "relevance", "decision", "rationale"],
    "additionalProperties": False,
}

USAGE_KEYS = ["input_tokens", "cached_tokens", "cache_write_tokens", "output_tokens", "reasoning_tokens"]
# Errors every further call would also hit, so the run stops instead of burning through records.
FATAL_ERRORS = (openai.BadRequestError, openai.AuthenticationError,
                openai.PermissionDeniedError, openai.NotFoundError)


class FatalApiError(Exception):
    pass


class RetryableError(Exception):
    """The request succeeded but the output was unusable (incomplete, refused, bad JSON)."""


def load_env(path):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        os.environ.setdefault(key, value.strip().strip("\"'"))


def format_record(row):
    return (f"ID: {row['id']}\nTitle: {row['title']}\nYear: {row['year']}\n"
            f"Type: {row.get('type', '')}\nSource: {row.get('source', '')}\n"
            f"Abstract: {row['abstract']}")


def build_request(args, system_prompt, row):
    return {
        "model": args.model,
        "input": [
            # The breakpoint caches the shared system prompt. Implicit mode would put the
            # breakpoint after the (unique) record, paying a cache write on every call.
            {"role": "developer", "content": [{
                "type": "input_text", "text": system_prompt,
                "prompt_cache_breakpoint": {"mode": "explicit"},
            }]},
            {"role": "user", "content": [{"type": "input_text", "text": format_record(row)}]},
        ],
        "prompt_cache_options": {"mode": "explicit"},
        "reasoning": {"effort": args.effort},
        "text": {"format": {"type": "json_schema", "name": "screening_decision",
                            "schema": SCHEMA, "strict": True}},
        "max_output_tokens": args.max_output_tokens,
        "store": False,
    }


def usage_of(response):
    usage = response.usage
    if usage is None:
        return dict.fromkeys(USAGE_KEYS, 0)
    input_details, output_details = usage.input_tokens_details, usage.output_tokens_details
    return {
        "input_tokens": usage.input_tokens or 0,
        "cached_tokens": getattr(input_details, "cached_tokens", 0) or 0,
        "cache_write_tokens": getattr(input_details, "cache_write_tokens", 0) or 0,
        "output_tokens": usage.output_tokens or 0,
        "reasoning_tokens": getattr(output_details, "reasoning_tokens", 0) or 0,
    }


def cost_parts(usage, price):
    ordinary = max(usage["input_tokens"] - usage["cached_tokens"] - usage["cache_write_tokens"], 0)
    return {
        "input": ordinary * price["input"] / 1e6,
        "cached": usage["cached_tokens"] * price["cached"] / 1e6,
        "cache_write": usage["cache_write_tokens"] * price["cache_write"] / 1e6,
        "output": usage["output_tokens"] * price["output"] / 1e6,
    }


def parse_answer(response):
    if response.status != "completed":
        raise RetryableError(f"response status {response.status}: {response.incomplete_details}")
    for item in response.output:
        for part in getattr(item, "content", None) or []:
            if part.type == "refusal":
                raise RetryableError(f"refusal: {part.refusal}")
    try:
        return json.loads(response.output_text)
    except json.JSONDecodeError as e:
        raise RetryableError(f"invalid JSON output: {e}") from e


def rule_decision(answer):
    """Apply the prompt's decision rules to the model's own verdicts."""
    verdicts = [answer["criteria"][c]["verdict"] for c in CRITERIA]
    if "no" in verdicts:
        return "exclude"
    if all(v == "yes" for v in verdicts) and answer["relevance"] == 3:
        return "include"
    return "uncertain"


def screen(row, args, client, system_prompt, stop):
    """Screen one record. The SDK retries HTTP-level failures (429, 5xx, timeouts) itself;
    this loop retries responses whose output is unusable. Usage accumulates across attempts."""
    usage = dict.fromkeys(USAGE_KEYS, 0)
    request = build_request(args, system_prompt, row)
    started, error, attempt = time.monotonic(), None, 0
    for attempt in range(1, args.max_attempts + 1):
        if stop.is_set():
            error = "stopped"
            break
        try:
            response = client.responses.create(**request)
            for key, value in usage_of(response).items():
                usage[key] += value
            answer = parse_answer(response)
            return {"ok": True, "answer": answer, "response_id": response.id,
                    "attempts": attempt, "usage": usage}, time.monotonic() - started
        except FATAL_ERRORS as e:
            raise FatalApiError(str(e)) from e
        except openai.RateLimitError as e:
            if getattr(e, "code", None) == "insufficient_quota":
                raise FatalApiError(str(e)) from e
            error = f"rate limited after SDK retries: {e}"
            break
        except (openai.APIConnectionError, openai.APIStatusError) as e:
            error = f"API error after SDK retries: {e}"
            break
        except RetryableError as e:
            error = str(e)
    return {"ok": False, "error": error, "attempts": attempt, "usage": usage}, time.monotonic() - started


def bar(done, total, width=28):
    filled = int(width * done / total) if total else width
    return "█" * filled + "░" * (width - filled)


def fmt_duration(seconds):
    seconds = int(seconds)
    return f"{seconds // 60}m{seconds % 60:02d}s"


def load_previous(raw_path, config):
    """Latest successful result per record id that was produced with the same config."""
    done = {}
    if raw_path.exists():
        for line in raw_path.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("ok") and all(entry.get(k) == v for k, v in config.items()):
                done[str(entry["id"])] = entry
    return done


def write_csv(path, fieldnames, rows):
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_outputs(args, rows, results, config, run_stats):
    out = args.out_dir
    by_id = {str(r["id"]): r for r in rows}
    screened = [(by_id[i], results[i]) for i in by_id if i in results]

    result_rows, gold, uncertain = [], [], []
    for row, entry in screened:
        answer = entry["answer"]
        flat = {
            "id": row["id"], "title": row["title"], "year": row["year"], "doi": row["doi"],
            "decision": entry["decision"], "model_decision": answer["decision"],
            "relevance": answer["relevance"], "rqs": ";".join(answer["rqs"]),
            "rationale": answer["rationale"], "cost_usd": f"{entry['cost_usd']:.6f}",
        }
        for c in CRITERIA:
            flat[c] = answer["criteria"][c]["verdict"]
            flat[f"{c}_evidence"] = answer["criteria"][c]["evidence"]
        result_rows.append(flat)
        extra = {"relevance": answer["relevance"], "rqs": flat["rqs"], "rationale": answer["rationale"]}
        if entry["decision"] == "include":
            gold.append({**row, **extra})
        elif entry["decision"] == "uncertain":
            unclear = [c for c in CRITERIA if answer["criteria"][c]["verdict"] == "unclear"]
            uncertain.append({**row, **extra, "unclear_criteria": ";".join(unclear)})

    base_fields = list(rows[0].keys())
    result_fields = (["id", "title", "year", "doi", "decision", "model_decision", "relevance", "rqs"]
                     + [f for c in CRITERIA for f in (c, f"{c}_evidence")] + ["rationale", "cost_usd"])
    write_csv(out / "llm_screening_results.csv", result_fields, result_rows)
    write_csv(out / "llm_gold_set.csv", base_fields + ["relevance", "rqs", "rationale"], gold)
    write_csv(out / "llm_uncertain.csv", base_fields + ["relevance", "rqs", "unclear_criteria", "rationale"], uncertain)

    report = build_report(args, rows, screened, gold, uncertain, config, run_stats)
    (out / "llm_screening_report.txt").write_text(report, encoding="utf-8")
    return gold, uncertain, report


def build_report(args, rows, screened, gold, uncertain, config, run_stats):
    total = len(rows)
    n = len(screened)
    decisions = Counter(e["decision"] for _, e in screened)
    overridden = [r["id"] for r, e in screened if e["decision"] != e["answer"]["decision"]]
    price = PRICING[args.model]

    usage = dict.fromkeys(USAGE_KEYS, 0)
    costs = dict.fromkeys(["input", "cached", "cache_write", "output"], 0.0)
    attempts = 0
    for _, e in screened:
        attempts += e["attempts"]
        for k in USAGE_KEYS:
            usage[k] += e["usage"][k]
        for k, v in cost_parts(e["usage"], price).items():
            costs[k] += v
    total_cost = sum(costs.values())

    def pct(part, whole):
        return f"{100 * part / whole:.1f}%" if whole else "n/a"

    lines = [
        "LLM screening report: quasi-gold set (QGS)",
        "=" * 60,
        f"Generated:      {datetime.now():%Y-%m-%d %H:%M:%S}",
        f"Model:          {args.model} (reasoning effort: {args.effort})",
        f"System prompt:  {args.prompt} (sha256 {config['prompt_sha256'][:16]})",
        f"Input:          {args.input} ({total} records)",
        "",
        "Decisions",
        "-" * 60,
        f"  include (gold set)   {decisions['include']:>4}  {pct(decisions['include'], n)}",
        f"  uncertain (review)   {decisions['uncertain']:>4}  {pct(decisions['uncertain'], n)}",
        f"  exclude              {decisions['exclude']:>4}  {pct(decisions['exclude'], n)}",
        f"  screened             {n:>4} of {total}",
        f"  not screened/failed  {total - n:>4}",
        f"  model decision overridden by the decision rules: {len(overridden)}"
        + (f" (ids {', '.join(map(str, overridden))})" if overridden else ""),
        "",
        "Relevance scores (all screened)",
        "-" * 60,
    ]
    relevance = Counter(e["answer"]["relevance"] for _, e in screened)
    lines += [f"  {score}: {relevance[score]:>4}" for score in (3, 2, 1, 0)]

    lines += ["", "Criterion verdicts (all screened)", "-" * 60,
              f"  {'criterion':<26}{'yes':>6}{'no':>6}{'unclear':>9}"]
    for c in CRITERIA:
        counts = Counter(e["answer"]["criteria"][c]["verdict"] for _, e in screened)
        lines.append(f"  {c:<26}{counts['yes']:>6}{counts['no']:>6}{counts['unclear']:>9}")

    lines += ["", "Gold set: RQ coverage (a study can cover several)", "-" * 60]
    rq_counts = Counter(rq for r in gold for rq in r["rqs"].split(";") if rq)
    lines += [f"  {rq}: {rq_counts[rq]:>4}  {pct(rq_counts[rq], len(gold))}" for rq in RQS]

    lines += ["", "Gold set: by year", "-" * 60]
    years = Counter(r["year"] for r in gold)
    lines += [f"  {year}: {years[year]:>4}" for year in sorted(years)] or ["  (empty)"]

    lines += [
        "", "Tokens and cost (all screened records, including retries)", "-" * 60,
        f"  API calls                {attempts:>12,}",
        f"  input tokens             {usage['input_tokens']:>12,}",
        f"    cache reads            {usage['cached_tokens']:>12,}  {pct(usage['cached_tokens'], usage['input_tokens'])} of input",
        f"    cache writes           {usage['cache_write_tokens']:>12,}",
        f"    uncached               {usage['input_tokens'] - usage['cached_tokens'] - usage['cache_write_tokens']:>12,}",
        f"  output tokens            {usage['output_tokens']:>12,}",
        f"    reasoning              {usage['reasoning_tokens']:>12,}",
        f"  cost: uncached input     ${costs['input']:>11.4f}",
        f"  cost: cache reads        ${costs['cached']:>11.4f}",
        f"  cost: cache writes       ${costs['cache_write']:>11.4f}",
        f"  cost: output             ${costs['output']:>11.4f}",
        f"  total cost               ${total_cost:>11.4f}",
        f"  avg cost per record      ${(total_cost / n if n else 0):>11.5f}",
        f"  prices (per 1M tokens):  input ${price['input']}, cached ${price['cached']}, "
        f"cache write ${price['cache_write']}, output ${price['output']}",
        "",
        "This run",
        "-" * 60,
        f"  records screened         {run_stats['screened']:>6}",
        f"  records reused           {run_stats['reused']:>6}",
        f"  failed                   {len(run_stats['failed']):>6}"
        + (f"  (ids {', '.join(run_stats['failed'])})" if run_stats["failed"] else ""),
        f"  wall time                {fmt_duration(run_stats['elapsed']):>6}",
        f"  cost                     ${run_stats['cost']:.4f}",
        "",
        f"Gold set ({len(gold)})",
        "-" * 60,
    ]
    lines += [f"  [{r['id']:>3}] {r['year']} | {r['rqs'] or '-':<15} | {r['title']}" for r in gold] or ["  (empty)"]
    lines += ["", f"Uncertain: needs human review ({len(uncertain)})", "-" * 60]
    lines += [f"  [{r['id']:>3}] {r['year']} | rel {r['relevance']} | unclear: {r['unclear_criteria'] or '-'} | {r['title']}"
              for r in uncertain] or ["  (empty)"]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, default=ROOT / "references/references-2026-09-15.csv")
    parser.add_argument("--prompt", type=Path, default=ROOT / "system_prompt.txt")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "screening")
    parser.add_argument("--env-file", type=Path, default=ROOT / "scripts/.env")
    parser.add_argument("--model", default="gpt-5.6-luna")
    parser.add_argument("--effort", default="medium", choices=["none", "low", "medium", "high", "xhigh", "max"])
    parser.add_argument("--workers", type=int, default=4, help="parallel requests (default 4)")
    parser.add_argument("--limit", type=int, help="screen at most N new records this run")
    parser.add_argument("--max-output-tokens", type=int, default=16000)
    parser.add_argument("--max-attempts", type=int, default=3, help="attempts when the output is unusable")
    parser.add_argument("--sdk-retries", type=int, default=5, help="SDK retries for rate limits / server errors")
    parser.add_argument("--timeout", type=int, default=300, help="per-request timeout in seconds")
    args = parser.parse_args()

    if args.model not in PRICING:
        sys.exit(f"No pricing for {args.model!r}; add it to PRICING in {Path(__file__).name}.")
    load_env(args.env_file)
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        sys.exit(f"OPENAI_API_KEY not set (looked in environment and {args.env_file}).")

    client = OpenAI(api_key=api_key, max_retries=args.sdk_retries, timeout=args.timeout)
    system_prompt = args.prompt.read_text(encoding="utf-8").strip()
    with args.input.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    price = PRICING[args.model]
    config = {"model": args.model, "effort": args.effort,
              "prompt_sha256": hashlib.sha256(system_prompt.encode()).hexdigest()}

    args.out_dir.mkdir(parents=True, exist_ok=True)
    raw_path = args.out_dir / "llm_screening_raw.jsonl"
    results = load_previous(raw_path, config)
    reused = sum(1 for r in rows if str(r["id"]) in results)
    pending = [r for r in rows if str(r["id"]) not in results]
    if args.limit is not None:
        pending = pending[:args.limit]

    print(f"{len(rows)} records | {reused} already screened with this model/effort/prompt | "
          f"{len(pending)} to screen | model {args.model} (effort {args.effort}) | workers {args.workers}",
          file=sys.stderr)

    lock, stop = threading.Lock(), threading.Event()
    totals = dict.fromkeys(USAGE_KEYS, 0)
    run = {"cost": 0.0, "done": 0, "failed": [], "fatal": None}
    started = time.monotonic()

    def record_result(row, outcome, latency):
        entry = {"id": str(row["id"]), **config, **outcome, "latency_s": round(latency, 2),
                 "timestamp": datetime.now().isoformat(timespec="seconds")}
        entry["cost_usd"] = sum(cost_parts(outcome["usage"], price).values())
        if outcome["ok"]:
            entry["decision"] = rule_decision(outcome["answer"])
        with lock:
            with raw_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            for k in USAGE_KEYS:
                totals[k] += outcome["usage"][k]
            run["cost"] += entry["cost_usd"]
            run["done"] += 1
            if outcome["ok"]:
                results[entry["id"]] = entry
            else:
                run["failed"].append(entry["id"])

            u, done, n = outcome["usage"], run["done"], len(pending)
            elapsed = time.monotonic() - started
            eta = fmt_duration(elapsed / done * (n - done))
            call_cache = f"{100 * u['cached_tokens'] / u['input_tokens']:.0f}%" if u["input_tokens"] else "n/a"
            run_cache = f"{100 * totals['cached_tokens'] / totals['input_tokens']:.0f}%" if totals["input_tokens"] else "n/a"
            status = (f"{entry['decision']:<9} rel {outcome['answer']['relevance']}" if outcome["ok"]
                      else f"FAILED after {outcome['attempts']} attempts: {outcome['error'][:120]}")
            print(f"[{bar(done, n)}] {done:>3}/{n} {100 * done / n:3.0f}% | ETA {eta} | id {entry['id']:>3} {status}\n"
                  f"    in {u['input_tokens']:,} (cache read {u['cached_tokens']:,}, write {u['cache_write_tokens']:,})"
                  f" | out {u['output_tokens']:,} (reasoning {u['reasoning_tokens']:,})"
                  f" | cache hit {call_cache} call / {run_cache} run"
                  f" | ${entry['cost_usd']:.5f} call / ${run['cost']:.4f} so far",
                  file=sys.stderr, flush=True)

    def task(row):
        try:
            outcome, latency = screen(row, args, client, system_prompt, stop)
        except FatalApiError as e:
            stop.set()
            run["fatal"] = str(e)
            return
        if outcome.get("error") != "stopped":
            record_result(row, outcome, latency)

    try:
        if pending:
            # Screen one record first so the system prompt is in the cache before parallel calls.
            task(pending[0])
            if not stop.is_set() and len(pending) > 1:
                with ThreadPoolExecutor(max_workers=args.workers) as pool:
                    futures = [pool.submit(task, row) for row in pending[1:]]
                    for future in as_completed(futures):
                        future.result()
    except KeyboardInterrupt:
        stop.set()
        print("\nInterrupted; waiting for in-flight requests, then writing outputs.", file=sys.stderr)

    if run["fatal"]:
        print(f"\nStopped on a non-retryable API error:\n  {run['fatal']}", file=sys.stderr)

    run_stats = {"screened": run["done"] - len(run["failed"]), "reused": reused, "failed": run["failed"],
                 "elapsed": time.monotonic() - started, "cost": run["cost"]}
    if not results:
        sys.exit("No screened records; nothing to write.")
    gold, uncertain, report = write_outputs(args, rows, results, config, run_stats)
    print("\n" + report.split("\nGold set (")[0], file=sys.stderr)
    print(f"Wrote {len(gold)} gold / {len(uncertain)} uncertain records to {args.out_dir}/", file=sys.stderr)
    if run["fatal"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
