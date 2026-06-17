#!/usr/bin/env python3
"""Typo / grammar fixer for review bodies.

Two finding sources, merged into one report (and, with --apply, one set of edits
you review as a single `git diff`):

  1. codespell — cheap misspelling / homonym sweep over each body. Always runs
                 (via `uvx codespell`, no install needed).
  2. LLM pass  — Opus grammar / dropped-word / missing-preposition pass that
                 codespell can't catch. Synchronous on a --limit sample; the
                 full corpus goes through the Batch API (--submit then --apply).

Front matter is excluded from both passes, so author names, tags, and titles
never show up as findings.

Apply policy (aggressive — bias toward applying; git is the undo):
  codespell, lowercase single suggestion  -> apply
  codespell, multiple suggestions         -> apply the first suggestion
  codespell, Capitalized / ALL-CAPS       -> residual report (the lone guardrail:
                                             these are reliably false positives —
                                             proper nouns, acronyms)
  LLM, quote found in body                -> apply (first occurrence; whitespace-
                                             normalized retry if no exact match)
  LLM, quote not locatable                -> residual report

This script is git-agnostic: it only edits files in the working tree and writes
reports. You own branch / commit / merge. --apply is opt-in; the default is
report-only (writes scripts/typo_report.txt, touches no review files).

Run from review-cli/:
    # codespell only
    uv run python scripts/lint_typos.py
    # synchronous LLM sample (fast, ~pennies) — validate the prompt before batching
    uv run --extra llm python scripts/lint_typos.py --llm --limit 50
    # synchronous sample, applied to files (review the diff)
    uv run --extra llm python scripts/lint_typos.py --llm --limit 50 --apply
    # full corpus via Batch API:
    uv run --extra llm python scripts/lint_typos.py --submit   # phase 1: submit
    uv run --extra llm python scripts/lint_typos.py --apply    # phase 2: poll + apply

Needs the `llm` extra (anthropic SDK) and ANTHROPIC_API_KEY for any LLM/batch run.
"""
from __future__ import annotations

import argparse
import bisect
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import frontmatter

from review.config import Config

SCRIPT_DIR = Path(__file__).parent
REPORT_OUT = SCRIPT_DIR / "typo_report.txt"
RESIDUAL_OUT = SCRIPT_DIR / "residual_report.txt"
BATCH_STATE = SCRIPT_DIR / ".batch_state.json"

# codespell over-eagerly "corrects" words that are correct in book reviews.
# Add lowercase words here (comma-joined into --ignore-words-list).
CODESPELL_IGNORE = [
    "ans",  # common in fantasy/SF names; codespell -> "and"/"answer"
    "ambien",  # the drug; codespell -> "ambient"
    "protestors",  # valid variant of "protesters"
    # Real English words codespell flags as "possible typos":
    "covert", "empress", "rouge", "somme",
    # Author / character / place names recurring across reviews:
    "shepard", "shapin", "brin", "vor", "sade", "leary", "bui",
]

# Model for the LLM grammar pass. See the claude-api skill: default to the latest
# Opus. The Batch API runs the full corpus at 50% of standard pricing.
LLM_MODEL = "claude-opus-4-8"
LLM_MAX_TOKENS = 4096

LLM_SYSTEM = """\
You are a meticulous copy-editor for short book-review prose. Find only \
*objective* errors a spell-checker misses: dropped words, missing prepositions \
or articles, subject/verb disagreement, wrong-word homonyms (their/there, \
its/it's, lead/led), and dropped -s/-ed endings.

Do NOT report style, tone, word choice, Oxford commas, or anything subjective. \
When the prose is clean, return an empty list. For each error, quote the exact \
span from the text verbatim (long enough to locate it unambiguously) and give \
the corrected span."""

# Structured-output schema for the LLM pass (shared by the sync and batch paths).
RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "quote": {"type": "string"},
                    "correction": {"type": "string"},
                    "kind": {"type": "string"},
                },
                "required": ["quote", "correction", "kind"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["findings"],
    "additionalProperties": False,
}


