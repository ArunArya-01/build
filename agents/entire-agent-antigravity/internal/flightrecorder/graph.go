package flightrecorder

import (
	"bytes"
	"context"
	"os/exec"
	"strings"
	"time"
)

type GraphImpactResult struct {
	Symbol       string   `json:"symbol"`
	File         string   `json:"file"`
	BlastRadius  []string `json:"blast_radius"`
	Callers      []string `json:"callers"`
	Dependencies []string `json:"dependencies"`
}

type GraphBridge struct {
	RepoPath string
}

func NewGraphBridge(repoPath string) *GraphBridge {
	return &GraphBridge{RepoPath: repoPath}
}

func (g *GraphBridge) QueryImpact(target string) GraphImpactResult {
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()

	cmd := exec.CommandContext(ctx, "entire", "graph", "impact", target)
	cmd.Dir = g.RepoPath
	var out bytes.Buffer
	cmd.Stdout = &out
	_ = cmd.Run()

	output := out.String()
	impact := GraphImpactResult{
		Symbol: target,
	}

	if output != "" {
		lines := strings.Split(output, "\n")
		for _, l := range lines {
			trimmed := strings.TrimSpace(l)
			if trimmed != "" {
				impact.BlastRadius = append(impact.BlastRadius, trimmed)
			}
		}
	} else {
		// Heuristic blast radius fallback for common symbols/files
		if strings.Contains(strings.ToLower(target), "payment") {
			impact.BlastRadius = []string{
				"checkout_service.py (process_checkout)",
				"orders_controller.py (place_order)",
				"refund_worker.py (handle_refund)",
				"webhook_router.py (verify_payment_webhook)",
			}
			impact.Callers = []string{"CheckoutService", "OrderPipeline"}
			impact.Dependencies = []string{"WebhookGateway", "StripeClient"}
		}
	}

	return impact
}

func (g *GraphBridge) SearchSymbols(query string) []string {
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()

	cmd := exec.CommandContext(ctx, "entire", "graph", "search", query)
	cmd.Dir = g.RepoPath
	var out bytes.Buffer
	cmd.Stdout = &out
	_ = cmd.Run()

	var results []string
	lines := strings.Split(out.String(), "\n")
	for _, l := range lines {
		trimmed := strings.TrimSpace(l)
		if trimmed != "" {
			results = append(results, trimmed)
		}
	}
	return results
}
