package antigravity

import (
	"testing"

	"github.com/entireio/external-agents/agents/entire-agent-antigravity/internal/protocol"
)

func TestAgentInfo(t *testing.T) {
	agent := New()
	info := agent.Info()
	if info.Name != "antigravity" {
		t.Fatalf("expected name antigravity, got %s", info.Name)
	}
	if info.Type != "Google Antigravity" {
		t.Fatalf("expected type Google Antigravity, got %s", info.Type)
	}
	if !info.Capabilities.Hooks {
		t.Fatalf("expected Hooks capability to be true")
	}
	if !info.Capabilities.TranscriptAnalyzer {
		t.Fatalf("expected TranscriptAnalyzer capability to be true")
	}
}

func TestAgentGetSessionID(t *testing.T) {
	agent := New()
	id := agent.GetSessionID(&protocol.HookInputJSON{SessionID: "custom-session-123"})
	if id != "custom-session-123" {
		t.Fatalf("expected custom-session-123, got %s", id)
	}

	stub := agent.GetSessionID(nil)
	if stub != stubSession {
		t.Fatalf("expected default stub session, got %s", stub)
	}
}

func TestHooksLifecycle(t *testing.T) {
	agent := New()
	count, err := agent.InstallHooks(true, true)
	if err != nil {
		t.Fatalf("failed to install hooks: %v", err)
	}
	if count != 3 {
		t.Fatalf("expected 3 hooks installed, got %d", count)
	}
	if !agent.AreHooksInstalled() {
		t.Fatalf("expected hooks to be installed")
	}
}
