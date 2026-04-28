#!/usr/bin/env python3
import json
import sys
import urllib.error
import urllib.request

TEMPO_SEARCH_URL = "http://localhost:3200/api/search"
TEMPO_TRACE_URL = "http://localhost:3200/api/traces/"

def fetch_json(url):
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.URLError as e:
        print(f"Error connecting to Tempo: {e}")
        return None

def analyze_traces():
    print("Starting Proactive Trace Analysis...")

    # 1. Fetch recent traces
    search_url = f"{TEMPO_SEARCH_URL}?limit=50"
    data = fetch_json(search_url)
    if not data or 'traces' not in data:
        print("Could not retrieve traces from Tempo.")
        sys.exit(1)

    traces = data['traces']
    print(f"Found {len(traces)} recent traces. Analyzing...")

    flagged = 0

    for trace in traces:
        trace_id = trace.get("traceID")
        duration = trace.get("durationMs", 0)

        flags = []

        # Rule 1: Latency Regression
        if duration > 10000:
            flags.append(f"High Latency: {duration}ms")

        # Rule 2: Fetch full trace for detailed analysis
        trace_details = fetch_json(f"{TEMPO_TRACE_URL}{trace_id}")
        if trace_details and "batches" in trace_details:
            services_found = set()
            has_error = False

            for batch in trace_details["batches"]:
                # Check for errors in spans
                for scope in batch.get("scopeSpans", []):
                    for span in scope.get("spans", []):
                        if span.get("status", {}).get("code") == 2: # STATUS_CODE_ERROR
                            has_error = True

                # Extract service names
                for attr in batch.get("resource", {}).get("attributes", []):
                    if attr.get("key") == "service.name":
                        services_found.add(attr.get("value", {}).get("stringValue"))

            # Rule 3: Error spans
            if has_error:
                flags.append("Error Span Found")

            # Rule 4: Incomplete trace paths (e.g. litellm and openclaw are missing from vllm trace)
            expected_services = {"openclaw-gateway", "litellm", "vllm-main"}
            if not expected_services.issubset(services_found):
                missing = expected_services - services_found
                # We only flag if it's supposed to be an E2E trace but is missing components.
                if len(services_found) > 1: # Basic heuristic to avoid flagging single-service debug traces
                    flags.append(f"Missing Services: {missing}")

        if flags:
            print(f"\n⚠️ Trace Flagged: {trace_id}")
            for f in flags:
                print(f"  - {f}")
            flagged += 1

    print(f"\nAnalysis complete. Flagged {flagged} traces.")

if __name__ == "__main__":
    analyze_traces()
