"""
Pydantic models for service configurations.
"""

from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


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
    supports_tools: bool = True
    thinking_format: str | None = None
    supports_developer_role: bool = True


class OpenClawModel(BaseSchema):
    id: str
    name: str
    context_window: int = 32768
    max_tokens: int = 32768
    input: list[Literal["text", "image"]] = Field(default_factory=lambda: ["text"])
    reasoning: bool | None = None
    api: str = "openai-completions"
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
    api: str = "openai-completions"
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
