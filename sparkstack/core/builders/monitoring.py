import json
import os
from pathlib import Path

import jinja2
import yaml

from sparkstack.core.env import (
    REMOTE_PROMETHEUS_URL,
    REMOTE_TEMPO_URL,
    is_monitoring_external,
)
from sparkstack.core.schemas import PrometheusConfig, ScrapeConfig, StaticConfig


class MonitoringBuilder:
    def __init__(self, stack_dir: Path):
        self.stack_dir = stack_dir
        self.scrape_configs = [
            ScrapeConfig(
                job_name="vllm",
                metrics_path="/metrics",
                file_sd_configs=[{"files": ["/etc/prometheus/targets.json"]}],
            )
        ]
        self.scrape_targets = []

    def add_target(self, target: str, model_name: str, instance_name: str | None = None):
        labels = {"model": model_name}
        if instance_name:
            labels["instance"] = instance_name
        self.scrape_targets.append({"targets": [target], "labels": labels})

    def _template_dir(self) -> Path:
        return Path(__file__).parent.parent.parent.parent / "services" / "monitoring"

    def _write_alloy_config(self):
        """Generate the Alloy config from the appropriate template."""
        template_name = (
            "config.alloy.external.template"
            if is_monitoring_external()
            else "config.alloy.template"
        )
        template_path = self._template_dir() / template_name

        if not template_path.exists():
            return

        # Prepare monitor domains
        raw_domains = [
            d.strip() for d in os.getenv("SPARK_STACK_MONITOR_DOMAINS", "").split(",") if d.strip()
        ]
        monitor_domains = []
        for domain in raw_domains:
            if not domain.startswith("http"):
                domain = f"https://{domain}"
            monitor_domains.append(domain)

        variables: dict[str, str | list[str]] = {
            "monitor_domains": monitor_domains,
        }
        if is_monitoring_external():
            variables["REMOTE_PROMETHEUS_URL"] = REMOTE_PROMETHEUS_URL
            variables["REMOTE_TEMPO_URL"] = REMOTE_TEMPO_URL

        # Generate the Alloy config from the template using Jinja2
        alloy_content = jinja2.Template(template_path.read_text()).render(**variables)

        (self.stack_dir / "config.alloy").write_text(alloy_content)

    def write(self, preserve_targets: bool = False):
        base_configs = self.scrape_configs + [
            ScrapeConfig(
                job_name="litellm-gateway",
                metrics_path="/metrics",
                static_configs=[
                    StaticConfig(
                        targets=[
                            os.getenv(
                                "VLLM_GATEWAY_HOST",
                                f"{os.getenv('WORKER_TAILNET_IP', 'litellm')}:4000"
                            )
                        ],
                        labels={"instance": "spark"},
                    )
                ],
            ),
            ScrapeConfig(
                job_name="monitoring",
                static_configs=[
                    StaticConfig(
                        targets=[
                            os.getenv("ALLOY_HOST", "alloy:12345"),
                            os.getenv("NV_MONITOR_HOST", "nv-monitor:9101"),
                        ],
                        labels={"instance": "spark"},
                    )
                ],
                metric_relabel_configs=[
                    {
                        "source_labels": ["__name__"],
                        "regex": "DCGM_FI_DEV_XID_ERRORS",
                        "action": "drop",
                    }
                ],
            ),
        ]

        # Generate the Alloy config from the appropriate template
        self._write_alloy_config()

        config = PrometheusConfig(
            global_config={"scrape_interval": "15s"},
            scrape_configs=base_configs,
        )

        if not preserve_targets:
            targets = []
            for target in self.scrape_configs:
                static_cfgs = getattr(target, "static_configs", []) or []
                for static in static_cfgs:
                    targets.append({"targets": static.targets, "labels": static.labels})
            targets.extend(self.scrape_targets)
            with (self.stack_dir / "targets.json").open("w") as f:
                json.dump(targets, f, indent=2)

        # In external mode, skip prometheus.yml generation
        # since Prometheus won't be deployed locally.
        if is_monitoring_external():
            return

        with (self.stack_dir / "prometheus.yml").open("w") as f:
            yaml.dump(config.model_dump(by_alias=True, exclude_none=True), f, sort_keys=False)
