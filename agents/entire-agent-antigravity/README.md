# Entire External Agent: Google Antigravity (Codebase Flight Recorder)

This directory contains the **Google Antigravity** external agent adapter for the [Entire CLI](https://github.com/entireio/cli), built for **Bengaluru Tech Week Buildathon 2026 — Track 3: Bring Entire to a New Agent or Workflow**.

## Features

- **Native Protocol Integration**: Complies with Entire CLI external-agent protocol specification.
- **"Before You Code" Risk Radar**: Synthesizes Entire Checkpoints + Entire Graph + Databricks historical failure data to warn the agent before high-impact changes.
- **Automated Lifecycle Hooks**: Installs into `.agents/hooks.json` with zero manual setup.
- **Entire Checkpoints & Graph**: Automates session checkpoints and code blast-radius queries.
- **Databricks Telemetry Lake**: Logs development sessions, retry patterns, and test verdicts.

## Build & Installation

```bash
# 1. Build the binary
cd agents/entire-agent-antigravity
go build -o ../../bin/entire-agent-antigravity ./cmd/entire-agent-antigravity

# 2. Copy to PATH
cp ../../bin/entire-agent-antigravity /opt/homebrew/bin/

# 3. Enable in any repository
entire enable --agent antigravity --telemetry=false
```

## Testing

```bash
go test -v ./...
```
