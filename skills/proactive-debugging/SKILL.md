---
name: proactive-debugging
description: "Proactively hunt for systemic anomalies, hidden latency regressions, and silent errors in the Spark-Stack infrastructure using Tempo distributed tracing and diagnostic scripts."
---

# Proactive Debugging

Unlike reactive debugging (where you respond to an active incident or broken test), **Proactive Debugging** involves open-ended hunting for anomalies, unhandled edge cases, and regressions *before* they surface to the user.

In the `spark-stack` environment, OpenTelemetry traces sent to Grafana Tempo are a great vehicle for discovery. However, **do not limit yourself to only the patterns below.** Trust your intuition, craft your own queries, and investigate any suspicious metrics, logs, or traces you uncover.

## 1. When to Use This Skill

- After a major infrastructure, model, or configuration upgrade.
- When performing a system health audit.
- During idle time to discover hidden inefficiencies or strange behaviors in the stack.
- To validate that recently applied fixes haven't introduced silent downstream errors.

## 2. Example Proactive Hunt Patterns

These are *starting points* for your investigation. Feel free to write custom `jq` filters, check Docker logs, inspect SQLite files, or query other endpoints if you suspect other classes of anomalies.

### A. Hunting for Silent Errors

Some services might experience localized errors that are handled gracefully and don't crash the stack, but indicate a latent issue.

**Query Tempo for traces containing an error tag:**

```bash
curl -s "http://localhost:3200/api/search?limit=50&tags=error=true" | jq '.traces[] | {id: .traceID, start: .startTimeUnixNano, name: .rootTraceName}'
```

*If you find traces here, pull the full trace and identify the exact span and service throwing the error.*

### B. Hunting for Latency Regressions

Identify requests taking unusually long, which may indicate locking issues, thrashing, or network timeouts.

**Query Tempo for traces taking longer than 15 seconds:**

```bash
curl -s "http://localhost:3200/api/search?limit=50&minDuration=15000ms" | jq '.traces[] | {id: .traceID, duration: .durationMs, name: .rootTraceName}'
```

*Look for outlier durations and compare where the time is spent.*

### C. Hunting for Truncated Context

Find traces where the LLM input messages are dangerously close to the OTel attribute limit.

**Check the length of `gen_ai.input.messages`:**

```bash
for TRACE in $(curl -s "http://localhost:3200/api/search?limit=5" | jq -r '.traces[].traceID'); do
  echo -n "Trace $TRACE length: "
  curl -s "http://localhost:3200/api/traces/$TRACE" | jq -r '[.batches[].scopeSpans[].spans[].attributes[]? | select(.key == "gen_ai.input.messages")] | .[0].value.stringValue' | wc -c
done
```

### D. Open-Ended Exploration

Don't hesitate to inspect system resource usage (CPU/RAM/GPU), database sizes, Docker container network stats, or other telemetry signals. Real anomalies often hide outside of structured trace data.

## 3. Automated Analysis Scripts

To assist your hunt, you can use the `analyze_traces.py` script as a baseline check.

**Usage:**

```bash
uv run scripts/analyze_traces.py
```

This script will flag obvious issues (errors, slow traces, missing spans). **Use its output as a jumping-off point for deeper, manual investigation.**

## 4. Remediation Guidelines

When you discover an anomaly:

1. **Investigate Deeply**: Use all available tools to determine the root cause. Is it a race condition? A resource leak? A subtle configuration error?
2. **Contextualize**: Look at the broader system state (databases, container health, concurrent processes).
3. **Formulate a Fix**: Depending on the severity, either apply a patch directly using standard `stack-debugging` patterns, or document your findings clearly for later review.
