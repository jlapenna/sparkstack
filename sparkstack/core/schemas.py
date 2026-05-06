"""
Pydantic models for service configurations.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


@dataclass
class ModelRequest:
    """A parsed model request with role, recipe identity, and optional overrides."""

    role: str | None
    recipe: str
    overrides: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_cli_arg(cls, arg: str) -> "ModelRequest":
        """Parse the ``role=recipe:k=v,k=v`` CLI shorthand."""
        overrides: dict[str, str] = {}
        if ":" in arg:
            arg, overrides_str = arg.split(":", 1)
            for item in overrides_str.split(","):
                if "=" in item:
                    k, v = item.split("=", 1)
                    overrides[k] = v
        if "=" in arg:
            role, recipe = arg.split("=", 1)
            return cls(role=role, recipe=recipe, overrides=overrides)
        return cls(role=None, recipe=arg, overrides=overrides)


class ServiceStatus(Enum):
    WAITING = "waiting"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


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
    """

    id: str
    name: str
    context_window: int
    max_tokens: int
    input: list[Literal["text", "image"]] = Field(default_factory=lambda: ["text"])
    reasoning: bool = False
    api: str = "openai-responses"
    cost: OpenClawModelCost = Field(default_factory=OpenClawModelCost)
    compat: OpenClawModelCompat | None = None


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


class SparkProvider(BaseSchema):
    base_url: str = "http://spark.local:4000/v1"
    api_key: str = ""
    auth: str = "api-key"
    api: str = "openai-responses"
    models: list[OpenClawModel] = Field(default_factory=list)


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
