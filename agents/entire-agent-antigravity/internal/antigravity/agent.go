package antigravity

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/entireio/external-agents/agents/entire-agent-antigravity/internal/flightrecorder"
	"github.com/entireio/external-agents/agents/entire-agent-antigravity/internal/protocol"
)

const (
	AgentName   = "antigravity"
	AgentType   = "Google Antigravity"
	stubSession = "session-antigravity-live"
)

type Agent struct {
	BriefingEngine *flightrecorder.BriefingEngine
}

func New() *Agent {
	root := protocol.RepoRoot()
	return &Agent{
		BriefingEngine: flightrecorder.NewBriefingEngine(root),
	}
}

func (a *Agent) Info() protocol.InfoResponse {
	return protocol.InfoResponse{
		ProtocolVersion: protocol.ProtocolVersion,
		Name:            AgentName,
		Type:            AgentType,
		Description:     "Codebase Flight Recorder integration for Google Antigravity (Track 3)",
		IsPreview:       false,
		ProtectedDirs:   []string{".agents", ".gemini", ".entire/flight_recorder"},
		HookNames: []string{
			"PreInvocation",
			"PreToolUse",
			"PostToolUse",
			"PostInvocation",
			"Stop",
		},
		Capabilities: protocol.DeclaredCapabilities{
			Hooks:                  true,
			TranscriptAnalyzer:     true,
			TranscriptPreparer:     true,
			CompactTranscript:      true,
			TokenCalculator:        true,
			TextGenerator:          true,
			HookResponseWriter:     true,
			SubagentAwareExtractor: true,
			UsesTerminal:           false,
		},
	}
}

func (a *Agent) Detect() protocol.DetectResponse {
	// Antigravity is present if Antigravity config or workspace hooks exist or running in Antigravity environment
	home, _ := os.UserHomeDir()
	antigravityDir := filepath.Join(home, ".gemini", "antigravity")
	_, err := os.Stat(antigravityDir)
	return protocol.DetectResponse{Present: err == nil || os.Getenv("ANTIGRAVITY_ENV") != ""}
}

func (a *Agent) GetSessionID(input *protocol.HookInputJSON) string {
	if input != nil && strings.TrimSpace(input.SessionID) != "" {
		return input.SessionID
	}
	return stubSession
}

func (a *Agent) GetSessionDir(repoPath string) (string, error) {
	if strings.TrimSpace(repoPath) == "" {
		repoPath = protocol.RepoRoot()
	}
	if resolved, err := filepath.EvalSymlinks(repoPath); err == nil {
		repoPath = resolved
	}
	sum := sha256.Sum256([]byte(repoPath))
	key := hex.EncodeToString(sum[:])[:16]
	dir := filepath.Join(os.TempDir(), "entire-antigravity", key)
	_ = os.MkdirAll(dir, 0755)
	return dir, nil
}

func (a *Agent) ResolveSessionFile(sessionDir, sessionID string) string {
	if strings.TrimSpace(sessionDir) == "" {
		sessionDir, _ = a.GetSessionDir(protocol.RepoRoot())
	}
	if strings.TrimSpace(sessionID) == "" {
		sessionID = stubSession
	}
	return filepath.Join(sessionDir, safeFilename(sessionID)+".jsonl")
}

func (a *Agent) FormatResumeCommand(sessionID string) string {
	return fmt.Sprintf("agy resume --session-id %s", sessionID)
}

func safeFilename(s string) string {
	s = strings.ReplaceAll(s, "/", "_")
	s = strings.ReplaceAll(s, "\\", "_")
	return s
}
