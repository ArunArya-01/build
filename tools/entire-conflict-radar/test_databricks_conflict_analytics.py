import json
import tempfile
import unittest
from pathlib import Path

import databricks_conflict_analytics as analytics
import entire_conflict_radar as radar


class FakeRunner:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []
        self.submitted_payload = None

    def __call__(self, args, cwd, timeout):
        self.calls.append((args, cwd, timeout))
        if args[:3] == ["databricks", "jobs", "submit"]:
            json_arg = args[args.index("--json") + 1]
            with Path(json_arg.removeprefix("@")).open(encoding="utf-8") as handle:
                self.submitted_payload = json.load(handle)
        for predicate, response in self.responses:
            if predicate(args):
                return response
        return radar.CommandResult(1, "", "unexpected command")


class DatabricksConflictAnalyticsTests(unittest.TestCase):
    def test_evidence_record_includes_radar_signals_and_conflict_terms(self):
        item = radar.Evidence(
            source="git history",
            title="Rejected protocol sanitizer",
            text="Rejected sanitizer because it failed transcript storage.",
            commit="abcdef1",
            checkpoint="checkpoint-1",
            path="agents/entire-agent-grok/internal/grok/native_transcript.go",
            symbol="sanitizeTranscriptForStorage",
            score=24,
            reasons=["historical risk terms: rejected, failed"],
        )

        record = analytics.evidence_record(
            "Replace sanitizeTranscriptForStorage in agents/entire-agent-grok/internal/grok/native_transcript.go",
            item,
        )

        self.assertEqual(record["risk_level"], "HIGH")
        self.assertIn("failed", record["conflict_terms"])
        self.assertIn("rejected", record["conflict_terms"])
        self.assertIn("sanitizeTranscriptForStorage", record["prompt_symbols"])
        self.assertEqual(record["path"], "agents/entire-agent-grok/internal/grok/native_transcript.go")

    def test_local_aggregate_records_matches_databricks_notebook_outputs(self):
        records = [
            {
                "path": "a.py",
                "symbol": "saveThing",
                "score": 24,
                "risk_level": "HIGH",
                "conflict_terms": ["failed", "storage"],
            },
            {
                "path": "a.py",
                "symbol": "saveThing",
                "score": 12,
                "risk_level": "MEDIUM",
                "conflict_terms": ["failed"],
            },
            {
                "path": "b.py",
                "symbol": "loadThing",
                "score": 6,
                "risk_level": "LOW",
                "conflict_terms": ["deprecated"],
            },
        ]

        aggregate = analytics.aggregate_records(records)

        self.assertEqual(aggregate["conflict_frequency_by_path"][0]["path"], "a.py")
        self.assertEqual(aggregate["conflict_frequency_by_path"][0]["count"], 2)
        self.assertEqual(aggregate["conflict_frequency_by_symbol"][0]["symbol"], "saveThing")
        self.assertEqual(aggregate["risk_frequency"][0], {"risk_level": "HIGH", "count": 1})
        self.assertEqual(aggregate["recurring_conflict_terms"][0], {"term": "failed", "count": 2})

    def test_invalid_databricks_profile_fails_cleanly(self):
        fake = FakeRunner(
            [
                (
                    lambda args: args[:3] == ["databricks", "auth", "profiles"],
                    radar.CommandResult(
                        0,
                        json.dumps({"profiles": [{"name": "DEFAULT", "valid": False, "default": True}]}),
                    ),
                ),
            ]
        )

        with self.assertRaisesRegex(analytics.DatabricksUnavailable, "profile `DEFAULT` is not valid"):
            analytics.ensure_valid_profile(None, runner=fake)

    def test_run_databricks_analytics_uses_cli_profile_and_existing_cluster(self):
        fake = FakeRunner(
            [
                (
                    lambda args: args[:3] == ["databricks", "auth", "profiles"],
                    radar.CommandResult(
                        0,
                        json.dumps({"profiles": [{"name": "PROD", "valid": True, "default": True}]}),
                    ),
                ),
                (lambda args: args[:3] == ["databricks", "fs", "mkdir"], radar.CommandResult(0, "")),
                (lambda args: args[:3] == ["databricks", "fs", "cp"], radar.CommandResult(0, "")),
                (
                    lambda args: args[:3] == ["databricks", "workspace", "mkdirs"],
                    radar.CommandResult(0, ""),
                ),
                (
                    lambda args: args[:3] == ["databricks", "workspace", "import"],
                    radar.CommandResult(0, ""),
                ),
                (
                    lambda args: args[:3] == ["databricks", "jobs", "submit"],
                    radar.CommandResult(0, '{"run_id": 123}'),
                ),
            ]
        )

        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "radar.jsonl"
            input_path.write_text("{}\n", encoding="utf-8")
            result = analytics.run_databricks_analytics(
                input_path,
                cluster_id="cluster-123",
                profile="PROD",
                runner=fake,
            )

        self.assertEqual(result.profile_name, "PROD")
        self.assertEqual(result.dbfs_input_path, analytics.DEFAULT_DBFS_DIR + "/radar.jsonl")
        self.assertEqual(result.dbfs_output_path, analytics.DEFAULT_DBFS_DIR + "/radar-analytics-output")
        self.assertEqual(fake.submitted_payload["tasks"][0]["existing_cluster_id"], "cluster-123")
        self.assertEqual(
            fake.submitted_payload["tasks"][0]["notebook_task"]["base_parameters"]["input_path"],
            result.dbfs_input_path,
        )
        self.assertTrue(all("--profile" in call[0] for call in fake.calls))


if __name__ == "__main__":
    unittest.main()
