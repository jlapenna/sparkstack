---
name: proactive-debugging
description: "Proactively hunt for systemic anomalies, hidden latency regressions, and silent errors in the Spark-Stack infrastructure using Tempo distributed tracing and diagnostic scripts."
---

# Proactive Debugging

Unlike reactive debugging (where you respond to an active incident or broken test), **Proactive Debugging** involves hunting for anomalies, unhandled edge cases, and performance regressions *before* they surface to the user. 

In the `spark-stack` environment, OpenTelemetry traces sent to Grafana Tempo are the primary vehicle for proactive discovery.

## 1. When to Use This Skill
- After a major infrastructure, model, or configuration upgrade.
- When performing a system health audit.
- During idle time to discover hidden inefficiencies in the LLM or Gateway routing paths.
- To validate that recently applied fixes haven't introduced silent downstream errors.

## 2. Proactive Hunt Patterns

### A. Hunting for Silent Errors
Some services (like `litellm` or `vllm`) might experience localized errors (e.g., retries, malformed inputs) that are handled gracefully and don't crash the stack, but indicate a latent issue.

**Query Tempo for any trace containing an error tag:**
```bash
curl -s "http://localhost:3200/api/search?limit=50&tags=error=true" | jq '.traces[] | {id: .traceID, start: .startTimeUnixNano, name: .rootTraceName}'
```
*If you find traces here, use the `stack-debugging` skill to pull the full trace and identify the exact span and service throwing the error.*

### B. Hunting for Latency Regressions
Identify requests taking unusually long, which may indicate SQLite locking, model loading thrashing, or network timeouts.

**Query Tempo for traces taking longer than 15 seconds (15000ms):**
```bash
curl -s "http://localhost:3200/api/search?limit=50&minDuration=15000ms" | jq '.traces[] | {id: .traceID, duration: .durationMs, name: .rootTraceName}'
```
*Look for outlier durations. If `vllm-main` takes 14s but the `openclaw-gateway` takes 30s, the delay is in the gateway's context building or session locking.*

### C. Hunting for Truncated Context
Find traces where the LLM input messages are dangerously close to the OTel attribute limit, suggesting the context window is near maximum or OTel truncation is actively occurring.

**Check the length of `gen_ai.input.messages` for recent traces:**
```bash
for TRACE in $(curl -s "http://localhost:3200/api/search?limit=5" | jq -r '.traces[].traceID'); do
  echo -n "Trace $TRACE length: "
  curl -s "http://localhost:3200/api/traces/$TRACE" | jq -r '[.batches[].scopeSpans[].spans[].attributes[]? | select(.key == "gen_ai.input.messages")] | .[0].value.stringValue' | wc -c
done
```

## 3. Automated Proactive Analysis Script

To automate the proactive hunting process, use the `analyze_traces.py` script.

**Usage:**
```bash
uv run scripts/analyze_traces.py
```

This script will:
1. Connect to Tempo.
2. Fetch the last 50 traces.
3. Automatically flag traces that contain `error=true`.
4. Flag traces with a duration > 10,000ms.
5. Flag traces where components of the stack (like `openclaw-gateway` or `vllm-main`) are suspiciously missing from the span attributes.

## 4. Remediation Workflow
When a proactive anomaly is found:
1. **Isolate**: Determine if the issue is deterministic (happens on specific prompts) or systemic (happens randomly due to load).
2. **Contextualize**: Check the `openclaw-gateway` session state (using `scripts/clear_stuck_sessions.py` if state locks are suspected).
3. **Report**: Create an issue detailing the Trace ID, the missing/erroring span, and the latency breakdown.
4. **Fix**: Use the `stack-debugging` skill patterns to patch the underlying issue.
