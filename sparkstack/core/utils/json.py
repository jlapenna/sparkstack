import json
from typing import Any


def parse_cli_json(stdout: str) -> dict[str, Any] | list[Any]:
    """Robustly extract and parse a JSON object or array from CLI stdout (ignoring preambles/warnings).

    When multiple JSON objects are present the envelope (containing a ``status``
    key) is preferred over trailing diagnostic blobs.
    """
    decoder = json.JSONDecoder()

    start_idx = -1
    for i, char in enumerate(stdout):
        if char in ("{", "["):
            start_idx = i
            break

    if start_idx == -1:
        raise ValueError("Could not find a JSON object or array in the command output.")

    all_parsed: list[dict[str, Any] | list[Any]] = []
    scan_idx = start_idx
    while scan_idx != -1:
        try:
            parsed, parsed_len = decoder.raw_decode(stdout[scan_idx:])
            all_parsed.append(parsed)
            # Advance past parsed content to look for more JSON objects
            next_start = -1
            remainder = stdout[scan_idx + parsed_len :]
            for i, char in enumerate(remainder):
                if char in ("{", "["):
                    next_start = scan_idx + parsed_len + i
                    break
            scan_idx = next_start
        except json.JSONDecodeError:
            next_start = -1
            for i, char in enumerate(stdout[scan_idx + 1 :], start=scan_idx + 1):
                if char in ("{", "["):
                    next_start = i
                    break
            scan_idx = next_start

    if not all_parsed:
        raise ValueError("Found JSON-like structure but failed to parse any valid objects.")

    # Prefer the envelope (dict with 'status' key) over diagnostic blobs.
    for obj in all_parsed:
        if isinstance(obj, dict) and "status" in obj:
            return obj

    return all_parsed[0]
