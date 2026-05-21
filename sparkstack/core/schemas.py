"""
Pydantic models for service configurations.
"""

import os
import warnings
from dataclasses import dataclass, field
from enum import Enum
from typing import Annotated, Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from sparkstack.core.env import (
    OPENCLAW_NODE_TARGET,
    SPARKSTACK_HEAD_TAILNET_IP,
    WORKER_TAILNET_IP,
    is_overlay_configured,
)


@dataclass
class ModelRequest:
    """A parsed model request with role, recipe identity, optional target, and optional overrides."""

    role: str | None
    recipe: str
    target: str | None = None
    overrides: dict[str, str] = field(default_factory=dict)

    @property
    def is_remote(self) -> bool:
        return bool(self.target and self.target != "localhost")

    @classmethod
    def from_cli_arg(cls, arg: str) -> "ModelRequest":
        """Parse the ``role=recipe@target:k=v,k=v`` CLI shorthand."""
        overrides: dict[str, str] = {}
        target: str | None = None

        if ":" in arg:
            arg, overrides_str = arg.split(":", 1)
            for item in overrides_str.split(","):
                if "=" in item:
                    k, v = item.split("=", 1)
                    overrides[k] = v

        if "@" in arg:
            arg, target = arg.split("@", 1)

        if "=" in arg:
            role, recipe = arg.split("=", 1)
            return cls(role=role, recipe=recipe, target=target, overrides=overrides)

        return cls(role=None, recipe=arg, target=target, overrides=overrides)


class ServiceStatus(Enum):
    WAITING = "waiting"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    SKIPPED = "skipped"


class PassThroughModel(BaseModel):
    """Base model that allows extra attributes to pass through unmapped parameters to the output."""

    model_config = ConfigDict(extra="allow")


