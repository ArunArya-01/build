# Google Antigravity (Codebase Flight Recorder) — External Agent Specification

## Verdict: Compatible & Verified

Google Antigravity exposes lifecycle hooks via `.agents/hooks.json` and conversation logs under the Antigravity runtime directory. The `entire-agent-antigravity` integration implements **Codebase Flight Recorder** (Track 3: Bring Entire to a New Agent or Workflow), connecting Antigravity lifecycle events with Entire Checkpoints, Entire Graph code analysis, and Databricks historical telemetry.

## Static Checks

| Check | Result | Notes |
| :--- | :--- | :--- |
| **Binary Present** | PASS | `entire-agent-antigravity` on `/Users/arunarya/.gemini/antigravity/bin:/Users/arunarya/Library/Application Support/Antigravity/bin:/Library/Frameworks/Python.framework/Versions/3.13/bin:/usr/local/bin:/System/Cryptexes/App/usr/bin:/usr/bin:/bin:/usr/sbin:/sbin:/var/run/com.apple.security.cryptexd/codex.system/bootstrap/usr/local/bin:/var/run/com.apple.security.cryptexd/codex.system/bootstrap/usr/bin:/var/run/com.apple.security.cryptexd/codex.system/bootstrap/usr/appleinternal/bin:/pkg/env/global/bin:/Library/Apple/usr/bin:/usr/local/go/bin:/opt/homebrew/bin` (`/opt/homebrew/bin/entire-agent-antigravity`) |
| **Protocol Compliance** | PASS | Implements all 20 protocol subcommands |
| **Lifecycle Hooks** | PASS | `PreInvocation`, `PreToolUse`, `PostToolUse`, `Stop` in `.agents/hooks.json` |
| **Entire Graph Bridge** | PASS | `entire graph impact / search / def / diff` integrated |
| **Databricks Telemetry** | PASS | Structured session lake + REST API sync |
| **Risk Briefing Card** | PASS | "BEFORE YOU CODE" card injected via `PreInvocation` ephemeral step |

## Protocol Mapping

| Protocol Subcommand | Antigravity Concept | Implementation |
| :--- | :--- | :--- |
| `info` | Agent metadata | Name `antigravity`, type `Google Antigravity` |
| `detect` | Environment detection | Checks `~/.gemini/antigravity` or Antigravity runtime |
| `get-session-id` | Conversation ID | Returns active `conversationId` |
| `get-session-dir` | Entire sidecar dir | Repo-scoped OS temp directory |
| `resolve-session-file` | Session file path | `<session_id>.jsonl` |
| `read-session` | Sidecar JSONL | Returns native data and modified files |
| `write-session` | Sidecar JSONL | Writes native session payload |
| `read-transcript` | Antigravity transcript | Reads `transcript.jsonl` |
| `compact-transcript` | Base64 compact format | Emits compact Entire Transcript Format |
| `format-resume-command` | Resume command | `agy resume --session-id <session_id>` |
| `parse-hook` | Antigravity hook parser | Maps lifecycle hooks to Entire events |
| `install-hooks` | `.agents/hooks.json` | Installs briefing, audit, and stop handlers |
| `are-hooks-installed` | Verification | Validates `.agents/hooks.json` entries |
| `uninstall-hooks` | Removal | Removes Entire hooks from `.agents/hooks.json` |
| `extract-modified-files` | Tool call parser | Extracts files modified by `write_to_file` / `replace_file_content` |
| `extract-prompts` | User prompt extractor | Reads `USER_INPUT` steps |
| `extract-summary` | Session summary | Extracts task summary and conclusion |

## Lifecycle Hook Architecture

```
Google Antigravity
       │
       ▼ (PreInvocation)
entire-agent-antigravity hook-handler pre-invocation
       │
       ├─► Queries Entire Graph (blast radius & callers)
       ├─► Queries Entire Checkpoints (previous decisions & failed attempts)
       ├─► Queries Databricks (historical fail rate & retry hotspots)
       │
       ▼
Injects "BEFORE YOU CODE" Briefing into Antigravity Context
       │
       ▼ (PostToolUse)
entire-agent-antigravity hook-handler post-tool (Logs tool usage & test results)
       │
       ▼ (Stop)
entire-agent-antigravity hook-handler stop (Creates Entire Checkpoint & Databricks telemetry)
```
