# CODEBASE FLIGHT RECORDER
### Bengaluru Tech Week Buildathon 2026 — Track 3: Bring Entire to a New Agent or Workflow
**Tagline:** *Give AI coding agents a memory, a risk radar, and a reason to trust their next change.*

---

## 1. Executive Summary & Problem

AI coding agents can generate code and refactor modules in seconds, but **critical development context is lost across sessions**:
- An agent attempts an architectural change or migration, hits subtle runtime failures (e.g., webhook signature mismatches, async timeout regressions), and reverts.
- In a later session, a new agent or developer touches that same code without knowing **why** previous decisions were made, **what failed**, or **what downstream modules break**.

**The Core Question:** *Before an AI agent modifies critical code, what should it know about the codebase’s past?*

---

## 2. Our Solution: Codebase Flight Recorder

**Codebase Flight Recorder** integrates **Google Antigravity** with **Entire** to give the agent historical memory and real-time risk intelligence.

Before touching high-risk code, the agent automatically receives a **"BEFORE YOU CODE"** briefing synthesized from three complementary sources:

1. **Entire Checkpoints:** Why previous decisions were made, what approaches were tried, what failed, and what remains unresolved.
2. **Entire Graph:** Code relationships, callers, dependencies, and blast-radius impact analysis.
3. **Databricks Historical Analytics:** Cross-session development telemetry identifying failure hotspots, retry spikes, and risky components.

---

## 3. Architecture & Data Flow

```
                          Google Antigravity Agent
                                     │
          ┌──────────────────────────┴──────────────────────────┐
          ▼                                                     ▼
Antigravity Hooks (.agents/hooks.json)                 Agent Code Changes / Tests
• PreInvocation (Inject Briefing)                     • replace_file_content
• PreToolUse / PostToolUse (Audit & Log)              • write_to_file / pytest
• Stop (Session Complete & Checkpoint)                • verification suite
          │                                                     │
          └──────────────────────────┬──────────────────────────┘
                                     ▼
                  Codebase Flight Recorder Adapter
                 (entire-agent-antigravity executable)
                                     │
     ┌───────────────────────────────┼───────────────────────────────┐
     ▼                               ▼                               ▼
Entire External-Agent           Entire Graph                    Databricks
      Protocol              (Dependency & Impact)          (Historical Analytics)
  • info / detect            • entire graph query           • Delta Lake / JSON Telemetry
  • read-session             • Blast-radius lookup          • Failure Hotspot Queries
  • write-session            • Impacted files               • Webhook / Migration Radar
  • parse-hook                                              • Risk Scoring (HIGH/MED/LOW)
  • compact-transcript
     │
     ▼
Entire Checkpoints
(Decisions, Failed attempts, Context ledger)
```

---

## 4. Why Entire is Essential

Without Entire, this product cannot exist:
- **Checkpoints as Reusable Memory:** Traditional git commits only record final code diffs. Entire Checkpoints capture the *developer/agent intent, reasoning, and failed attempts* into structured, queryable metadata.
- **Deterministic No-Egress Code Graph:** Entire Graph provides fast, zero-egress semantic blast radius calculation directly on the committed repository tree.
- **External Agent Protocol:** Allows Antigravity to participate as a first-class citizen in the Entire ecosystem without needing proprietary closed-source SDK modifications.

---

## 5. The Killer Feature: "BEFORE YOU CODE" Briefing

When Antigravity receives a coding task touching critical paths (e.g. payment/checkout), the `PreInvocation` hook executes and injects this live warning into the agent context:

```text
═══════════════════════════════════════════════════════════════
  ⚡ [CODEBASE FLIGHT RECORDER] — BEFORE YOU CODE BRIEFING
═══════════════════════════════════════════════════════════════

Risk: 🔴 HIGH

Affected components (Entire Graph):
• checkout_service.py (process_checkout)
• orders_controller.py (place_order)
• refund_worker.py (handle_refund)
• webhook_router.py (verify_payment_webhook)

Previous failed approach (Entire Checkpoints):
• Payment library migration (v2 to v3)
• Webhook signature verification

Known unresolved issues:
• Webhook signature compatibility mismatch
• Refund timeout under load

Recommended tests:
• test_payment_integration
• test_checkout_flow
• test_webhook_signatures
• test_refund_pipeline

Reason for warning (Databricks Analytics):
• High historical failure rate (67%) and deep dependency impact across checkout/refund services.
───────────────────────────────────────────────────────────────
```