@dataclass
class Finding:
    rel: str  # {type}/{slug}
    line: int  # 1-based line in the original file (best-effort for LLM)
    source: str  # "codespell" | "llm"
    old: str  # word (codespell) or quoted span (llm)
    corrections: list[str]  # codespell suggestions, or [correction] for llm
    kind: str = ""  # llm error kind, or ""

    def report_line(self) -> str:
        if self.source == "codespell":
            rhs = ", ".join(self.corrections)
            return f"  :{self.line}: {self.old} ==> {rhs}  [codespell]"
        corr = self.corrections[0] if self.corrections else ""
        kind = f" ({self.kind})" if self.kind else ""
        return f"  :{self.line}: {self.old!r} ==> {corr!r}{kind}  [llm]"


# --------------------------------------------------------------------------- #
# File / line helpers
# --------------------------------------------------------------------------- #
def body_start_line(raw: str) -> int:
    """1-based line number of the first body line (after the YAML front matter)."""
    lines = raw.splitlines()
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                return i + 2  # line after the closing ---
    return 1


def line_offsets(raw: str) -> list[int]:
    """Char offset where each line starts (index 0 == line 1)."""
    offsets = [0]
    for ch_i, ch in enumerate(raw):
        if ch == "\n":
            offsets.append(ch_i + 1)
    return offsets


def char_to_line(pos: int, offsets: list[int]) -> int:
    """1-based line number containing char offset `pos`."""
    return bisect.bisect_right(offsets, pos)


def iter_reviews(content_dir: Path, limit: int | None):
    mds = sorted(content_dir.rglob("*/index.md"))
    if limit is not None:
        mds = mds[:limit]
    for md in mds:
        yield md, md.parent.relative_to(content_dir).as_posix()


# --------------------------------------------------------------------------- #
# Pass 1 — codespell
# --------------------------------------------------------------------------- #
def codespell_pass(files: list[Path], body_starts: dict[Path, int]) -> list[Finding]:
    cmd = ["uvx", "codespell", "--disable-colors"]
    if CODESPELL_IGNORE:
        cmd += ["--ignore-words-list", ",".join(CODESPELL_IGNORE)]
    cmd += [str(f) for f in files]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        print("  ! uvx not found — skipping codespell pass.", file=sys.stderr)
        return []

    content_dir = Config.load().content_dir
    # codespell line: "path:line: word ==> corr1, corr2"
    pat = re.compile(r"^(?P<path>.+?):(?P<line>\d+): (?P<word>.+?) ==> (?P<corr>.+)$")
    findings: list[Finding] = []
    for raw_line in proc.stdout.splitlines():
        m = pat.match(raw_line)
        if not m:
            continue
        path = Path(m.group("path"))
        line = int(m.group("line"))
        if line < body_starts.get(path, 1):
            continue  # hit landed in the front matter — ignore
        rel = path.parent.relative_to(content_dir).as_posix()
        corrections = [c.strip() for c in m.group("corr").split(",") if c.strip()]
        findings.append(
            Finding(rel, line, "codespell", m.group("word").strip(), corrections)
        )
    return findings


# --------------------------------------------------------------------------- #
# Pass 2 — LLM grammar
# --------------------------------------------------------------------------- #
def _require_llm():
    try:
        import anthropic  # noqa: F401
    except ImportError:
        sys.exit(
            "  ! LLM passes need the anthropic SDK. Re-run with:\n"
            "      uv run --extra llm python scripts/lint_typos.py ..."
        )
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        sys.exit("  ! LLM passes need ANTHROPIC_API_KEY (or ANTHROPIC_AUTH_TOKEN) set.")


def llm_request_params(body: str) -> dict:
    """Request shape shared by the synchronous and batch paths."""
    return dict(
        model=LLM_MODEL,
        max_tokens=LLM_MAX_TOKENS,
        system=LLM_SYSTEM,
        output_config={
            "effort": "low",
            "format": {"type": "json_schema", "schema": RESULT_SCHEMA},
        },
        messages=[{"role": "user", "content": body}],
    )


