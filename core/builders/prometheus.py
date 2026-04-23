import json
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
        config = PrometheusConfig(
            global_config={"scrape_interval": "15s"},
            scrape_configs=self.scrape_configs
            + [
                ScrapeConfig(
                    job_name="litellm-gateway",
                    metrics_path="/metrics",
                    static_configs=[
                        StaticConfig(
                            targets=["vllm-gateway:4000"], labels={"instance": "spark.local"}
                        )
                    ],
                ),
                ScrapeConfig(
                    job_name="monitoring",
                    static_configs=[
                        StaticConfig(
                            targets=[
                                "cadvisor:8080",
                                "node-exporter:9100",
                                "dcgm-exporter:9400",
                                "vector:9102",
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
                ScrapeConfig(
                    job_name="home_local",
                    file_sd_configs=[{"files": ["/prometheus/home_local.json"]}],
                    relabel_configs=[{"target_label": "instance", "replacement": "home.local"}],
                ),
                ScrapeConfig(
                    job_name="blackbox",
                    metrics_path="/probe",
                    params={"module": ["http_2xx"]},
                    static_configs=[
                        StaticConfig(targets=["https://c.jlapenna.net", "https://m.jlapenna.net"])
                    ],
                    relabel_configs=[
                        {
                            "source_labels": ["__address__"],
                            "target_label": "__param_target",
                        },
                        {
                            "source_labels": ["__param_target"],
                            "target_label": "instance",
                        },
                        {
                            "target_label": "__address__",
                            "replacement": "blackbox-exporter:9115",
                        },
                    ],
                ),
            ],
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
