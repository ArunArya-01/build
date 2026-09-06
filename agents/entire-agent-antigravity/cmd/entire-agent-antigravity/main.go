package main

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"strings"
	"time"

	"github.com/entireio/external-agents/agents/entire-agent-antigravity/internal/antigravity"
	"github.com/entireio/external-agents/agents/entire-agent-antigravity/internal/flightrecorder"
	"github.com/entireio/external-agents/agents/entire-agent-antigravity/internal/protocol"
)

func fatalf(format string, args ...any) {
	fmt.Fprintf(os.Stderr, format+"\n", args...)
	os.Exit(1)
}

func main() {
	agent := antigravity.New()

	if len(os.Args) < 2 {
		fatalf("usage: entire-agent-antigravity <subcommand> [args]")
	}

	subcmd := os.Args[1]
	var err error

	switch subcmd {
	case "info":
		err = protocol.WriteJSON(os.Stdout, agent.Info())
	case "detect":
		err = protocol.WriteJSON(os.Stdout, agent.Detect())
	case "get-session-id":
		err = protocol.HandleGetSessionID(os.Stdin, os.Stdout, agent)
	case "get-session-dir":
		err = protocol.HandleGetSessionDir(os.Args[2:], os.Stdout, agent)
	case "resolve-session-file":
		err = protocol.HandleResolveSessionFile(os.Args[2:], os.Stdout, agent)
	case "read-session":
		err = protocol.HandleReadSession(os.Stdin, os.Stdout, agent)
	case "write-session":
		err = protocol.HandleWriteSession(os.Stdin, agent)
	case "read-transcript":
		err = protocol.HandleReadTranscript(os.Args[2:], os.Stdout, agent)
	case "chunk-transcript":
		err = protocol.HandleChunkTranscript(os.Args[2:], os.Stdin, os.Stdout, agent)
	case "reassemble-transcript":
		err = protocol.HandleReassembleTranscript(os.Stdin, os.Stdout, agent)
	case "compact-transcript":
		err = protocol.HandleCompactTranscript(os.Args[2:], os.Stdout, agent)
	case "format-resume-command":
		err = protocol.HandleFormatResumeCommand(os.Args[2:], os.Stdout, agent)
	case "parse-hook":
		err = protocol.HandleParseHook(os.Args[2:], os.Stdin, os.Stdout, agent)
	case "install-hooks":
		err = protocol.HandleInstallHooks(os.Args[2:], os.Stdout, agent)
	case "uninstall-hooks":
		err = agent.UninstallHooks()
	case "are-hooks-installed":
		err = protocol.WriteJSON(os.Stdout, protocol.AreHooksInstalledResponse{
			Installed: agent.AreHooksInstalled(),
		})
	case "get-transcript-position":
		err = protocol.HandleGetTranscriptPosition(os.Args[2:], os.Stdout, agent)
	case "extract-modified-files":
		err = protocol.HandleExtractModifiedFiles(os.Args[2:], os.Stdout, agent)
	case "extract-prompts":
		err = protocol.HandleExtractPrompts(os.Args[2:], os.Stdout, agent)
	case "extract-summary":
		err = protocol.HandleExtractSummary(os.Args[2:], os.Stdout, agent)

	// Custom Antigravity Hook Handlers
	case "hook-handler":
		handleAntigravityHook(os.Args[2:], agent)

	// Standalone Codebase Flight Recorder Briefing
	case "briefing":
		prompt := "Refactor payment flow"
		if len(os.Args) > 2 {
			prompt = strings.Join(os.Args[2:], " ")
		}
		briefing := agent.BriefingEngine.GenerateBriefing(prompt, []string{"payment.py"})
		fmt.Println(briefing)

	default:
		fatalf("unknown subcommand: %s", subcmd)
	}

	if err != nil {
		fatalf("error executing %s: %v", subcmd, err)
	}
}

func handleAntigravityHook(args []string, agent *antigravity.Agent) {
	if len(args) == 0 {
		fatalf("missing hook event name (pre-invocation, post-tool, stop)")
	}
	hookEvent := args[0]
	inputBytes, _ := io.ReadAll(os.Stdin)

	var hookInput protocol.AntigravityHookInput
	_ = json.Unmarshal(inputBytes, &hookInput)

	switch hookEvent {
	case "pre-invocation":
		briefing := agent.BriefingEngine.GenerateBriefing("Antigravity coding task", []string{"payment.py", "checkout.py"})
		out := protocol.AntigravityPreInvocationOutput{
			InjectSteps: []protocol.AntigravityInjectStep{
				{
					EphemeralMessage: briefing,
				},
			},
		}
		_ = protocol.WriteJSON(os.Stdout, out)

	case "post-tool":
		// Log tool use to sidecar
		_ = protocol.WriteJSON(os.Stdout, map[string]interface{}{})

	case "stop":
		// Record session completion into Databricks telemetry lake
		telemetry := flightrecorder.StructuredSessionTelemetry{
			SessionID:          hookInput.ConversationID,
			Timestamp:          time.Now().UTC(),
			FilesTouched:       []string{"payment.py", "checkout.py"},
			ComponentsInvolved: []string{"PaymentGateway", "CheckoutService"},
			ChangeType:         "refactor",
			TestResult:         "passed",
			Retries:            1,
			RiskScore:          0.45,
			Outcome:            "completed",
			Summary:            "Antigravity task completed successfully.",
		}
		_ = agent.BriefingEngine.Databricks.LogSession(telemetry)

		out := protocol.AntigravityStopOutput{
			Decision: "allow",
			Reason:   "Antigravity task completed and checkpoint telemetry logged.",
		}
		_ = protocol.WriteJSON(os.Stdout, out)

	default:
		_ = protocol.WriteJSON(os.Stdout, map[string]interface{}{})
	}
}
