#!/usr/bin/env python3
"""Explicit Databricks analytics path for Decision Conflict Radar evidence."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import entire_conflict_radar as radar


SCRIPT_DIR = Path(__file__).resolve().parent
NOTEBOOK_SOURCE = SCRIPT_DIR / "databricks" / "decision_conflict_radar_analytics.py"
DEFAULT_DBFS_DIR = "dbfs:/tmp/codebase-flight-recorder/decision-conflict-radar"
DEFAULT_WORKSPACE_PATH = "/Shared/codebase-flight-recorder/decision_conflict_radar_analytics"
DEFAULT_OUTPUT_NAME = "radar-analytics-output"


class DatabricksUnavailable(RuntimeError):
    """Raised when the Databricks CLI cannot be used cleanly."""


@dataclass(frozen=True)
class DatabricksRunResult:
    profile_name: str
    dbfs_input_path: str
    dbfs_output_path: str
    workspace_path: str
    submit_output: str


def evidence_record(prompt: str, item: radar.Evidence) -> dict[str, object]:
    signals = radar.extract_signals(prompt)
    haystack = " ".join(
        part for part in (item.title, item.text, item.path, item.symbol) if part
    ).lower()
    conflict_terms = sorted(term for term in radar.RISK_TERMS if term in haystack)
    return {
        "prompt": prompt,
        "source": item.source,
        "title": item.title,
        "text": item.text,
        "commit": item.commit,
        "checkpoint": item.checkpoint,
        "path": item.path,
        "line": item.line,
        "symbol": item.symbol,
        "score": item.score,
        "risk_level": radar.risk_level(item.score),
        "reasons": list(item.reasons),
        "prompt_terms": list(signals.terms),
        "prompt_paths": list(signals.paths),
        "prompt_symbols": list(signals.symbols),
        "prompt_risk_terms": list(signals.risk_terms),
        "conflict_terms": conflict_terms,
    }


def export_radar_evidence(
    prompts: Iterable[str],
    repo: Path,
    output_path: Path,
    *,
    limit: int = 25,
    command_timeout: float = 4.0,
    runner: radar.Runner = radar.default_runner,
) -> int:
    count = 0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for prompt in prompts:
            if not prompt.strip():
                continue
            findings = radar.analyze(
                prompt,
                repo,
                runner=runner,
                limit=max(1, limit),
                command_timeout=max(0.2, command_timeout),
            )
            for item in findings:
                handle.write(json.dumps(evidence_record(prompt, item), sort_keys=True) + "\n")
                count += 1
    return count


def aggregate_records(records: Iterable[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    by_path: Counter[str] = Counter()
    by_symbol: Counter[str] = Counter()
    by_risk_level: Counter[str] = Counter()
    by_conflict_term: Counter[str] = Counter()
    severity_sum: Counter[str] = Counter()

    for record in records:
        score = int(record.get("score") or 0)
        path = str(record.get("path") or "").strip()
        symbol = str(record.get("symbol") or "").strip()
        risk_level = str(record.get("risk_level") or "LOW").strip() or "LOW"

        if path:
            by_path[path] += 1
            severity_sum[f"path:{path}"] += score
        if symbol:
            by_symbol[symbol] += 1
            severity_sum[f"symbol:{symbol}"] += score
        by_risk_level[risk_level] += 1

        for term in record.get("conflict_terms") or []:
            by_conflict_term[str(term)] += 1

    return {
        "conflict_frequency_by_path": ranked_counts(by_path, severity_sum, "path"),
        "conflict_frequency_by_symbol": ranked_counts(by_symbol, severity_sum, "symbol"),
        "risk_frequency": [{"risk_level": key, "count": count} for key, count in by_risk_level.most_common()],
        "recurring_conflict_terms": [
            {"term": key, "count": count} for key, count in by_conflict_term.most_common()
        ],
    }


def ranked_counts(counter: Counter[str], severity_sum: Counter[str], namespace: str) -> list[dict[str, object]]:
    rows = []
    for key, count in counter.most_common():
        total_score = severity_sum[f"{namespace}:{key}"]
        rows.append(
            {
                namespace: key,
                "count": count,
                "total_score": total_score,
                "average_score": round(total_score / count, 2) if count else 0,
            }
        )
    return rows


def read_prompts(args: argparse.Namespace) -> list[str]:
    prompts: list[str] = []
    if args.prompt:
        prompts.append(args.prompt)
    if args.prompt_file:
        raw = Path(args.prompt_file).read_text(encoding="utf-8")
        normalized = radar.normalize_prompt_input(raw)
        if normalized.prompt_text:
            prompts.extend(normalized.prompt_text.split("\n\n"))
        else:
            prompts.extend(line.strip() for line in raw.splitlines() if line.strip())
    return prompts


def databricks_args(profile: str | None, *args: str) -> list[str]:
    command = ["databricks", *args]
    if profile:
        command.extend(["--profile", profile])
    return command


def ensure_valid_profile(
    profile: str | None,
    *,
    runner: radar.Runner = radar.default_runner,
    cwd: Path = SCRIPT_DIR,
    timeout: float = 10.0,
) -> str:
    result = runner(databricks_args(profile, "auth", "profiles", "-o", "json"), cwd, timeout)
    if result.code != 0:
        detail = (result.stderr or result.stdout or "no diagnostic output").strip()
        raise DatabricksUnavailable(
            "Databricks CLI authentication could not be inspected. "
            f"Run `databricks auth login` or `databricks auth switch`, then retry. Detail: {detail}"
        )

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise DatabricksUnavailable(
            "Databricks CLI returned non-JSON profile data; retry with a configured CLI profile."
        ) from exc

    profiles = payload.get("profiles") or []
    selected = None
    if profile:
        selected = next((item for item in profiles if item.get("name") == profile), None)
    else:
        selected = next((item for item in profiles if item.get("default")), None)
        selected = selected or (profiles[0] if profiles else None)

    if not selected:
        raise DatabricksUnavailable(
            "No Databricks CLI profile was found. Run `databricks auth login`, then retry."
        )

    profile_name = str(selected.get("name") or profile or "default")
    if not selected.get("valid"):
        raise DatabricksUnavailable(
            f"Databricks CLI profile `{profile_name}` is not valid. "
            "Run `databricks auth login` or `databricks auth switch`, then retry."
        )
    return profile_name


def run_checked(
    args: list[str],
    *,
    action: str,
    runner: radar.Runner = radar.default_runner,
    cwd: Path = SCRIPT_DIR,
    timeout: float = 60.0,
) -> radar.CommandResult:
    result = runner(args, cwd, timeout)
    if result.code != 0:
        detail = (result.stderr or result.stdout or "no diagnostic output").strip()
        raise DatabricksUnavailable(f"Databricks {action} failed cleanly: {detail}")
    return result


def dbfs_child(directory: str, filename: str) -> str:
    return directory.rstrip("/") + "/" + filename


def workspace_parent(path: str) -> str:
    parent = str(Path(path).parent)
    return parent if parent != "." else "/"


def run_databricks_analytics(
    input_path: Path,
    *,
    dbfs_dir: str = DEFAULT_DBFS_DIR,
    workspace_path: str = DEFAULT_WORKSPACE_PATH,
    cluster_id: str,
    output_name: str = DEFAULT_OUTPUT_NAME,
    profile: str | None = None,
    wait: bool = False,
    timeout: float = 60.0,
    runner: radar.Runner = radar.default_runner,
) -> DatabricksRunResult:
    if not input_path.is_file():
        raise DatabricksUnavailable(f"Input JSONL does not exist: {input_path}")
    if not NOTEBOOK_SOURCE.is_file():
        raise DatabricksUnavailable(f"Databricks notebook source is missing: {NOTEBOOK_SOURCE}")
    if not cluster_id.strip():
        raise DatabricksUnavailable("A Databricks existing cluster id is required for `jobs submit`.")

    profile_name = ensure_valid_profile(profile, runner=runner, timeout=timeout)
    dbfs_input = dbfs_child(dbfs_dir, input_path.name)
    dbfs_output = dbfs_child(dbfs_dir, output_name)

    run_checked(
        databricks_args(profile, "fs", "mkdir", dbfs_dir),
        action="DBFS directory creation",
        runner=runner,
        timeout=timeout,
    )
    run_checked(
        databricks_args(profile, "fs", "cp", str(input_path), dbfs_input, "--overwrite"),
        action="JSONL upload",
        runner=runner,
        timeout=timeout,
    )
    run_checked(
        databricks_args(profile, "workspace", "mkdirs", workspace_parent(workspace_path)),
        action="workspace directory creation",
        runner=runner,
        timeout=timeout,
    )
    run_checked(
        databricks_args(
            profile,
            "workspace",
            "import",
            workspace_path,
            "--file",
            str(NOTEBOOK_SOURCE),
            "--format",
            "SOURCE",
            "--language",
            "PYTHON",
            "--overwrite",
        ),
        action="notebook import",
        runner=runner,
        timeout=timeout,
    )

    job_payload = {
        "run_name": "Codebase Flight Recorder Decision Conflict Radar Analytics",
        "tasks": [
            {
                "task_key": "decision_conflict_radar_analytics",
                "existing_cluster_id": cluster_id,
                "notebook_task": {
                    "notebook_path": workspace_path,
                    "base_parameters": {
                        "input_path": dbfs_input,
                        "output_path": dbfs_output,
                    },
                },
            }
        ],
    }
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json") as handle:
        json.dump(job_payload, handle, sort_keys=True)
        handle.flush()
        submit_args = databricks_args(profile, "jobs", "submit", "--json", f"@{handle.name}")
        if not wait:
            submit_args.append("--no-wait")
        submit = run_checked(
            submit_args,
            action="job submission",
            runner=runner,
            timeout=timeout,
        )

    return DatabricksRunResult(
        profile_name=profile_name,
        dbfs_input_path=dbfs_input,
        dbfs_output_path=dbfs_output,
        workspace_path=workspace_path,
        submit_output=submit.stdout.strip(),
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export and explicitly run Databricks analytics for Decision Conflict Radar evidence."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    export = subparsers.add_parser("export", help="Run the radar and write findings as JSONL.")
    export.add_argument("--prompt", help="Prompt text to analyze.")
    export.add_argument("--prompt-file", help="File containing a prompt, Codex JSONL, or one prompt per line.")
    export.add_argument("--repo", default=".", help="Repository root to inspect. Defaults to cwd.")
    export.add_argument("--output", required=True, help="Output JSONL path.")
    export.add_argument("--limit", type=int, default=25, help="Maximum radar findings per prompt.")
    export.add_argument("--command-timeout", type=float, default=4.0, help="Per-command radar timeout.")

    run = subparsers.add_parser("run", help="Upload JSONL and submit the Databricks notebook.")
    run.add_argument("--input", required=True, help="Local radar evidence JSONL file.")
    run.add_argument("--cluster-id", required=True, help="Existing Databricks cluster id for the one-time run.")
    run.add_argument("--profile", help="Databricks CLI profile name. Defaults to the active/default profile.")
    run.add_argument("--dbfs-dir", default=DEFAULT_DBFS_DIR, help="DBFS directory for inputs and outputs.")
    run.add_argument("--workspace-path", default=DEFAULT_WORKSPACE_PATH, help="Workspace notebook path.")
    run.add_argument("--output-name", default=DEFAULT_OUTPUT_NAME, help="Output directory name under --dbfs-dir.")
    run.add_argument("--wait", action="store_true", help="Wait for the Databricks job to finish.")
    run.add_argument("--timeout", type=float, default=60.0, help="Per-Databricks-CLI-command timeout.")

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        if args.command == "export":
            prompts = read_prompts(args)
            if not prompts:
                raise DatabricksUnavailable("No prompt text was provided for radar export.")
            count = export_radar_evidence(
                prompts,
                Path(args.repo).resolve(),
                Path(args.output),
                limit=args.limit,
                command_timeout=args.command_timeout,
            )
            print(f"Wrote {count} radar evidence records to {args.output}")
            return 0

        result = run_databricks_analytics(
            Path(args.input),
            dbfs_dir=args.dbfs_dir,
            workspace_path=args.workspace_path,
            cluster_id=args.cluster_id,
            output_name=args.output_name,
            profile=args.profile,
            wait=args.wait,
            timeout=args.timeout,
        )
        print(f"Uploaded input: {result.dbfs_input_path}")
        print(f"Imported notebook: {result.workspace_path}")
        print(f"Analytics output: {result.dbfs_output_path}")
        if result.submit_output:
            print(result.submit_output)
        return 0
    except DatabricksUnavailable as exc:
        print(f"Databricks analytics unavailable: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
