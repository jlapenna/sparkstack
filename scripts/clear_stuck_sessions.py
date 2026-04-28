#!/usr/bin/env python3
import glob
import json
import os


def clear_stuck_sessions():
    """
    Scans all OpenClaw session store JSON files and resets any session
    stuck in the 'processing' state back to 'idle'. This resolves SQLite
    database lock contentions caused by orphaned embedded agents.
    """
    home = os.path.expanduser("~")
    # Search common OpenClaw state directories for session stores
    search_paths = [
        f"{home}/.openclaw/agents/*/sessions/sessions.json",
        f"{home}/.openclaw/workspaces/*/sessions.json",
        f"{home}/.openclaw-dev/agents/*/sessions/sessions.json",
        f"{home}/.openclaw-dev/workspaces/*/sessions.json",
    ]

    found_files = []
    for pattern in search_paths:
        found_files.extend(glob.glob(pattern))

    if not found_files:
        print("No OpenClaw session store files found.")
        return

    fixed_count = 0
    for file_path in found_files:
        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)

            modified = False
            if isinstance(data, dict):
                # Typically data is a dictionary of sessionKey -> sessionData
                for session_key, session_data in data.items():
                    if isinstance(session_data, dict) and session_data.get("status") == "running":
                        print(f"Resetting stuck session: {session_key} in {file_path}")
                        session_data["status"] = "idle"
                        modified = True

            if modified:
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                fixed_count += 1
        except Exception as e:
            print(f"Failed to process {file_path}: {e}")

    if fixed_count > 0:
        print(f"Successfully cleared stuck sessions in {fixed_count} file(s).")
        print(
            "Important: Restart the OpenClaw Gateway (e.g., `docker restart openclaw-openclaw-gateway-1`) for the changes to take effect."
        )
    else:
        print("No stuck sessions found.")


if __name__ == "__main__":
    clear_stuck_sessions()
