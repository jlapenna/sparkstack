# sparkstack (retired)

sparkstack was the CLI and Docker Compose control plane that built, launched
and monitored a local AI service stack (OpenClaw, LiteLLM, vLLM backends and a
Prometheus, Grafana and Tempo monitoring stack) from `sparkstack-registry`
recipes on DGX Spark hosts.

It was retired on 2026-10-19 and the repository is archived. Its ownership
moved elsewhere in September 2026: `jlapenna/homelab` took the gateway and
monitoring, and `sparkstack-registry` took the serving lanes, then removed the
`stacks/` directory this CLI orchestrates, so most commands no longer have
anything to run against.

## Where the work lives now

- Serving lanes and recipes:
  [`jlapenna/sparkstack-registry` `docs/deployment.md`](https://github.com/jlapenna/sparkstack-registry/blob/main/docs/deployment.md)
- LiteLLM gateway, monitoring and hosts:
  [`jlapenna/homelab` `docs/spark-model-serving.md`](https://github.com/jlapenna/homelab/blob/main/docs/spark-model-serving.md)

The code is left in place for reference and its full history stays in git. It
is not maintained: do not build or launch stacks from it. The `sparkrun` uv
workspace sibling (`jlapenna/sparkrun`) has been deleted, so `uv sync` in a
fresh checkout no longer resolves.
