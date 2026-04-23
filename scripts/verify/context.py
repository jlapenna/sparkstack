from dataclasses import dataclass
from pathlib import Path


@dataclass
class VerifyContext:
    root_dir: Path
    stack_dir: Path
    oc_bin: Path
    gateway_url: str
    telemetry_url: str
