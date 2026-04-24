import json
import os
from pathlib import Path

import yaml

from core.schemas import PrometheusConfig, ScrapeConfig, StaticConfig


class PrometheusBuilder:
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

    def add_target(self, target: str, model_name: str):
        self.scrape_targets.append({"targets": [target], "labels": {"model": model_name}})

    def write(self):
        base_configs = self.scrape_configs + [
            ScrapeConfig(
                job_name="litellm-gateway",
                metrics_path="/metrics",
                static_configs=[
                    StaticConfig(
                        targets=[os.getenv("VLLM_GATEWAY_HOST", "vllm-gateway:4000")],
                        labels={"instance": "spark.local"},
                    )
                ],
            ),
            ScrapeConfig(
                job_name="monitoring",
                static_configs=[
                    StaticConfig(
                        targets=[
                            os.getenv("CADVISOR_HOST", "cadvisor:8080"),
                            os.getenv("NODE_EXPORTER_HOST", "node-exporter:9100"),
                            os.getenv("DCGM_EXPORTER_HOST", "dcgm-exporter:9400"),
                            os.getenv("VECTOR_HOST", "vector:9102"),
                        ],
                        labels={"instance": "spark.local"},
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
        if monitor_domains:
            base_configs.append(
                ScrapeConfig(
                    job_name="blackbox",
                    metrics_path="/probe",
                    params={"module": ["http_2xx"]},
                    static_configs=[StaticConfig(targets=monitor_domains)],
                    relabel_configs=[
                        {"source_labels": ["__address__"], "target_label": "__param_target"},
                        {"source_labels": ["__param_target"], "target_label": "instance"},
                        {
                            "target_label": "__address__",
                            "replacement": os.getenv(
                                "BLACKBOX_EXPORTER_HOST", "blackbox-exporter:9115"
                            ),
                        },
                    ],
                )
            )

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