class BaseSchema(BaseModel):
    """Base model with automatic camelCase alias support for OpenClaw compatibility."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="allow")


# --- OpenClaw Models ---


class OpenClawModelCompat(BaseSchema):
    """Compat flags matching OpenClaw's ModelCompatConfig type.

    Field names here map to OpenClaw's camelCase keys via alias_generator.
    Only set fields the registry explicitly provides — no hardcoded defaults.
    """

    supports_tools: bool | None = None
    thinking_format: str | None = None
    supports_developer_role: bool | None = None
    supports_prompt_cache_key: bool | None = None
    supports_store: bool | None = None
    supports_reasoning_effort: bool | None = None
    max_tokens_field: str | None = None


class OpenClawModelCost(BaseSchema):
    """Per-token cost metadata required by the OpenClaw provider schema.

    Self-hosted / local models should declare zero cost so OpenClaw can
    surface cost tracking without treating missing fields as configuration
    errors.  Values are in USD per token.
    """

    input: float = 0.0
    output: float = 0.0
    cache_read: float = 0.0
    cache_write: float = 0.0


class OpenClawModel(BaseSchema):
    """Model entry matching OpenClaw's ModelDefinitionConfig type.

    context_window and max_tokens are required — they must come from the
    registry, not fabricated defaults.

    IMPORTANT: max_tokens is the per-turn *completion* budget (how many tokens
    the model can generate), NOT the total context capacity.  Setting
    max_tokens >= context_window creates a "poison pill" where OpenClaw's
    compaction reserve exceeds the context window, causing infinite retry
    loops and silent context loss.

    Industry best practice: max_tokens should be a fixed value (8k-32k)
    appropriate for the task, not a fraction of context_window. The
    MAX_COMPLETION_TOKENS ceiling enforces this.
    """

    # Maximum completion budget per turn.  Industry standard for coding agents
    # is 16k-32k tokens -- enough for large code blocks and reasoning traces,
    # but leaves the vast majority of the context window for conversation history.
    MAX_COMPLETION_TOKENS: ClassVar[int] = 32_768

    id: str
    name: str
    context_window: int
    max_tokens: int | None = None
    input: list[Literal["text", "image"]] = Field(default_factory=lambda: ["text"])
    reasoning: bool = False
    api: str | None = None
    cost: OpenClawModelCost = Field(default_factory=OpenClawModelCost)
    compat: OpenClawModelCompat | None = None

    @model_validator(mode="after")
    def _validate_model(self) -> "OpenClawModel":
        """Validate model properties and prevent the compaction poison pill.

        Three guards:
        1. Tokenizer Drift Buffer: Downscale context_window by 15% to safely
           encapsulate tokenizer expansion rates between OpenClaw and backends.
        2. max_tokens >= context_window → hard clamp to min(MAX_COMPLETION_TOKENS,
           context_window // 2).  Without this, reserveTokens = max_tokens + headroom
           exceeds the context window, making compaction unsatisfiable.
        3. max_tokens > MAX_COMPLETION_TOKENS → soft clamp with warning.
           No agent needs 131k tokens of output per turn; the downstream
           reserveTokens formula (max_tokens + 8192) would consume >50% of the
           context, starving conversation history.
        """
        # Guard 1: Tokenizer Drift Buffer (Reference: Incident 2026-05-02)
        # Downscale by 15% to protect against 13.8% observed tokenizer drift.
        if self.context_window > 0:
            self.context_window = int(self.context_window * 0.85)

        is_embedding = "embedding" in self.id.lower()

        if not self.api:
            self.api = "openai-embeddings" if is_embedding else "openai-responses"

        if self.max_tokens is None or is_embedding:
            return self

        # Guard 2 & 3: Compaction Poison Pill (Reference: Incident 2026-05-10)
        ceiling = min(self.MAX_COMPLETION_TOKENS, self.context_window // 2)
        if self.max_tokens >= self.context_window > 0:
            warnings.warn(
                f"OpenClawModel '{self.id}': max_tokens ({self.max_tokens}) >= "
                f"context_window ({self.context_window}). Clamping to {ceiling} "
                f"to prevent compaction poison-pill loop.",
                stacklevel=2,
            )
            self.max_tokens = ceiling
        elif self.max_tokens > self.MAX_COMPLETION_TOKENS and self.context_window > 0:
            warnings.warn(
                f"OpenClawModel '{self.id}': max_tokens ({self.max_tokens}) exceeds "
                f"recommended ceiling ({self.MAX_COMPLETION_TOKENS}). Clamping to "
                f"{ceiling} to prevent excessive reserve token consumption.",
                stacklevel=2,
            )
            self.max_tokens = ceiling
        return self


# --- Registry Models (Discriminated Union) ---


class ComposeData(BaseModel):
    """Basic structure for docker compose data."""

    model_config = ConfigDict(extra="allow")
    compose: dict[str, Any] = Field(default_factory=dict)


class BaseRegistryModel(PassThroughModel):
    identity: str
    vram_usage: float


class SparkrunRegistryModel(BaseRegistryModel):
    kind: Literal["sparkrun"] = "sparkrun"
    recipe: dict[str, Any]
    recipe_path: str


class ComposeRegistryModel(BaseRegistryModel):
    kind: Literal["compose"] = "compose"
    data: ComposeData


RegistryModel = Annotated[SparkrunRegistryModel | ComposeRegistryModel, Field(discriminator="kind")]


# --- Provider & Stack Configs ---


def _default_litellm_base_url() -> str:
    """Return the default LiteLLM base URL based on the current network topology.

    When the Headscale overlay is active, LiteLLM runs in
    network_mode: container:sparkstack-head-sidecar.  Its port 4000
    is bound in the sidecar's network namespace, so it is only
    routable via the sidecar's Docker container name on
    sparkstack-net.  The service name "litellm" only resolves
    within the compose project's internal network.
    """
    if is_overlay_configured():
        return "http://sparkstack-head-sidecar:4000/v1"
    return f"http://{os.getenv('WORKER_TAILNET_IP', 'litellm')}:4000/v1"


class ApiKeyConfig(BaseSchema):
    source: str = "env"
    provider: str = "default"
    id: str = "LITELLM_MASTER_KEY"


class RequestConfig(BaseSchema):
    allow_private_network: bool = True


class OpenClawCompactionConfig(BaseSchema):
    model_config = ConfigDict(extra="allow")
    mode: str | None = None
    reserveTokensFloor: int | None = None
    reserveTokens: int | None = None


class OpenClawAgentDefaults(BaseSchema):
    compaction: OpenClawCompactionConfig | None = None
    models: dict[str, Any] = Field(default_factory=dict)


class OpenClawAgentsConfig(BaseSchema):
    defaults: OpenClawAgentDefaults = Field(default_factory=OpenClawAgentDefaults)


class OpenClawModelsConfig(BaseSchema):
    providers: dict[str, Any] = Field(default_factory=dict)


class OpenClawConfig(BaseSchema):
    """Root configuration for openclaw.json."""

    models: OpenClawModelsConfig = Field(default_factory=OpenClawModelsConfig)
    agents: OpenClawAgentsConfig = Field(default_factory=OpenClawAgentsConfig)

    def update_from_spark_provider(self, provider: "SparkProvider") -> None:
        """Update the configuration from a SparkProvider instance.

        This injects the provider into the `models` block and updates global
        agent defaults (like compaction reserve and placeholder model keys) to
        ensure OpenClaw operates safely with the provided models.
        """
        self.models.providers["spark"] = provider.model_dump(by_alias=True, exclude_none=True)

        max_gen_tokens = 0
        min_context_window = float("inf")

        for m in provider.models:
            if m.api != "openai-embeddings":
                if m.max_tokens is not None:
                    max_gen_tokens = max(max_gen_tokens, m.max_tokens)
                if m.context_window > 0:
                    min_context_window = min(min_context_window, m.context_window)

        if self.agents.defaults.compaction is None:
            self.agents.defaults.compaction = OpenClawCompactionConfig()

        self.agents.defaults.compaction.mode = "safeguard"

        if max_gen_tokens > 0 and self.agents.defaults.compaction.reserveTokensFloor is None:
            # Layer 3 Enforcement: Compute reserve and clamp to MAX_RESERVE_RATIO
            # Formula: reserveTokens = maxTokens + HEADROOM (8192)
            # Reference: plans/token_budget_algorithm.md
            HEADROOM = 8192
            MAX_RESERVE_RATIO = 0.30

            reserve = max_gen_tokens + HEADROOM

            if min_context_window != float("inf"):
                max_safe_reserve = int(min_context_window * MAX_RESERVE_RATIO)
                if reserve > max_safe_reserve:
                    reserve = max_safe_reserve
                    # We don't warn here because Layer 2 (Schema) already handles
                    # individual model warnings. This is the global sync safety net.

            self.agents.defaults.compaction.reserveTokensFloor = reserve

        for m in provider.models:
            m_id = f"spark/{m.id}"
            if m_id not in self.agents.defaults.models:
                self.agents.defaults.models[m_id] = {}


class SparkProvider(BaseSchema):
    """Provider configuration for the self-hosted Spark LLM backend.

    timeout_seconds: The gateway's idle-timeout watchdog detects local providers
    by hostname pattern (localhost, *.local, private IPs), but Docker DNS names
    like ``litellm`` don't match, causing the 120s cloud default to apply.  A
    generous timeout is needed to survive long reasoning turns and event-loop
    pressure from concurrent plugin initialisation.
    """

    base_url: str = Field(
        default_factory=lambda: os.getenv(
            "VLLM_GATEWAY_URL",
            _default_litellm_base_url(),
        ),
        alias="baseUrl",
    )
    api_key: ApiKeyConfig | str = Field(default_factory=ApiKeyConfig)
    auth: str = "api-key"
    api: str | None = None

    @model_validator(mode="after")
    def _rewrite_base_url_for_remote(self) -> "SparkProvider":
        # Only rewrite when OpenClaw is on a *truly* remote node (not localhost/127.0.0.1).
        # When OPENCLAW_NODE_TARGET points to localhost the openclaw container is co-located on
        # Docker and can reach LiteLLM via Docker DNS ("litellm").  Rewriting to the Tailnet IP
        # breaks connectivity because the 100.64.0.0/10 subnet is only routable inside the
        # sidecar's network namespace, not from openclaw's Docker bridge.
        _target = OPENCLAW_NODE_TARGET or ""
        _is_local_target = not _target or "localhost" in _target or "127.0.0.1" in _target
        if (
            _target
            and not _is_local_target
            and (
                "localhost" in self.base_url
                or "litellm" in self.base_url
                or (WORKER_TAILNET_IP and WORKER_TAILNET_IP in self.base_url)
            )
        ):
            if not SPARKSTACK_HEAD_TAILNET_IP:
                warnings.warn(
                    "OPENCLAW_NODE_TARGET is set but SPARKSTACK_HEAD_TAILNET_IP is missing. "
                    f"The base_url '{self.base_url}' may not resolve from the remote node.",
                    stacklevel=2,
                )
            else:
                new_url = self.base_url.replace("localhost", SPARKSTACK_HEAD_TAILNET_IP).replace(
                    "litellm", SPARKSTACK_HEAD_TAILNET_IP
                )
                if WORKER_TAILNET_IP:
                    new_url = new_url.replace(WORKER_TAILNET_IP, SPARKSTACK_HEAD_TAILNET_IP)
                self.base_url = new_url
        return self

    timeout_seconds: int = 300
    request: RequestConfig = Field(default_factory=RequestConfig)
    models: list[OpenClawModel] = Field(default_factory=list)

    @model_validator(mode="after")
    def _ensure_api_key(self) -> "SparkProvider":
        if isinstance(self.api_key, str) and not self.api_key:
            self.api_key = ApiKeyConfig()
        return self


class ModelsConfig(PassThroughModel):
    """Schema for models.json"""

    spark: SparkProvider


class LiteLLMModelEntry(PassThroughModel):
    model_name: str
    litellm_params: dict[str, Any]
    model_info: dict[str, Any]


class LiteLLMConfig(PassThroughModel):
    """Schema for litellm-config.yaml"""

    model_list: list[LiteLLMModelEntry] = Field(default_factory=list)
    litellm_settings: dict[str, Any] = Field(default_factory=dict)
    general_settings: dict[str, Any] = Field(default_factory=dict)
    router_settings: dict[str, Any] = Field(default_factory=dict)


# --- Prometheus Models ---


class StaticConfig(PassThroughModel):
    targets: list[str]
    labels: dict[str, str] | None = None


class ScrapeConfig(PassThroughModel):
    job_name: str
    metrics_path: str | None = None
    params: dict[str, list[str]] | None = None
    static_configs: list[StaticConfig] | None = None
    file_sd_configs: list[dict[str, Any]] | None = None
    relabel_configs: list[dict[str, Any]] | None = None
    metric_relabel_configs: list[dict[str, Any]] | None = None


class PrometheusConfig(PassThroughModel):
    """Schema for prometheus.yml"""

    global_config: dict[str, str] = Field(
        default_factory=lambda: {"scrape_interval": "15s"}, serialization_alias="global"
    )
    scrape_configs: list[ScrapeConfig] = Field(default_factory=list)
