import contextlib
import io
import json
import os
import sys
import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import entire_conflict_radar as radar


class FakeRunner:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __call__(self, args, cwd, timeout):
        self.calls.append((args, cwd, timeout))
        for predicate, response in self.responses:
            if predicate(args):
                return response
        return radar.CommandResult(1, "", "unexpected command")


class DecisionConflictRadarTests(unittest.TestCase):
    def test_original_direct_input_format_normalizes_to_prompt_text(self):
        prompt = "Remove failed checkpoint transcript parser path"
        payload = {"user_prompt": prompt, "hook_event_name": "UserPromptSubmit"}

        normalized = radar.normalize_prompt_input(json.dumps(payload))

        self.assertEqual(normalized.prompt_text, prompt)
        self.assertFalse(normalized.incomplete)
        self.assertEqual(radar.extract_prompt_text(json.dumps(payload)), prompt)

    def test_new_nested_codex_response_item_and_event_msg_format(self):
        response_item_prompt = (
            "Replace sanitizeTranscriptForStorage in "
            "agents/entire-agent-grok/internal/grok/native_transcript.go"
        )
        event_msg_prompt = "Remove failed checkpoint transcript path"
        records = [
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": response_item_prompt}],
                },
            },
            {
                "type": "event_msg",
                "payload": {
                    "item": {
                        "type": "UserMessage",
                        "content": [{"type": "text", "text": event_msg_prompt}],
                    }
                },
            },
        ]

        normalized = radar.normalize_prompt_input("\n".join(json.dumps(record) for record in records))

        self.assertIn(response_item_prompt, normalized.prompt_text)
        self.assertIn(event_msg_prompt, normalized.prompt_text)
        self.assertFalse(normalized.incomplete)

    def test_unknown_event_record_is_ignored_without_using_metadata_as_prompt(self):
        payload = {
            "type": "future_lifecycle_event",
            "payload": {
                "message": "Remove failed protocol storage path",
                "content": [{"type": "text", "text": "Replace checkpoint writer"}],
            },
        }

        normalized = radar.normalize_prompt_input(json.dumps(payload))

        self.assertEqual(normalized.prompt_text, "")
        self.assertFalse(normalized.incomplete)
        self.assertEqual(normalized.unknown_events, 1)

    def test_incomplete_jsonl_recovers_partial_prompt_and_marks_context(self):
        prompt = "Remove failed protocol storage path"
        good_record = {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": prompt}],
            },
        }
        raw = json.dumps(good_record) + "\n" + '{"type":"response_item","payload":'

        normalized = radar.normalize_prompt_input(raw)

        self.assertEqual(normalized.prompt_text, prompt)
        self.assertTrue(normalized.incomplete)
        self.assertIn(
            "incomplete input context",
            radar.render_warning([], incomplete_context=normalized.incomplete),
        )

    def test_malformed_json_is_partial_raw_context_not_a_crash(self):
        raw = '{"user_prompt":"Remove failed protocol storage path"'

        normalized = radar.normalize_prompt_input(raw)

        self.assertIn("Remove failed protocol storage path", normalized.prompt_text)
        self.assertTrue(normalized.incomplete)

    def test_extracts_prompt_paths_symbols_and_risk_terms(self):
        prompt = (
            "Replace sanitizeTranscriptForStorage() in "
            "agents/entire-agent-grok/internal/grok/native_transcript.go:430 "
            "with a protocol storage hook because the old approach failed."
        )

        signals = radar.extract_signals(prompt)

        self.assertIn("agents/entire-agent-grok/internal/grok/native_transcript.go:430", signals.paths)
        self.assertIn("sanitizeTranscriptForStorage", signals.symbols)
        self.assertIn("replace", signals.risk_terms)
        self.assertIn("failed", signals.risk_terms)
        self.assertIn("protocol", signals.risk_terms)
        self.assertIn("grok", signals.terms)

    def test_ranks_conflict_like_results_above_generic_matches(self):
        signals = radar.extract_signals(
            "Replace sanitizeTranscriptForStorage in agents/entire-agent-grok/internal/grok/native_transcript.go"
        )
        items = [
            radar.Evidence(
                source="entire search",
                title="Update Grok README",
                text="General Grok transcript documentation.",
                commit="1111111",
            ),
            radar.Evidence(
                source="git history",
                title="Strip encrypted_content from stored Grok transcripts",
                text=(
                    "Rejected adding a sanitizer hook to the external agent protocol "
                    "because redaction corrupted encrypted_content storage."
                ),
                commit="c4c0eb999",
                checkpoint="3b8de7933fe8",
                path="agents/entire-agent-grok/internal/grok/native_transcript.go",
                symbol="sanitizeTranscriptForStorage",
            ),
        ]

        ranked = radar.rank_evidence(items, signals)

        self.assertGreaterEqual(len(ranked), 2)
        self.assertEqual(ranked[0].commit, "c4c0eb999")
        self.assertEqual(radar.risk_level(ranked[0].score), "HIGH")

    def test_git_history_fallback_when_entire_search_fails(self):
        git_log = (
            "c4c0eb999\x00Strip encrypted_content from stored Grok transcripts\x00"
            "Rejected a protocol sanitizer hook because it corrupted transcript storage.\n"
            "Entire-Checkpoint: 3b8de7933fe8\n"
            "\x1e"
        )
        fake = FakeRunner(
            [
                (lambda args: args[0].endswith("entire") and "search" in args, radar.CommandResult(1, "", "auth failed")),
                (lambda args: args[:2] == ["git", "log"], radar.CommandResult(0, git_log, "")),
            ]
        )

        findings = radar.analyze(
            "Add a protocol sanitizer hook for Grok transcript storage",
            Path("/tmp/nonexistent-radar-repo"),
            runner=fake,
        )

        self.assertEqual(findings[0].commit, "c4c0eb999")
        self.assertEqual(findings[0].checkpoint, "3b8de7933fe8")
        self.assertIn("git history", findings[0].source)

    def test_analyze_performs_no_repository_writes(self):
        fake = FakeRunner(
            [
                (lambda args: True, radar.CommandResult(1, "", "not available")),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "tracked.txt").write_text("unchanged", encoding="utf-8")
            before = snapshot(repo)

            radar.analyze("Remove failed protocol storage path", repo, runner=fake)

            self.assertEqual(snapshot(repo), before)

    def test_empty_input_produces_no_historical_conflict_warning(self):
        git_log = (
            "c4c0eb999\x00Strip encrypted_content from stored Grok transcripts\x00"
            "Rejected a protocol sanitizer hook because it corrupted transcript storage.\n"
            "Entire-Checkpoint: 3b8de7933fe8\n"
            "\x1e"
        )
        fake = FakeRunner(
            [
                (lambda args: args[:2] == ["git", "log"], radar.CommandResult(0, git_log, "")),
            ]
        )

        findings = radar.analyze("", Path("/tmp/nonexistent-radar-repo"), runner=fake)

        self.assertEqual(findings, [])
        self.assertEqual(
            radar.render_warning(findings),
            "Decision Conflict Radar: no strong historical conflicts found.",
        )
        self.assertEqual(fake.calls, [])
        normalized = radar.normalize_prompt_input("")
        self.assertEqual(normalized.prompt_text, "")
        self.assertFalse(normalized.incomplete)

    def test_codex_hook_with_no_stdin_available_does_not_block(self):
        read_fd, write_fd = os.pipe()
        try:
            with os.fdopen(read_fd, "r", encoding="utf-8") as stdin:
                stdout = io.StringIO()
                start = time.monotonic()
                with patch.object(sys, "stdin", stdin), contextlib.redirect_stdout(stdout):
                    code = radar.main(["--codex-hook", "--repo", ".", "--limit", "1", "--command-timeout", "0.2"])
                elapsed = time.monotonic() - start
        finally:
            os.close(write_fd)

        self.assertEqual(code, 0)
        self.assertLess(elapsed, 0.5)
        self.assertEqual(stdout.getvalue(), "")

    def test_codex_hook_with_valid_payload_normalizes_and_analyzes(self):
        prompt = "Add a unit test for the radar"
        payload = {"hook_event_name": "UserPromptSubmit", "turn_id": "turn-1", "prompt": prompt}
        item = radar.Evidence(
            source="git history",
            title="Add amp external agent",
            text="Add amp external agent with protocol tests.",
            commit="79fccc096a45",
            checkpoint="125b3e427dda",
            score=24,
            reasons=["matches intent terms: test"],
        )
        stdout = io.StringIO()
        read_fd, write_fd = os.pipe()
        try:
            os.write(write_fd, json.dumps(payload).encode("utf-8"))
            with os.fdopen(read_fd, "r", encoding="utf-8") as stdin:
                with (
                    patch.object(sys, "stdin", stdin),
                    patch.object(radar, "analyze", return_value=[item]) as analyze,
                    contextlib.redirect_stdout(stdout),
                ):
                    code = radar.main(["--codex-hook", "--repo", ".", "--limit", "1", "--command-timeout", "0.2"])
        finally:
            os.close(write_fd)

        self.assertEqual(code, 0)
        analyze.assert_called_once()
        self.assertEqual(analyze.call_args.args[0], prompt)
        emitted = json.loads(stdout.getvalue())
        self.assertIn("systemMessage", emitted)
        self.assertIn("Decision Conflict Radar: HIGH risk", emitted["systemMessage"])

    def test_codex_hook_with_malformed_input_uses_incomplete_normalization(self):
        raw = '{"user_prompt":"Remove failed protocol storage path"'
        stdout = io.StringIO()

        with (
            patch.object(sys, "stdin", io.StringIO(raw)),
            patch.object(radar, "analyze", return_value=[]),
            contextlib.redirect_stdout(stdout),
        ):
            code = radar.main(["--codex-hook", "--repo", ".", "--limit", "1", "--command-timeout", "0.2"])

        self.assertEqual(code, 0)
        emitted = json.loads(stdout.getvalue())
        self.assertIn("incomplete input context", emitted["systemMessage"])

    def test_hook_warning_payload_is_codex_system_message(self):
        item = radar.Evidence(
            source="git history",
            title="Rejected protocol sanitizer hook",
            text="Rejected protocol sanitizer hook because it failed storage redaction.",
            commit="c4c0eb999430",
            checkpoint="3b8de7933fe8",
            score=24,
            reasons=["historical risk terms: rejected, failed, protocol, storage"],
        )

        payload = json.loads(json.dumps({"systemMessage": radar.render_warning([item])}))

        self.assertIn("systemMessage", payload)
        self.assertIn("Decision Conflict Radar: HIGH risk", payload["systemMessage"])


class CodexHookConfigTests(unittest.TestCase):
    def test_codex_user_prompt_submit_invokes_radar_non_blocking_and_preserves_entire(self):
        hooks_path = Path(__file__).resolve().parents[2] / ".codex" / "hooks.json"
        config = json.loads(hooks_path.read_text(encoding="utf-8"))
        hooks = config["hooks"]["UserPromptSubmit"][0]["hooks"]
        commands = [hook["command"] for hook in hooks]

        self.assertTrue(
            any("tools/entire-conflict-radar/entire-conflict-radar" in command for command in commands)
        )
        self.assertTrue(any("entire hooks codex user-prompt-submit" in command for command in commands))

        radar_command = next(
            command
            for command in commands
            if "tools/entire-conflict-radar/entire-conflict-radar" in command
        )
        self.assertIn("--codex-hook", radar_command)
        self.assertIn("|| true", radar_command)


def snapshot(root):
    records = []
    for current, dirs, files in os.walk(root):
        dirs.sort()
        files.sort()
        for name in files:
            path = Path(current) / name
            rel = path.relative_to(root)
            records.append((str(rel), path.read_bytes()))
    return records


if __name__ == "__main__":
    unittest.main()
