package antigravity

import (
	"bufio"
	"bytes"
	"encoding/base64"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/entireio/external-agents/agents/entire-agent-antigravity/internal/protocol"
)

type AntigravityLogEntry struct {
	StepIndex int                    `json:"step_index"`
	Source    string                 `json:"source"`
	Type      string                 `json:"type"`
	Status    string                 `json:"status"`
	CreatedAt string                 `json:"created_at"`
	Content   string                 `json:"content"`
	ToolCalls []protocol.AntigravityToolCall `json:"tool_calls,omitempty"`
}

func (a *Agent) ReadSession(input *protocol.HookInputJSON) (protocol.AgentSessionJSON, error) {
	sessionID := a.GetSessionID(input)
	sessionDir, _ := a.GetSessionDir(protocol.RepoRoot())
	sessionFile := a.ResolveSessionFile(sessionDir, sessionID)

	var nativeData []byte
	if data, err := os.ReadFile(sessionFile); err == nil {
		nativeData = data
	}

	files, _, _ := a.ExtractModifiedFiles(sessionFile, 0)

	return protocol.AgentSessionJSON{
		SessionID:     sessionID,
		AgentName:     AgentName,
		RepoPath:      protocol.RepoRoot(),
		SessionRef:    sessionFile,
		StartTime:     time.Now().UTC().Format(time.RFC3339),
		NativeData:    nativeData,
		ModifiedFiles: files,
	}, nil
}

func (a *Agent) WriteSession(session protocol.AgentSessionJSON) error {
	sessionDir, _ := a.GetSessionDir(session.RepoPath)
	sessionFile := a.ResolveSessionFile(sessionDir, session.SessionID)
	_ = os.MkdirAll(filepath.Dir(sessionFile), 0755)
	return os.WriteFile(sessionFile, session.NativeData, 0644)
}

func (a *Agent) ReadTranscript(sessionRef string) ([]byte, error) {
	data, err := os.ReadFile(sessionRef)
	if err != nil {
		return []byte("{}"), nil
	}
	return data, nil
}

func (a *Agent) ChunkTranscript(content []byte, maxSize int) ([][]byte, error) {
	if maxSize <= 0 {
		maxSize = 64 * 1024
	}
	var chunks [][]byte
	for len(content) > 0 {
		if len(content) <= maxSize {
			chunks = append(chunks, content)
			break
		}
		chunks = append(chunks, content[:maxSize])
		content = content[maxSize:]
	}
	return chunks, nil
}

func (a *Agent) ReassembleTranscript(chunks [][]byte) ([]byte, error) {
	var buf bytes.Buffer
	for _, c := range chunks {
		buf.Write(c)
	}
	return buf.Bytes(), nil
}

func (a *Agent) CompactTranscript(sessionRef string) (protocol.CompactTranscriptResponse, error) {
	raw, err := a.ReadTranscript(sessionRef)
	if err != nil {
		return protocol.CompactTranscriptResponse{Transcript: ""}, nil
	}
	encoded := base64.StdEncoding.EncodeToString(raw)
	return protocol.CompactTranscriptResponse{
		Transcript: encoded,
	}, nil
}

func (a *Agent) GetTranscriptPosition(path string) (int, error) {
	info, err := os.Stat(path)
	if err != nil {
		return 0, nil
	}
	return int(info.Size()), nil
}

func (a *Agent) ExtractModifiedFiles(path string, offset int) ([]string, int, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, offset, nil
	}
	defer file.Close()

	if offset > 0 {
		_, _ = file.Seek(int64(offset), 0)
	}

	var modified []string
	seen := make(map[string]bool)
	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		line := scanner.Bytes()
		var entry AntigravityLogEntry
		if err := json.Unmarshal(line, &entry); err == nil {
			for _, tc := range entry.ToolCalls {
				if tc.Name == "write_to_file" || tc.Name == "replace_file_content" {
					if target, ok := tc.Args["TargetFile"].(string); ok && target != "" {
						if !seen[target] {
							seen[target] = true
							modified = append(modified, target)
						}
					}
				}
			}
		}
	}

	info, _ := file.Stat()
	newPos := offset
	if info != nil {
		newPos = int(info.Size())
	}
	return modified, newPos, nil
}

func (a *Agent) ExtractPrompts(sessionRef string, offset int) ([]string, error) {
	file, err := os.Open(sessionRef)
	if err != nil {
		return nil, nil
	}
	defer file.Close()

	var prompts []string
	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		line := scanner.Bytes()
		var entry AntigravityLogEntry
		if err := json.Unmarshal(line, &entry); err == nil {
			if entry.Type == "USER_INPUT" && strings.TrimSpace(entry.Content) != "" {
				prompts = append(prompts, entry.Content)
			}
		}
	}
	return prompts, nil
}

func (a *Agent) ExtractSummary(sessionRef string) (string, bool, error) {
	file, err := os.Open(sessionRef)
	if err != nil {
		return "Antigravity task in progress", true, nil
	}
	defer file.Close()

	var lastContent string
	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		var entry AntigravityLogEntry
		if err := json.Unmarshal(scanner.Bytes(), &entry); err == nil {
			if entry.Content != "" {
				lastContent = entry.Content
			}
		}
	}

	if lastContent != "" {
		if len(lastContent) > 300 {
			lastContent = lastContent[:300] + "..."
		}
		return lastContent, true, nil
	}
	return "Antigravity session executed successfully", true, nil
}
