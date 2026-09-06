package flightrecorder

import (
	"strings"
	"testing"
	"time"
)

func TestBriefingGenerationHighRisk(t *testing.T) {
	engine := NewBriefingEngine(".")
	briefing := engine.GenerateBriefing("Refactor payment library and webhook verification", []string{"payment.py", "webhook.py"})

	if !strings.Contains(briefing, "Risk: 🔴 HIGH") {
		t.Fatalf("expected HIGH risk rating for payment task, got: %s", briefing)
	}
	if !strings.Contains(briefing, "checkout_service.py") && !strings.Contains(briefing, "Checkout Service") {
		t.Fatalf("expected checkout blast radius impact, got: %s", briefing)
	}
	if !strings.Contains(briefing, "Webhook") {
		t.Fatalf("expected webhook failure context, got: %s", briefing)
	}
	if !strings.Contains(briefing, "Recommended tests:") {
		t.Fatalf("expected recommended tests section, got: %s", briefing)
	}
}

func TestDatabricksTelemetryLake(t *testing.T) {
	client := NewDatabricksClient(".")
	telemetry := StructuredSessionTelemetry{
		SessionID:          "test-session-999",
		Timestamp:          time.Now(),
		FilesTouched:       []string{"payment.py"},
		ComponentsInvolved: []string{"PaymentGateway"},
		ChangeType:         "migration",
		TestResult:         "passed",
		Retries:            1,
		RiskScore:          0.85,
		Outcome:            "verified",
	}

	err := client.LogSession(telemetry)
	if err != nil {
		t.Fatalf("expected clean telemetry logging, got %v", err)
	}

	risk := client.AnalyzeRisk([]string{"payment.py"}, "migration")
	if risk.RiskLevel != "HIGH" {
		t.Fatalf("expected HIGH risk rating from Databricks analysis")
	}
}
