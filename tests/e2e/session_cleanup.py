"""Utility for cleaning up test sessions from the verifier agent's session store."""

import contextlib
import json
from pathlib import Path

from loguru import logger


def _safe_log(level: str, msg: str) -> None:
    with contextlib.suppress(ValueError):
        getattr(logger, level)(msg)


VERIFIER_SESSIONS_DIR = Path.home() / ".openclaw" / "agents" / "verifier" / "sessions"
SESSIONS_INDEX = VERIFIER_SESSIONS_DIR / "sessions.json"


def cleanup_session(session_id: str) -> None:
    """Remove a test session from the verifier's session store by session ID.

    Searches the sessions.json index for any session whose key contains
    the given session_id, then removes the corresponding transcript files
    (.jsonl, .trajectory.jsonl, .trajectory-path.json) and the index entry.
    """
    if not SESSIONS_INDEX.exists():
        _safe_log("debug", f"Sessions index not found at {SESSIONS_INDEX}, skipping cleanup.")
        return

    try:
        index = json.loads(SESSIONS_INDEX.read_text())
    except (json.JSONDecodeError, OSError) as e:
        _safe_log("warning", f"Failed to read sessions index: {e}")
        return

    sessions = index.get("sessions", [])
    if not isinstance(sessions, list):
        _safe_log("debug", "Sessions index has unexpected format, skipping cleanup.")
        return

    uuids_to_remove: list[str] = []
    keys_to_remove: list[str] = []

    for entry in sessions:
        session_key = entry.get("sessionKey", "")
        sid = entry.get("id", "")
        if session_id in session_key or session_id in sid:
            uuids_to_remove.append(sid)
            keys_to_remove.append(session_key)

    if not uuids_to_remove:
        _safe_log("debug", f"No sessions found matching '{session_id}', skipping cleanup.")
        return

    # Remove transcript files
    for sid in uuids_to_remove:
        for suffix in [".jsonl", ".trajectory.jsonl", ".trajectory-path.json"]:
            transcript = VERIFIER_SESSIONS_DIR / f"{sid}{suffix}"
            if transcript.exists():
                transcript.unlink()
                _safe_log("debug", f"Removed transcript: {transcript.name}")

    # Update the index
    updated_sessions = [s for s in sessions if s.get("id") not in uuids_to_remove]
    index["sessions"] = updated_sessions

    try:
        SESSIONS_INDEX.write_text(json.dumps(index, indent=2))
    except OSError as e:
        _safe_log("warning", f"Failed to update sessions index: {e}")
        return

    _safe_log(
        "info",
        f"Cleaned up {len(uuids_to_remove)} session(s) for '{session_id}': "
        f"{', '.join(k for k in keys_to_remove)}",
    )


def wipe_all_sessions(label: str = "wipe") -> None:
    """Wipe all verifier sessions.

    The verifier agent accumulates session transcripts across test runs.
    When the lossless-claw context engine loads this accumulated context
    (often 50k+ tokens), the model degrades — emitting tool calls inside
    reasoning tokens instead of using the proper tool_calls format.

    This function physically deletes the verifier's session store to ensure
    a clean slate.
    """
    if not VERIFIER_SESSIONS_DIR.exists():
        _safe_log("debug", f"[{label}] No verifier sessions directory found, skipping.")
        return
    count = 0
    for f in VERIFIER_SESSIONS_DIR.iterdir():
        if f.is_file():
            f.unlink()
            count += 1
    _safe_log(
        "info", f"[{label}] Removed {count} verifier session file(s) from {VERIFIER_SESSIONS_DIR}"
    )
