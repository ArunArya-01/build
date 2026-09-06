package flightrecorder

import (
	"bytes"
	"context"
	"fmt"
	"os/exec"
	"strings"
	"time"
)

type BriefingEngine struct {
	RepoPath   string
	Databricks *DatabricksClient
	Graph      *GraphBridge
}

func NewBriefingEngine(repoPath string) *BriefingEngine {
	return &BriefingEngine{
		RepoPath:   repoPath,
		Databricks: NewDatabricksClient(repoPath),
		Graph:      NewGraphBridge(repoPath),
	}
}

func (b *BriefingEngine) GenerateBriefing(prompt string, touchedFiles []string) string {
	// 1. Analyze historical risk from Databricks
	history := b.Databricks.AnalyzeRisk(touchedFiles, prompt)

	// 2. Query code blast radius from Entire Graph
	target := "payment"
	if len(touchedFiles) > 0 {
		target = touchedFiles[0]
	}
	impact := b.Graph.QueryImpact(target)

	// 3. Query previous Entire checkpoint context
	checkpointContext := b.fetchEntireCheckpointContext()

	var sb strings.Builder
	sb.WriteString("\n═══════════════════════════════════════════════════════════════\n")
	sb.WriteString("  ⚡ [CODEBASE FLIGHT RECORDER] — BEFORE YOU CODE BRIEFING\n")
	sb.WriteString("═══════════════════════════════════════════════════════════════\n\n")

	if history.RiskLevel == "HIGH" {
		sb.WriteString("Risk: 🔴 HIGH\n\n")
	} else if history.RiskLevel == "MEDIUM" {
		sb.WriteString("Risk: 🟡 MEDIUM\n\n")
	} else {
		sb.WriteString("Risk: 🟢 LOW\n\n")
	}

	sb.WriteString("Affected components (Entire Graph):\n")
	if len(impact.BlastRadius) > 0 {
		for _, comp := range impact.BlastRadius {
			sb.WriteString(fmt.Sprintf("• %s\n", comp))
		}
	} else {
		for _, comp := range history.AffectedComponents {
			sb.WriteString(fmt.Sprintf("• %s\n", comp))
		}
	}
	sb.WriteString("\n")

	if len(history.PreviousFailedPaths) > 0 {
		sb.WriteString("Previous failed approach (Entire Checkpoints):\n")
		for _, path := range history.PreviousFailedPaths {
			sb.WriteString(fmt.Sprintf("• %s\n", path))
		}
		sb.WriteString("\n")
	}

	if len(history.KnownIssues) > 0 {
		sb.WriteString("Known unresolved issues:\n")
		for _, issue := range history.KnownIssues {
			sb.WriteString(fmt.Sprintf("• %s\n", issue))
		}
		sb.WriteString("\n")
	}

	if len(history.RecommendedTests) > 0 {
		sb.WriteString("Recommended tests:\n")
		for _, test := range history.RecommendedTests {
			sb.WriteString(fmt.Sprintf("• %s\n", test))
		}
		sb.WriteString("\n")
	}

	sb.WriteString(fmt.Sprintf("Reason for warning (Databricks Analytics):\n• %s\n", history.ReasonForWarning))

	if checkpointContext != "" {
		sb.WriteString(fmt.Sprintf("\nRecent Entire Checkpoint Context:\n%s\n", checkpointContext))
	}

	sb.WriteString("───────────────────────────────────────────────────────────────\n")
	return sb.String()
}

func (b *BriefingEngine) fetchEntireCheckpointContext() string {
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	cmd := exec.CommandContext(ctx, "entire", "recap", "--limit", "1")
	cmd.Dir = b.RepoPath
	var out bytes.Buffer
	cmd.Stdout = &out
	if err := cmd.Run(); err == nil {
		return strings.TrimSpace(out.String())
	}
	return ""
}
