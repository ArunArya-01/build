package protocol

import (
	"encoding/json"
	"flag"
	"io"
	"os"
		"time"
)

type SessionDirResolver interface {
	GetSessionDir(repoPath string) (string, error)
}

type SessionFileResolver interface {
	ResolveSessionFile(sessionDir, sessionID string) string
}

type SessionIDProvider interface {
	GetSessionID(*HookInputJSON) string
}

type SessionReader interface {
	ReadSession(*HookInputJSON) (AgentSessionJSON, error)
}

type SessionWriter interface {
	WriteSession(AgentSessionJSON) error
}

type TranscriptReader interface {
	ReadTranscript(sessionRef string) ([]byte, error)
}

type TranscriptChunker interface {
	ChunkTranscript(content []byte, maxSize int) ([][]byte, error)
	ReassembleTranscript(chunks [][]byte) ([]byte, error)
}

type TranscriptCompactor interface {
	CompactTranscript(sessionRef string) (CompactTranscriptResponse, error)
}

type ResumeFormatter interface {
	FormatResumeCommand(sessionID string) string
}

type HookParser interface {
	ParseHook(hookName string, input []byte) (*EventJSON, error)
	InstallHooks(localDev bool, force bool) (int, error)
	UninstallHooks() error
	AreHooksInstalled() bool
}

type TranscriptAnalyzer interface {
	GetTranscriptPosition(path string) (int, error)
	ExtractModifiedFiles(path string, offset int) ([]string, int, error)
	ExtractPrompts(sessionRef string, offset int) ([]string, error)
	ExtractSummary(sessionRef string) (string, bool, error)
}

func WriteJSON(w io.Writer, v any) error {
	enc := json.NewEncoder(w)
	enc.SetEscapeHTML(false)
	return enc.Encode(v)
}

func ReadJSON[T any](r io.Reader) (*T, error) {
	var value T
	if err := json.NewDecoder(r).Decode(&value); err != nil {
		return nil, err
	}
	return &value, nil
}

func RepoRoot() string {
	if root := os.Getenv("ENTIRE_REPO_ROOT"); root != "" {
		return root
	}
	root, _ := os.Getwd()
	return root
}

func HandleGetSessionID(stdin io.Reader, stdout io.Writer, provider SessionIDProvider) error {
	input, err := ReadJSON[HookInputJSON](stdin)
	if err != nil {
		return err
	}
	return WriteJSON(stdout, SessionIDResponse{SessionID: provider.GetSessionID(input)})
}

