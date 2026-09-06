#!/usr/bin/env python3
"""Read-only Decision Conflict Radar for Entire/Codex prompts."""

from __future__ import annotations

import argparse
import json
import os
import re
import select
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable


RISK_TERMS = {
    "revert",
    "reverted",
    "reverting",
    "failed",
    "failure",
    "rejected",
    "reject",
    "replace",
    "replaced",
    "remove",
    "removed",
    "deprecated",
    "breaking",
    "overwrite",
    "corrupt",
    "corrupted",
    "protocol",
    "storage",
    "checkpoint",
    "transcript",
}

STOP_WORDS = {
    "about",
    "after",
    "again",
    "also",
    "before",
    "being",
    "build",
    "change",
    "command",
    "could",
    "current",
    "detect",
    "does",
    "go",
    "files",
    "from",
    "have",
    "into",
    "make",
    "must",
    "need",
    "only",
    "prompt",
    "repo",
    "repository",
    "should",
    "that",
    "the",
    "their",
    "there",
    "this",
    "through",
    "using",
    "when",
    "where",
    "will",
    "with",
    "work",
}

PATH_RE = re.compile(
    r"(?<![\w./-])(?:\.{1,2}/)?(?:[\w.-]+/)+[\w.-]+(?::\d+)?"
    r"|(?<![\w./-])[\w.-]+\.(?:go|ts|tsx|js|jsx|py|rs|md|json|toml|ya?ml|sh)(?::\d+)?"
)
SYMBOL_RE = re.compile(
    r"\b[A-Z][A-Za-z0-9_]{2,}\b"
    r"|\b[a-z_][A-Za-z0-9_]*_[A-Za-z0-9_]+\b"
    r"|\b[a-z][A-Za-z0-9_]*[A-Z][A-Za-z0-9_]*\b"
    r"|\b[A-Za-z_][A-Za-z0-9_]*\(\)"
)
WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")
COMMIT_RE = re.compile(r"\b[0-9a-f]{7,40}\b", re.IGNORECASE)
HOOK_STDIN_IDLE_TIMEOUT = 0.1
HOOK_STDIN_MAX_BYTES = 1024 * 1024
HOOK_STDIN_CHUNK_SIZE = 64 * 1024


@dataclass(frozen=True)
class PromptSignals:
    terms: tuple[str, ...]
    paths: tuple[str, ...]
    symbols: tuple[str, ...]
    risk_terms: tuple[str, ...]


@dataclass
class CommandResult:
    code: int
    stdout: str
    stderr: str = ""


@dataclass
class Evidence:
    source: str
    title: str
    text: str
    commit: str = ""
    checkpoint: str = ""
    path: str = ""
    line: str = ""
    symbol: str = ""
    score: int = 0
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class NormalizedPromptInput:
    prompt_text: str
    incomplete: bool = False
    unknown_events: int = 0


Runner = Callable[[list[str], Path, float], CommandResult]