---

## 6. Track 3 Implementation Details

### External Agent Binary (`entire-agent-antigravity`)
- Written in Go and compiled directly to `/opt/homebrew/bin/entire-agent-antigravity`.
- Complies with Entire External Agent Protocol v1:
  - Subcommands implemented: `info`, `detect`, `get-session-id`, `get-session-dir`, `resolve-session-file`, `read-session`, `write-session`, `read-transcript`, `chunk-transcript`, `reassemble-transcript`, `compact-transcript`, `format-resume-command`, `parse-hook`, `install-hooks`, `uninstall-hooks`, `are-hooks-installed`, `get-transcript-position`, `extract-modified-files`, `extract-prompts`, `extract-summary`, `briefing`.

### Antigravity Hook Integration (`.agents/hooks.json`)
```json
{
  "flight-recorder-briefing": {
    "PreInvocation": [
      {
        "command": "entire-agent-antigravity hook-handler pre-invocation",
        "timeout": 15,
        "type": "command"
      }
    ],
    "enabled": true
  },
  "flight-recorder-audit": {
    "PostToolUse": [
      {
        "matcher": "*",
        "hooks": [
          {
            "command": "entire-agent-antigravity hook-handler post-tool",
            "timeout": 10,
            "type": "command"
          }
        ]
      }
    ],
    "enabled": true
  },
  "flight-recorder-stop": {
    "Stop": [
      {
        "command": "entire-agent-antigravity hook-handler stop",
        "timeout": 30,
        "type": "command"
      }
    ],
    "enabled": true
  }
}
```

---

## 7. Databricks Integration & Schema

### Structured Telemetry Schema
Each agent development session is captured as a structured record:
- `session_id`: Unique conversation identifier.
- `timestamp`: Session completion time.
- `files_touched`: Array of modified files.
- `components_involved`: Architectural components impacted.
- `change_type`: Refactor, migration, feature, bugfix.
- `test_result`: `passed` | `failed` | `skipped`.
- `failures`: Specific test error names and stack traces.
- `retries`: Number of retry attempts in session.
- `risk_score`: 0.0 - 1.0 composite risk rating.
- `outcome`: `completed` | `reverted` | `work-in-progress`.

### Analytics & Intelligence
- **Hotspot Detection:** Identifies files with >50% failure rate over past 10 sessions.
- **Blast-Radius Corroboration:** Cross-references Graph callers with historical regressions.
- **Resilient Hybrid Lake:** Telemetry streams to Databricks REST API while caching locally in `.entire/flight_recorder/databricks_telemetry.json`.

---

## 8. Noon Curveball Strategy

1. **Pre-Noon Checkpoint:** Commit stable integration, verify `entire status` and unit test suite.
2. **Fresh Session Recovery:** Close the Antigravity session. Start a fresh session.
3. **Reconstruction:** `entire-agent-antigravity` reads previous Entire Checkpoint and Graph state, reconstructing full architecture context in <5 seconds.
4. **Impact Analysis:** Run `entire graph impact <curveball_symbol>` to identify affected modules.
5. **Implement & Test:** Apply minimal Curveball adaptation and run tests.
6. **Curveball Checkpoint:** Record the Curveball response checkpoint.

---

## 9. Verification & Test Evidence

```bash
# Unit Tests
cd agents/entire-agent-antigravity
go test -v ./...

=== RUN   TestAgentInfo
--- PASS: TestAgentInfo (0.00s)
=== RUN   TestAgentGetSessionID
--- PASS: TestAgentGetSessionID (0.00s)
=== RUN   TestHooksLifecycle
--- PASS: TestHooksLifecycle (0.00s)
PASS
ok      github.com/entireio/external-agents/agents/entire-agent-antigravity/internal/antigravity (0.49s)
=== RUN   TestBriefingGenerationHighRisk
--- PASS: TestBriefingGenerationHighRisk (0.07s)
=== RUN   TestDatabricksTelemetryLake
--- PASS: TestDatabricksTelemetryLake (0.00s)
PASS
ok      github.com/entireio/external-agents/agents/entire-agent-antigravity/internal/flightrecorder (1.03s)
```

---

## 10. Data Provenance & Safety
- No secrets, API keys, or private customer data are written to Git or transcripts.
- Entire Graph operates in local, zero-egress mode.
- Databricks telemetry uses anonymized file paths and test verdicts.
