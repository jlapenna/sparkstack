#!/usr/bin/env python3
import requests
import subprocess
import time
import pytest

def test_verify_tracing():
    print("Triggering an agent inference to generate a trace...")
    try:
        # We run the command inside the gateway container to guarantee it works without needing local openclaw config
        subprocess.run(
            ["docker", "exec", "openclaw-openclaw-gateway-1", "node", "dist/index.js", "agent", "--agent", "jclaw", "--message", "Tracing verification test. Please reply with OK."],
            check=True,
            capture_output=True
        )
    except subprocess.CalledProcessError as e:
        pytest.fail(f"Failed to trigger inference: {e.stderr.decode('utf-8')}")

    print("Inference completed. Waiting for traces to propagate to Tempo...")
    time.sleep(5)  # Give Tempo a few seconds to ingest

    tempo_search_url = "http://localhost:3200/api/search?tags=service.name=openclaw-gateway&limit=10"
    try:
        response = requests.get(tempo_search_url)
        response.raise_for_status()
        traces = response.json().get("traces", [])
    except Exception as e:
        pytest.fail(f"Failed to query Tempo search API: {e}")

    assert traces, "No traces found for openclaw-gateway in Tempo."

    required_services = {"openclaw-gateway", "litellm", "vllm-main"}
    found_e2e_trace = False

    for trace in traces:
        trace_id = trace["traceID"]
        try:
            trace_resp = requests.get(f"http://localhost:3200/api/traces/{trace_id}")
            trace_resp.raise_for_status()
            trace_data = trace_resp.json()
        except Exception as e:
            print(f"Failed to fetch trace {trace_id}: {e}")
            continue

        services_in_trace = set()
        for batch in trace_data.get("batches", []):
            resource = batch.get("resource", {})
            for attr in resource.get("attributes", []):
                if attr.get("key") == "service.name":
                    services_in_trace.add(attr.get("value", {}).get("stringValue"))

        print(f"Trace {trace_id} contains services: {services_in_trace}")

        if required_services.issubset(services_in_trace):
            print(f"\n✅ SUCCESS: E2E Trace {trace_id} successfully linked across {required_services}!")
            found_e2e_trace = True
            break

    assert found_e2e_trace, f"FAILED: Could not find a single trace containing all required services: {required_services}"
