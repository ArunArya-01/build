import json
import os
import tempfile
import unittest
from pathlib import Path

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
