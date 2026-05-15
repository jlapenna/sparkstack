import os
from dataclasses import dataclass
from pathlib import Path

import httpx
from dotenv import load_dotenv


@dataclass
class E2EContext:
    root_dir: Path
    stack_dir: Path
    openclaw_bin: Path
    gateway_url: str
    telemetry_url: str
    soak_minutes: int
    long_conversation_messages: int

    def gateway_client(self) -> httpx.AsyncClient:
        """Return an httpx.AsyncClient pre-configured for the LiteLLM gateway."""
        load_dotenv(self.root_dir / ".env")
        api_key = os.getenv("LITELLM_MASTER_KEY", "")
        if not api_key:
            raise AssertionError("LITELLM_MASTER_KEY not found in .env")

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        return httpx.AsyncClient(base_url=self.gateway_url, headers=headers)
