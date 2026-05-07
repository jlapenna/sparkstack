import json


def extract_cli_json(output: str) -> dict | None:
    """Extract the CLI envelope JSON from ``openclaw agent --json`` output.

    The CLI may emit multiple JSON objects.  We prefer the envelope that
    contains a ``status`` key (``{status: "ok", result: ...}``).  If no
    envelope is found, fall back to the last parsed dict.
    """
    all_parsed: list[dict] = []
    decoder = json.JSONDecoder()
    idx = output.find("{")
    while idx != -1:
        try:
            parsed, parsed_len = decoder.raw_decode(output[idx:])
            if isinstance(parsed, dict):
                all_parsed.append(parsed)
            idx = output.find("{", idx + parsed_len)
        except json.JSONDecodeError:
            idx = output.find("{", idx + 1)

    for obj in all_parsed:
        if "status" in obj:
            return obj
    return all_parsed[-1] if all_parsed else None
