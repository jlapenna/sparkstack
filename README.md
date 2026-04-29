# Spark Services Orchestrator

This repository serves as the primary deployment orchestrator for the Spark ecosystem, managing the `openclaw` backend, `sparkrun` orchestrator, and various local LLM (vLLM) backend stacks.

## Architecture

The ecosystem relies on Docker and Docker Compose to network different services together safely:

- **vLLM Inference Stacks**: Dynamic backend model deployment scripts.
- **OpenClaw Gateway**: API router and backend proxy logic.
- **SparkRun**: Automated orchestration.
- **Cloudflare Tunnels**: Exposes internal ports securely to the web.
- **Monitoring**: Prometheus and Grafana dashboards.

> **Note**: This repository is designed to be a deployment orchestrator. It manages `openclaw` and `sparkrun` as source dependencies in `../`. You will need access to those repositories to fully initialize this project, or you must configure it to point to public images.

## Prerequisites

- **Linux Host** (Ubuntu / Debian recommended)
- **Docker & Docker Compose V2**
- **uv** (Python package installer and runner)
- **tmux** (for detached background process management)

## Getting Started

1. **Clone the repository:**

   ```bash
   git clone https://github.com/jlapenna/spark-stack.git
   cd spark-stack
   ```

1. **Clone source dependencies (if you have access):**

   Ensure `openclaw`, `sparkrun`, and `spark-stack-registry` are cloned in the parent directory (`../`).

1. **Configure Environment:**
   Copy `.env.example` to `.env` and fill in the appropriate values.

   ```bash
   cp .env.example .env
   ```

1. **Launch the Service Stack:**
   You can use the built-in python scripts (via `uv`) to orchestrate and update the deployment:

   ```bash
   uv run manager/update_services.py
   ```

## Development and Host Tuning

See [DEVELOPMENT.md](DEVELOPMENT.md) for critical host-level tuning to ensure Docker does not conflict with SSH, and that `inotify` limits are high enough for hot-reloading development.

## Contributing

Please refer to [DEVELOPMENT.md](DEVELOPMENT.md) for setup and development guidelines, and [AGENTS.md](AGENTS.md) for contribution protocols.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
