package antigravity

import (
	"encoding/json"
	"os"
	"path/filepath"
	"time"

	"github.com/entireio/external-agents/agents/entire-agent-antigravity/internal/protocol"
)

type HookConfigFile struct {
	LintChecker   *HookGroup `json:"lint-checker,omitempty"`
	FlightRecorderPre *HookGroup `json:"flight-recorder-briefing,omitempty"`
	FlightRecorderTool *HookGroup `json:"flight-recorder-audit,omitempty"`
	FlightRecorderStop *HookGroup `json:"flight-recorder-stop,omitempty"`
}

type HookGroup struct {
	Enabled        *bool             `json:"enabled,omitempty"`
	PreInvocation  []HookHandler     `json:"PreInvocation,omitempty"`
	PostInvocation []HookHandler     `json:"PostInvocation,omitempty"`
	PreToolUse     []GroupedHandler  `json:"PreToolUse,omitempty"`
	PostToolUse    []GroupedHandler  `json:"PostToolUse,omitempty"`
	Stop           []HookHandler     `json:"Stop,omitempty"`
}

type GroupedHandler struct {
	Matcher string        `json:"matcher"`
	Hooks   []HookHandler `json:"hooks"`
}

type HookHandler struct {
	Type    string `json:"type,omitempty"`
	Command string `json:"command"`
	Timeout int    `json:"timeout,omitempty"`
}

func (a *Agent) hooksFilePath() string {
	return filepath.Join(protocol.RepoRoot(), ".agents", "hooks.json")
}

func (a *Agent) AreHooksInstalled() bool {
	p := a.hooksFilePath()
	data, err := os.ReadFile(p)
	if err != nil {
		return false
	}
	var raw map[string]interface{}
	if err := json.Unmarshal(data, &raw); err != nil {
		return false
	}
	_, hasPre := raw["flight-recorder-briefing"]
	_, hasStop := raw["flight-recorder-stop"]
	return hasPre && hasStop
}

func (a *Agent) InstallHooks(localDev bool, force bool) (int, error) {
	p := a.hooksFilePath()
	dir := filepath.Dir(p)
	_ = os.MkdirAll(dir, 0755)

	trueVal := true
	config := map[string]interface{}{
		"flight-recorder-briefing": map[string]interface{}{
			"enabled": trueVal,
			"PreInvocation": []map[string]interface{}{
				{
					"type":    "command",
					"command": "entire-agent-antigravity hook-handler pre-invocation",
					"timeout": 15,
				},
			},
		},
		"flight-recorder-audit": map[string]interface{}{
			"enabled": trueVal,
			"PostToolUse": []map[string]interface{}{
				{
					"matcher": "*",
					"hooks": []map[string]interface{}{
						{
							"type":    "command",
							"command": "entire-agent-antigravity hook-handler post-tool",
							"timeout": 10,
						},
					},
				},
			},
		},
		"flight-recorder-stop": map[string]interface{}{
			"enabled": trueVal,
			"Stop": []map[string]interface{}{
				{
					"type":    "command",
					"command": "entire-agent-antigravity hook-handler stop",
					"timeout": 30,
				},
			},
		},
	}

	data, err := json.MarshalIndent(config, "", "  ")
	if err != nil {
		return 0, err
	}
	if err := os.WriteFile(p, data, 0644); err != nil {
		return 0, err
	}
	return 3, nil
}

func (a *Agent) UninstallHooks() error {
	p := a.hooksFilePath()
	_ = os.Remove(p)
	return nil
}

func (a *Agent) ParseHook(hookName string, input []byte) (*protocol.EventJSON, error) {
	var hookInput protocol.AntigravityHookInput
	_ = json.Unmarshal(input, &hookInput)

	sessionID := hookInput.ConversationID
	if sessionID == "" {
		sessionID = stubSession
	}

	event := &protocol.EventJSON{
		Type:      1,
		SessionID: sessionID,
		Timestamp: time.Now().UTC().Format(time.RFC3339),
		Metadata: map[string]string{
			"model":     hookInput.ModelName,
			"hook_name": hookName,
		},
	}

	if hookInput.ToolCall != nil {
		event.ToolUseID = hookInput.ToolCall.Name
		rawArgs, _ := json.Marshal(hookInput.ToolCall.Args)
		event.ToolInput = rawArgs
	}

	return event, nil
}