func HandleGetSessionDir(args []string, stdout io.Writer, resolver SessionDirResolver) error {
	fs := flag.NewFlagSet("get-session-dir", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	repoPath := fs.String("repo-path", "", "repo path")
	if err := fs.Parse(args); err != nil {
		return err
	}
	sessionDir, err := resolver.GetSessionDir(*repoPath)
	if err != nil {
		return err
	}
	return WriteJSON(stdout, SessionDirResponse{SessionDir: sessionDir})
}

func HandleResolveSessionFile(args []string, stdout io.Writer, resolver SessionFileResolver) error {
	fs := flag.NewFlagSet("resolve-session-file", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	sessionDir := fs.String("session-dir", "", "session dir")
	sessionID := fs.String("session-id", "", "session id")
	if err := fs.Parse(args); err != nil {
		return err
	}
	return WriteJSON(stdout, SessionFileResponse{SessionFile: resolver.ResolveSessionFile(*sessionDir, *sessionID)})
}

func HandleReadSession(stdin io.Reader, stdout io.Writer, reader SessionReader) error {
	input, err := ReadJSON[HookInputJSON](stdin)
	if err != nil {
		return err
	}
	session, err := reader.ReadSession(input)
	if err != nil {
		return err
	}
	return WriteJSON(stdout, session)
}

func HandleWriteSession(stdin io.Reader, writer SessionWriter) error {
	session, err := ReadJSON[AgentSessionJSON](stdin)
	if err != nil {
		return err
	}
	return writer.WriteSession(*session)
}

func HandleReadTranscript(args []string, stdout io.Writer, reader TranscriptReader) error {
	fs := flag.NewFlagSet("read-transcript", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	sessionRef := fs.String("session-ref", "", "session ref")
	if err := fs.Parse(args); err != nil {
		return err
	}
	data, err := reader.ReadTranscript(*sessionRef)
	if err != nil {
		return err
	}
	_, err = stdout.Write(data)
	return err
}

func HandleChunkTranscript(args []string, stdin io.Reader, stdout io.Writer, chunker TranscriptChunker) error {
	fs := flag.NewFlagSet("chunk-transcript", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	maxSize := fs.Int("max-size", 64*1024, "max chunk size")
	if err := fs.Parse(args); err != nil {
		return err
	}
	content, err := io.ReadAll(stdin)
	if err != nil {
		return err
	}
	chunks, err := chunker.ChunkTranscript(content, *maxSize)
	if err != nil {
		return err
	}
	return WriteJSON(stdout, ChunkResponse{Chunks: chunks})
}

func HandleReassembleTranscript(stdin io.Reader, stdout io.Writer, chunker TranscriptChunker) error {
	input, err := ReadJSON[ChunkResponse](stdin)
	if err != nil {
		return err
	}
	data, err := chunker.ReassembleTranscript(input.Chunks)
	if err != nil {
		return err
	}
	_, err = stdout.Write(data)
	return err
}

func HandleCompactTranscript(args []string, stdout io.Writer, compactor TranscriptCompactor) error {
	fs := flag.NewFlagSet("compact-transcript", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	sessionRef := fs.String("session-ref", "", "session ref")
	if err := fs.Parse(args); err != nil {
		return err
	}
	resp, err := compactor.CompactTranscript(*sessionRef)
	if err != nil {
		return err
	}
	return WriteJSON(stdout, resp)
}

func HandleFormatResumeCommand(args []string, stdout io.Writer, formatter ResumeFormatter) error {
	fs := flag.NewFlagSet("format-resume-command", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	sessionID := fs.String("session-id", "", "session id")
	if err := fs.Parse(args); err != nil {
		return err
	}
	return WriteJSON(stdout, ResumeCommandResponse{Command: formatter.FormatResumeCommand(*sessionID)})
}

func HandleParseHook(args []string, stdin io.Reader, stdout io.Writer, parser HookParser) error {
	fs := flag.NewFlagSet("parse-hook", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	hookName := fs.String("hook-name", "", "hook name")
	if err := fs.Parse(args); err != nil {
		return err
	}
	input, err := io.ReadAll(stdin)
	if err != nil {
		return err
	}
	event, err := parser.ParseHook(*hookName, input)
	if err != nil {
		return err
	}
	if event == nil {
		event = &EventJSON{
			Type:      1,
			Timestamp: time.Now().UTC().Format(time.RFC3339),
		}
	}
	return WriteJSON(stdout, event)
}

func HandleInstallHooks(args []string, stdout io.Writer, parser HookParser) error {
	fs := flag.NewFlagSet("install-hooks", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	localDev := fs.Bool("local-dev", false, "local dev mode")
	force := fs.Bool("force", false, "force overwrite")
	if err := fs.Parse(args); err != nil {
		return err
	}
	count, err := parser.InstallHooks(*localDev, *force)
	if err != nil {
		return err
	}
	return WriteJSON(stdout, HooksInstalledCountResponse{HooksInstalled: count})
}

func HandleGetTranscriptPosition(args []string, stdout io.Writer, analyzer TranscriptAnalyzer) error {
	fs := flag.NewFlagSet("get-transcript-position", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	path := fs.String("path", "", "transcript path")
	if err := fs.Parse(args); err != nil {
		return err
	}
	pos, err := analyzer.GetTranscriptPosition(*path)
	if err != nil {
		return err
	}
	return WriteJSON(stdout, TranscriptPositionResponse{Position: pos})
}

func HandleExtractModifiedFiles(args []string, stdout io.Writer, analyzer TranscriptAnalyzer) error {
	fs := flag.NewFlagSet("extract-modified-files", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	path := fs.String("path", "", "transcript path")
	offset := fs.Int("offset", 0, "offset")
	if err := fs.Parse(args); err != nil {
		return err
	}
	files, nextOffset, err := analyzer.ExtractModifiedFiles(*path, *offset)
	if err != nil {
		return err
	}
	return WriteJSON(stdout, ExtractFilesResponse{Files: files, CurrentPosition: nextOffset})
}

func HandleExtractPrompts(args []string, stdout io.Writer, analyzer TranscriptAnalyzer) error {
	fs := flag.NewFlagSet("extract-prompts", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	sessionRef := fs.String("session-ref", "", "session ref")
	offset := fs.Int("offset", 0, "offset")
	if err := fs.Parse(args); err != nil {
		return err
	}
	prompts, err := analyzer.ExtractPrompts(*sessionRef, *offset)
	if err != nil {
		return err
	}
	return WriteJSON(stdout, ExtractPromptsResponse{Prompts: prompts})
}

func HandleExtractSummary(args []string, stdout io.Writer, analyzer TranscriptAnalyzer) error {
	fs := flag.NewFlagSet("extract-summary", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	sessionRef := fs.String("session-ref", "", "session ref")
	if err := fs.Parse(args); err != nil {
		return err
	}
	summary, has, err := analyzer.ExtractSummary(*sessionRef)
	if err != nil {
		return err
	}
	return WriteJSON(stdout, ExtractSummaryResponse{Summary: summary, HasSummary: has})
}
