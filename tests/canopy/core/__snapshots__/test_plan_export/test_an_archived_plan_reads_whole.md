---
kind: "plan"
id: 1
ticket_key: "PROJ-1"
run_id: 2
created_at: "<time>"
status: "approved"
sha256: "206ee709bd5410f2ca2c9046516517d6dca868664e6de86f07c231f0cb9fd627"
size: 70
approved_sha256: "206ee709bd5410f2ca2c9046516517d6dca868664e6de86f07c231f0cb9fd627"
approved_at: "<time>"
approved_channel: "planner"
approved_reason: "One endpoint, *no* schema change."
effort: "small"
approved_level: "normal"
persona: "skeptic"
model: "anthropic/claude-x@high"
models: ["anthropic/claude-x@high", "anthropic/claude-y"]
cost_usd: 0.25
total_cost_usd: 0.75
---

# Plan: PROJ-1 Export reports as CSV

## api

Add `GET /reports.csv`.
