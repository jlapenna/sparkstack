from dataclasses import dataclass
from pathlib import Path


@dataclass
class E2EContext:
    root_dir: Path
    stack_dir: Path
    oc_bin: Path
    gateway_url: str
    telemetry_url: str
    soak_minutes: int
    long_conversation_messages: int
