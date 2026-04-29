import json
import sys
import urllib.request

with urllib.request.urlopen(f"http://localhost:3200/api/traces/{sys.argv[1]}") as f:
    data = json.load(f)
    for batch in data.get("batches", []):
        service = "unknown"
        for attr in batch.get("resource", {}).get("attributes", []):
            if attr.get("key") == "service.name":
                service = attr.get("value", {}).get("stringValue")
        for scope in batch.get("scopeSpans", []):
            for span in scope.get("spans", []):
                name = span.get("name")
                start = int(span.get("startTimeUnixNano", 0))
                end = int(span.get("endTimeUnixNano", 0))
                duration_ms = (end - start) / 1e6
                status = span.get("status", {}).get("code", 0)
                print(f"[{service}] {name} - {duration_ms}ms (Status: {status})")
                for attr in span.get("attributes", []):
                    key = attr.get("key")
                    val = attr.get("value", {}).get("stringValue", attr.get("value"))
                    print(f"   {key}: {val}")