def _issues_from_message(msg) -> list[dict]:
    for block in msg.content:
        if block.type == "text":
            try:
                return json.loads(block.text).get("findings", [])
            except json.JSONDecodeError:
                return []
    return []


def _find_quote_line(raw: str, quote: str, start_line: int) -> int:
    """Best-effort 1-based file line of `quote` (for reporting / ordering)."""
    needle = quote.strip().splitlines()[0].strip() if quote.strip() else ""
    if needle:
        for i, line in enumerate(raw.splitlines()):
            if needle in line:
                return i + 1
    return start_line


def _findings_from_issues(md: Path, rel: str, issues: list[dict]) -> list[Finding]:
    raw = md.read_text(encoding="utf-8")
    start = body_start_line(raw)
    out: list[Finding] = []
    for issue in issues:
        quote = issue.get("quote", "")
        correction = issue.get("correction", "")
        if not quote or correction == quote:
            continue
        out.append(
            Finding(
                rel,
                _find_quote_line(raw, quote, start),
                "llm",
                quote,
                [correction],
                issue.get("kind", ""),
            )
        )
    return out


def llm_sync_pass(reviews: list[tuple[Path, str]]) -> list[Finding]:
    """Synchronous per-file LLM pass — for --limit samples."""
    import anthropic

    client = anthropic.Anthropic()
    findings: list[Finding] = []
    for n, (md, rel) in enumerate(reviews, 1):
        body = frontmatter.load(str(md)).content
        if not body.strip():
            continue
        print(f"  llm {n}/{len(reviews)}: {rel}", file=sys.stderr)
        try:
            resp = client.messages.create(**llm_request_params(body))
        except anthropic.AuthenticationError:
            sys.exit("  ! No valid ANTHROPIC_API_KEY — stopping.")
        except anthropic.APIError as e:
            print(f"  ! API error on {rel}: {e} — skipping.", file=sys.stderr)
            continue
        findings += _findings_from_issues(md, rel, _issues_from_message(resp))
    return findings