def default_runner(args: list[str], cwd: Path, timeout: float) -> CommandResult:
    try:
        completed = subprocess.run(
            args,
            cwd=str(cwd),
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CommandResult(code=1, stdout="", stderr=str(exc))
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def unique_ordered(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        cleaned = value.strip("`'\".,;()[]{}")
        key = cleaned.lower()
        if cleaned and key not in seen:
            seen.add(key)
            out.append(cleaned)
    return tuple(out)


def extract_prompt_text(raw: str) -> str:
    return normalize_prompt_input(raw).prompt_text


def read_codex_hook_stdin(
    stream: Any,
    idle_timeout: float = HOOK_STDIN_IDLE_TIMEOUT,
    max_bytes: int = HOOK_STDIN_MAX_BYTES,
) -> str:
    try:
        fd = stream.fileno()
    except (AttributeError, OSError, ValueError):
        try:
            return stream.read()
        except Exception:
            return ""

    try:
        if stream.isatty():
            return ""
    except Exception:
        pass

    chunks: list[bytes] = []
    remaining = max(0, max_bytes)
    while remaining:
        try:
            ready, _, _ = select.select([fd], [], [], idle_timeout)
        except (OSError, ValueError):
            return ""
        if not ready:
            break
        try:
            chunk = os.read(fd, min(HOOK_STDIN_CHUNK_SIZE, remaining))
        except BlockingIOError:
            break
        except OSError:
            return ""
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)

    encoding = getattr(stream, "encoding", None) or "utf-8"
    return b"".join(chunks).decode(encoding, errors="replace")


def normalize_prompt_input(raw: str) -> NormalizedPromptInput:
    stripped = raw.strip()
    if not stripped:
        return NormalizedPromptInput("")
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        jsonl = normalize_jsonl_prompt_input(raw)
        if jsonl.prompt_text or jsonl.incomplete or jsonl.unknown_events:
            return jsonl
        return NormalizedPromptInput(stripped, incomplete=looks_like_json(stripped))

    found = find_prompt_value(parsed)
    if found:
        return NormalizedPromptInput(found)
    if isinstance(parsed, dict) and is_event_record(parsed):
        return NormalizedPromptInput("", unknown_events=0 if is_known_event_record(parsed) else 1)
    return NormalizedPromptInput(stripped)


def normalize_jsonl_prompt_input(raw: str) -> NormalizedPromptInput:
    prompts: list[str] = []
    incomplete = False
    unknown_events = 0
    saw_jsonl_shape = False
    parsed_records = 0

    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if not looks_like_json(stripped):
            incomplete = True
            continue
        saw_jsonl_shape = True
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            incomplete = True
            continue
        parsed_records += 1
        found = find_prompt_value(parsed)
        if found:
            prompts.append(found)
        elif isinstance(parsed, dict) and is_event_record(parsed) and not is_known_event_record(parsed):
            unknown_events += 1

    if not saw_jsonl_shape:
        return NormalizedPromptInput("")

    prompt_text = "\n\n".join(unique_ordered(prompts))
    if not prompt_text and incomplete and parsed_records == 0:
        prompt_text = raw.strip()

    return NormalizedPromptInput(prompt_text, incomplete=incomplete, unknown_events=unknown_events)


def looks_like_json(value: str) -> bool:
    return value.startswith("{") or value.startswith("[")


def find_prompt_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        for item in value:
            found = find_prompt_value(item)
            if found:
                return found
    if isinstance(value, dict):
        event_prompt = find_event_prompt_value(value)
        if event_prompt:
            return event_prompt
        if is_event_record(value):
            return ""
        for key in ("user_prompt", "userPrompt", "prompt", "message", "content", "input"):
            if key in value:
                found = find_prompt_field_value(value[key])
                if found:
                    return found
        for item in value.values():
            found = find_prompt_value(item)
            if found:
                return found
    return ""


def find_prompt_field_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        text_parts = [text for item in value if (text := find_content_block_text(item))]
        if text_parts:
            return "\n".join(text_parts)
        for item in value:
            found = find_prompt_field_value(item)
            if found:
                return found
        return ""
    if isinstance(value, dict):
        block_text = find_content_block_text(value)
        if block_text:
            return block_text
        return find_prompt_value(value)
    return ""


def find_content_block_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return ""
    text = value.get("text")
    block_type = value.get("type")
    if isinstance(text, str) and (
        block_type in (None, "text", "input_text", "output_text") or str(block_type).endswith("_text")
    ):
        return text
    return ""


def is_event_record(value: dict[str, Any]) -> bool:
    return "type" in value and "payload" in value


def is_known_event_record(value: dict[str, Any]) -> bool:
    return value.get("type") in {
        "response_item",
        "event_msg",
        "session_meta",
        "world_state",
        "turn_context",
        "token_usage_record",
    }


def find_event_prompt_value(value: dict[str, Any]) -> str:
    record_type = value.get("type")
    payload = value.get("payload")

    if record_type == "response_item":
        if not isinstance(payload, dict):
            return ""
        if payload.get("type") == "message" and payload.get("role") == "user":
            return find_prompt_field_value(payload.get("content"))
        return ""

    if record_type == "event_msg":
        if not isinstance(payload, dict):
            return ""
        item = payload.get("item")
        if not isinstance(item, dict):
            return ""
        if item.get("type") == "UserMessage":
            return find_prompt_field_value(item.get("content"))
        return ""

    return ""


def extract_signals(prompt: str) -> PromptSignals:
    paths = unique_ordered(match.group(0) for match in PATH_RE.finditer(prompt))
    path_terms = [
        part.lower()
        for path in paths
        for part in re.split(r"[/_.:-]+", path)
        if len(part) > 2 and part.lower() not in STOP_WORDS
    ]

    symbols = unique_ordered(
        match.group(0).removesuffix("()") for match in SYMBOL_RE.finditer(prompt)
    )
    symbol_words = {symbol.lower() for symbol in symbols}

    risk_terms = unique_ordered(
        word.lower()
        for word in WORD_RE.findall(prompt)
        if word.lower() in RISK_TERMS
    )

    terms = unique_ordered(
        word.lower()
        for word in WORD_RE.findall(prompt)
        if word.lower() not in STOP_WORDS
        and word.lower() not in RISK_TERMS
        and word.lower() not in symbol_words
    )
    terms = unique_ordered(list(terms) + path_terms)

    return PromptSignals(
        terms=terms[:12],
        paths=paths[:8],
        symbols=symbols[:8],
        risk_terms=risk_terms[:8],
    )


def build_query(signals: PromptSignals) -> str:
    parts = list(signals.terms[:8]) + list(signals.symbols[:4])
    parts += [Path(path.split(":", 1)[0]).name for path in signals.paths[:4]]
    parts += list(signals.risk_terms[:4])
    return " ".join(unique_ordered(parts))[:240]


def find_entire(repo: Path) -> str:
    local = repo / "entire"
    if local.is_file() and os.access(local, os.X_OK):
        return str(local)
    return "entire"


def analyze(
    prompt: str,
    repo: Path,
    runner: Runner = default_runner,
    limit: int = 3,
    command_timeout: float = 4.0,
) -> list[Evidence]:
    signals = extract_signals(prompt)
    if not any((signals.terms, signals.paths, signals.symbols, signals.risk_terms)):
        return []

    query = build_query(signals)
    evidence: list[Evidence] = []

    if query:
        entire = find_entire(repo)
        search = runner(
            [entire, "search", query, "--json", "--compact", "--limit", "8"],
            repo,
            command_timeout,
        )
        evidence.extend(parse_search_output(search.stdout, "entire search") if search.code == 0 else [])

        code_query = build_code_query(signals)
        if code_query:
            code = runner(
                [entire, "search", "--code", code_query, "--json", "--limit", "8"],
                repo,
                command_timeout,
            )
            evidence.extend(parse_search_output(code.stdout, "entire code search") if code.code == 0 else [])

    evidence.extend(load_git_history(repo, runner))

    ranked = rank_evidence(evidence, signals)
    return ranked[:limit]


def build_code_query(signals: PromptSignals) -> str:
    path_bits = [Path(path.split(":", 1)[0]).name for path in signals.paths[:4]]
    parts = list(signals.symbols[:5]) + path_bits + list(signals.terms[:4])
    return " ".join(unique_ordered(parts))[:160]


def parse_search_output(output: str, source: str) -> list[Evidence]:
    if not output.strip():
        return []
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError:
        return [
            Evidence(source=source, title=line[:100], text=line)
            for line in output.splitlines()
            if line.strip()
        ]
    found: list[Evidence] = []
    walk_json(parsed, source, found)
    return dedupe_evidence(found)


def walk_json(value: Any, source: str, out: list[Evidence]) -> None:
    if isinstance(value, list):
        for item in value:
            walk_json(item, source, out)
        return
    if not isinstance(value, dict):
        return

    text = collect_text(value)
    title = first_string(value, "title", "message", "subject", "name", "summary")
    commit = first_string(value, "commit", "commit_hash", "commit_sha", "sha", "hash")
    checkpoint = first_string(value, "checkpoint", "checkpoint_id", "checkpointId")
    path = first_string(value, "path", "file", "filename", "filepath")
    line = str(value.get("line") or value.get("line_number") or value.get("lineNumber") or "")
    symbol = first_string(value, "symbol", "function", "name")

    if text or commit or path:
        if not title:
            title = text[:100] if text else path or commit
        if not commit:
            match = COMMIT_RE.search(text)
            commit = match.group(0) if match else ""
        out.append(
            Evidence(
                source=source,
                title=title,
                text=text,
                commit=commit,
                checkpoint=checkpoint,
                path=path,
                line=line,
                symbol=symbol,
            )
        )

    for item in value.values():
        if isinstance(item, (dict, list)):
            walk_json(item, source, out)


def collect_text(value: dict[str, Any]) -> str:
    fields = (
        "title",
        "message",
        "summary",
        "body",
        "content",
        "snippet",
        "context",
        "description",
        "text",
        "reason",
    )
    parts: list[str] = []
    for field_name in fields:
        item = value.get(field_name)
        if isinstance(item, str):
            parts.append(item)
    return "\n".join(unique_ordered(parts))


def first_string(value: dict[str, Any], *keys: str) -> str:
    for key in keys:
        item = value.get(key)
        if isinstance(item, str) and item.strip():
            return item.strip()
    return ""


def dedupe_evidence(items: list[Evidence]) -> list[Evidence]:
    seen: set[tuple[str, str, str, str]] = set()
    out: list[Evidence] = []
    for item in items:
        key = (item.source, item.commit, item.path, item.title[:80])
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def load_git_history(repo: Path, runner: Runner) -> list[Evidence]:
    result = runner(
        ["git", "log", "--all", "--max-count=120", "--format=%H%x00%s%x00%B%x1e"],
        repo,
        3.0,
    )
    if result.code != 0:
        return []

    out: list[Evidence] = []
    for record in result.stdout.split("\x1e"):
        record = record.strip()
        if not record:
            continue
        parts = record.split("\x00", 2)
        if len(parts) != 3:
            continue
        commit, subject, body = parts
        checkpoint_match = re.search(r"Entire-Checkpoint:\s*([^\s]+)", body)
        out.append(
            Evidence(
                source="git history",
                title=subject.strip(),
                text=f"{subject.strip()}\n{body.strip()}",
                commit=commit.strip(),
                checkpoint=checkpoint_match.group(1) if checkpoint_match else "",
            )
        )
    return out


def rank_evidence(items: list[Evidence], signals: PromptSignals) -> list[Evidence]:
    terms = {term.lower() for term in signals.terms}
    risk_terms = {term.lower() for term in signals.risk_terms}
    paths = {path.lower().split(":", 1)[0] for path in signals.paths}
    path_names = {Path(path).name.lower() for path in paths}
    symbols = {symbol.lower() for symbol in signals.symbols}

    ranked: list[Evidence] = []
    for item in dedupe_evidence(items):
        haystack = " ".join(
            part
            for part in (item.title, item.text, item.path, item.symbol)
            if part
        ).lower()
        reasons: list[str] = []
        score = 0

        conflict_hits = sorted(term for term in RISK_TERMS if term in haystack)
        if conflict_hits:
            score += min(12, 4 * len(conflict_hits))
            reasons.append("historical risk terms: " + ", ".join(conflict_hits[:4]))

        prompt_risk_hits = sorted(term for term in risk_terms if term in haystack)
        if prompt_risk_hits:
            score += min(8, 3 * len(prompt_risk_hits))
            reasons.append("matches prompt risk terms: " + ", ".join(prompt_risk_hits[:3]))

        term_hits = sorted(term for term in terms if term in haystack)
        if term_hits:
            score += min(10, 2 * len(term_hits))
            reasons.append("matches intent terms: " + ", ".join(term_hits[:5]))

        symbol_hits = sorted(symbol for symbol in symbols if symbol in haystack)
        if symbol_hits:
            score += 6 + min(6, 2 * len(symbol_hits))
            reasons.append("matches symbols: " + ", ".join(symbol_hits[:3]))

        path_hits = sorted(
            path for path in paths if path and (path in haystack or Path(path).name.lower() in haystack)
        )
        if path_hits:
            score += 8
            reasons.append("matches paths: " + ", ".join(path_hits[:2]))
        elif item.path and Path(item.path).name.lower() in path_names:
            score += 6
            reasons.append("matches affected file: " + Path(item.path).name)

        if item.commit:
            score += 1
        if item.checkpoint:
            score += 1
        if item.source == "git history":
            score += 1
        if item.source == "entire code search":
            score += 2

        if score >= 5:
            item.score = score
            item.reasons = reasons
            ranked.append(item)

    ranked.sort(key=lambda item: (-item.score, item.source, item.title))
    return ranked


def risk_level(score: int) -> str:
    if score >= 22:
        return "HIGH"
    if score >= 12:
        return "MEDIUM"
    return "LOW"


def render_warning(items: list[Evidence], incomplete_context: bool = False) -> str:
    if not items:
        if incomplete_context:
            return (
                "Decision Conflict Radar: incomplete input context; "
                "no strong historical conflicts found."
            )
        return "Decision Conflict Radar: no strong historical conflicts found."

    highest = risk_level(items[0].score)
    lines = [
        f"Decision Conflict Radar: {highest} risk ({len(items)} possible historical conflict{'s' if len(items) != 1 else ''})",
        "",
    ]
    if incomplete_context:
        lines.extend(
            [
                "Input context: partial/incomplete; findings are based on recovered prompt text.",
                "",
            ]
        )
    for idx, item in enumerate(items, 1):
        affected = item.path or item.symbol or "not specified"
        if item.line and item.path:
            affected = f"{item.path}:{item.line}"
        lines.append(f"{idx}. {risk_level(item.score)}: {item.title.strip()[:120]}")
        lines.append(f"   Detected conflict: {summarize(item.text or item.title)}")
        lines.append(f"   Evidence: {item.source}")
        if item.commit:
            lines.append(f"   Commit: {item.commit[:12]}")
        if item.checkpoint:
            lines.append(f"   Checkpoint: {item.checkpoint}")
        lines.append(f"   Affected file/symbol: {affected}")
        lines.append(f"   Reason: {'; '.join(item.reasons[:3]) if item.reasons else 'similar historical context'}")
    return "\n".join(lines)


def summarize(text: str) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    return compact[:220] + ("..." if len(compact) > 220 else "")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Warn about historical decision conflicts for a Codex user prompt."
    )
    parser.add_argument("prompt_words", nargs="*", help="Prompt text, if not using --prompt or stdin.")
    parser.add_argument("--prompt", help="Current Codex user prompt.")
    parser.add_argument("--repo", default=".", help="Repository root to inspect. Defaults to cwd.")
    parser.add_argument("--limit", type=int, default=3, help="Maximum warnings to print.")
    parser.add_argument(
        "--codex-hook",
        action="store_true",
        help="Emit a Codex hook systemMessage only when findings exist.",
    )
    parser.add_argument(
        "--command-timeout",
        type=float,
        default=4.0,
        help="Per-command timeout for Entire/Git lookups.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    normalized = NormalizedPromptInput("")
    if args.prompt:
        prompt = args.prompt
    elif args.prompt_words:
        prompt = " ".join(args.prompt_words)
    else:
        raw = read_codex_hook_stdin(sys.stdin) if args.codex_hook else sys.stdin.read()
        normalized = normalize_prompt_input(raw)
        prompt = normalized.prompt_text

    repo = Path(args.repo).resolve()
    findings = analyze(
        prompt,
        repo,
        limit=max(1, args.limit),
        command_timeout=max(0.2, args.command_timeout),
    )
    if args.codex_hook:
        if findings or (normalized.incomplete and prompt):
            print(json.dumps({"systemMessage": render_warning(findings, normalized.incomplete)}))
    else:
        print(render_warning(findings, normalized.incomplete))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
