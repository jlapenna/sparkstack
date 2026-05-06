import json
import os
from pathlib import Path

import yaml

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

    def write(self):
        base_configs = self.scrape_configs + [
            ScrapeConfig(
                job_name="litellm-gateway",
                metrics_path="/metrics",
                static_configs=[
                    StaticConfig(
                        targets=[os.getenv("VLLM_GATEWAY_HOST", "litellm:4000")],
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

        monitor_domains = [
            d.strip() for d in os.getenv("SPARK_STACK_MONITOR_DOMAINS", "").split(",") if d.strip()
        ]

        # Generate config.alloy from template
        alloy_template_path = (
            Path(__file__).parent.parent.parent.parent / "services" / "monitoring" / "config.alloy.template"
        )
        if alloy_template_path.exists():
            with open(alloy_template_path) as f:
                alloy_content = f.read()

            target_blocks = []
            for domain in monitor_domains:
                if not domain.startswith("http"):
                    domain = f"https://{domain}"
                target_blocks.append(f"""  target {{
    name    = "{domain}"
    address = "{domain}"
    module  = "http_2xx"
  }}""")

            alloy_content = alloy_content.replace(
                "{{ BLACKBOX_TARGETS }}", "\n".join(target_blocks)
            )
            with (self.stack_dir / "config.alloy").open("w") as f:
                f.write(alloy_content)

        config = PrometheusConfig(
            global_config={"scrape_interval": "15s"},
            scrape_configs=base_configs,
        )

        targets = []
        for target in self.scrape_configs:
            static_cfgs = getattr(target, "static_configs", []) or []
            for static in static_cfgs:
                targets.append({"targets": static.targets, "labels": static.labels})
        targets.extend(self.scrape_targets)
        with (self.stack_dir / "targets.json").open("w") as f:
            json.dump(targets, f, indent=2)

        with (self.stack_dir / "prometheus.yml").open("w") as f:
            yaml.dump(config.model_dump(by_alias=True, exclude_none=True), f, sort_keys=False)