# --------------------------------------------------------------------------- #
# Batch API — two phase
# --------------------------------------------------------------------------- #
def submit_batch(reviews: list[tuple[Path, str]], content_dir: Path) -> None:
    import anthropic
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    requests = []
    id_map: dict[str, str] = {}
    for i, (md, rel) in enumerate(reviews):
        body = frontmatter.load(str(md)).content
        if not body.strip():
            continue
        cid = f"r{i}"
        id_map[cid] = rel
        requests.append(
            Request(
                custom_id=cid,
                params=MessageCreateParamsNonStreaming(**llm_request_params(body)),
            )
        )

    if not requests:
        sys.exit("  ! No non-empty review bodies to submit.")

    client = anthropic.Anthropic()
    batch = client.messages.batches.create(requests=requests)
    BATCH_STATE.write_text(
        json.dumps(
            {
                "batch_id": batch.id,
                "model": LLM_MODEL,
                "content_dir": str(content_dir),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "count": len(requests),
                "map": id_map,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Submitted batch {batch.id} — {len(requests)} review(s).")
    print(f"State written to {BATCH_STATE.name}.")
    print(
        "Most batches finish within an hour. When ready, run:\n"
        "    uv run --extra llm python scripts/lint_typos.py --apply"
    )


def load_batch_findings(content_dir: Path, poll_seconds: int = 30) -> list[Finding]:
    import anthropic

    state = json.loads(BATCH_STATE.read_text(encoding="utf-8"))
    client = anthropic.Anthropic()
    bid = state["batch_id"]

    while True:
        batch = client.messages.batches.retrieve(bid)
        if batch.processing_status == "ended":
            break
        c = batch.request_counts
        print(
            f"  batch {bid}: {batch.processing_status} "
            f"(processing {c.processing}, succeeded {c.succeeded}, "
            f"errored {c.errored}) — waiting {poll_seconds}s…",
            file=sys.stderr,
        )
        time.sleep(poll_seconds)

    id_map = state["map"]
    findings: list[Finding] = []
    errored = 0
    for result in client.messages.batches.results(bid):
        rel = id_map.get(result.custom_id)
        if rel is None:
            continue
        if result.result.type != "succeeded":
            errored += 1
            continue
        md = content_dir / rel / "index.md"
        if not md.exists():
            continue
        findings += _findings_from_issues(
            md, rel, _issues_from_message(result.result.message)
        )
    if errored:
        print(f"  ! {errored} batch request(s) did not succeed.", file=sys.stderr)
    return findings


# --------------------------------------------------------------------------- #
# Planning / applying
# --------------------------------------------------------------------------- #
@dataclass
class FilePlan:
    edits: list[tuple[int, int, str, Finding]] = field(default_factory=list)  # start,end,new
    residuals: list[tuple[Finding, str]] = field(default_factory=list)  # finding, reason


def _codespell_span(raw: str, offsets: list[int], line_no: int, word: str):
    if line_no < 1 or line_no > len(offsets):
        return None
    start = offsets[line_no - 1]
    end = offsets[line_no] - 1 if line_no < len(offsets) else len(raw)
    m = re.search(r"\b" + re.escape(word) + r"\b", raw[start:end])
    if not m:
        return None
    return start + m.start(), start + m.end()


def _llm_span(raw: str, body_start_char: int, quote: str):
    """First occurrence of `quote` in the body; whitespace-normalized retry."""
    body = raw[body_start_char:]
    idx = body.find(quote)
    if idx != -1:
        return body_start_char + idx, body_start_char + idx + len(quote)
    toks = quote.split()
    if not toks:
        return None
    pat = re.compile(r"\s+".join(re.escape(t) for t in toks))
    m = pat.search(body)
    if m:
        return body_start_char + m.start(), body_start_char + m.end()
    return None


def plan_file(raw: str, findings: list[Finding]) -> FilePlan:
    offsets = line_offsets(raw)
    body_start_char = offsets[body_start_line(raw) - 1] if offsets else 0
    plan = FilePlan()
    for f in findings:
        if f.source == "codespell":
            if f.old[:1].isupper():
                plan.residuals.append((f, "capitalized/acronym — likely a proper noun"))
                continue
            new = f.corrections[0] if f.corrections else ""
            span = _codespell_span(raw, offsets, f.line, f.old)
            if span is None:
                plan.residuals.append((f, "word not found on its line"))
                continue
            plan.edits.append((span[0], span[1], new, f))
        else:  # llm
            new = f.corrections[0] if f.corrections else ""
            span = _llm_span(raw, body_start_char, f.old)
            if span is None:
                plan.residuals.append((f, "quote not locatable in body"))
                continue
            plan.edits.append((span[0], span[1], new, f))
    return plan


def apply_edits(raw: str, edits: list[tuple[int, int, str, Finding]]) -> str:
    # Apply right-to-left so earlier offsets stay valid.
    for start, end, new, _ in sorted(edits, key=lambda e: e[0], reverse=True):
        raw = raw[:start] + new + raw[end:]
    return raw


# --------------------------------------------------------------------------- #
# Reports
# --------------------------------------------------------------------------- #
def _group(findings: list[Finding]) -> dict[str, list[Finding]]:
    by_rel: dict[str, list[Finding]] = {}
    for f in findings:
        by_rel.setdefault(f.rel, []).append(f)
    for fs in by_rel.values():
        fs.sort(key=lambda f: (f.line, f.source))
    return by_rel


def write_report(findings: list[Finding], content_dir: Path) -> tuple[int, int]:
    """Dry-run report: shows which findings would apply vs. go to residual."""
    by_rel = _group(findings)
    n_apply = n_resid = 0
    with open(REPORT_OUT, "w", encoding="utf-8") as out:
        out.write("# Typo / grammar findings (dry run — nothing applied)\n")
        out.write("# [*] would auto-apply   [R] -> residual report\n\n")
        for rel in sorted(by_rel):
            md = content_dir / rel / "index.md"
            raw = md.read_text(encoding="utf-8")
            plan = plan_file(raw, by_rel[rel])
            resid_ids = {id(f) for f, _ in plan.residuals}
            out.write(f"\n{rel}/index.md\n")
            for f in by_rel[rel]:
                tag = "R" if id(f) in resid_ids else "*"
                out.write(f"  [{tag}]{f.report_line()[2:]}\n")
            n_apply += len(plan.edits)
            n_resid += len(plan.residuals)
    return n_apply, n_resid


def apply_all(findings: list[Finding], content_dir: Path) -> tuple[int, int]:
    by_rel = _group(findings)
    n_apply = 0
    residuals: list[tuple[str, Finding, str]] = []
    for rel, fs in by_rel.items():
        md = content_dir / rel / "index.md"
        raw = md.read_text(encoding="utf-8")
        plan = plan_file(raw, fs)
        if plan.edits:
            md.write_text(apply_edits(raw, plan.edits), encoding="utf-8")
            n_apply += len(plan.edits)
        for f, reason in plan.residuals:
            residuals.append((rel, f, reason))

    residuals.sort(key=lambda r: (r[0], r[1].line))
    with open(RESIDUAL_OUT, "w", encoding="utf-8") as out:
        out.write("# Residual findings — could not be auto-applied; handle by hand.\n")
        out.write(f"# {len(residuals)} finding(s).\n\n")
        current = None
        for rel, f, reason in residuals:
            if rel != current:
                current = rel
                out.write(f"\n{rel}/index.md\n")
            out.write(f"{f.report_line()}  -> {reason}\n")
    return n_apply, len(residuals)


# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=None, help="only the first N reviews")
    ap.add_argument("--llm", action="store_true", help="run the LLM pass synchronously")
    ap.add_argument("--submit", action="store_true", help="submit the full LLM pass as a batch")
    ap.add_argument("--apply", action="store_true", help="write fixes into files (else report only)")
    args = ap.parse_args()

    content_dir = Config.load().content_dir

    # Phase 1: submit a batch and exit.
    if args.submit:
        _require_llm()
        reviews = list(iter_reviews(content_dir, args.limit))
        print(f"Submitting {len(reviews)} review(s) to the Batch API…")
        submit_batch(reviews, content_dir)
        return 0

    reviews = list(iter_reviews(content_dir, args.limit))
    files = [md for md, _ in reviews]
    body_starts = {md: body_start_line(md.read_text(encoding="utf-8")) for md in files}
    print(f"Linting {len(files)} review(s)…")

    print("Pass 1: codespell")
    findings = codespell_pass(files, body_starts)
    print(f"  {len(findings)} codespell hit(s).")

    # LLM findings: prefer a pending batch unless --llm forces synchronous.
    if BATCH_STATE.exists() and not args.llm:
        print("Pass 2: LLM grammar (Batch API)")
        _require_llm()
        llm_findings = load_batch_findings(content_dir)
        print(f"  {len(llm_findings)} LLM finding(s).")
        findings += llm_findings
    elif args.llm:
        print("Pass 2: LLM grammar (synchronous)")
        _require_llm()
        llm_findings = llm_sync_pass(reviews)
        print(f"  {len(llm_findings)} LLM finding(s).")
        findings += llm_findings

    if args.apply:
        n_apply, n_resid = apply_all(findings, content_dir)
        print(f"\nApplied {n_apply} fix(es) to files. Review with: git diff --word-diff")
        print(f"{n_resid} residual finding(s) -> {RESIDUAL_OUT} (handle by hand).")
    else:
        n_apply, n_resid = write_report(findings, content_dir)
        print(f"\nWrote findings -> {REPORT_OUT}")
        print(f"  {n_apply} would auto-apply, {n_resid} would go to residual report.")
        print("Re-run with --apply to write the fixes into files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
