# Host Setup Guide

This document outlines system-level configurations and tweaks necessary for setting up a new host for the `spark-stack` ecosystem. Because this project relies heavily on Docker and `docker-compose` routing, a vanilla Linux host configuration will experience networking conflicts and remote connection drops if not tuned properly.

## 1. Protecting SSH Connections from Docker (VS Code Remote)

When the service orchestration scripts tear down or rebuild Docker bridge networks, Docker's `libnetwork` aggressively flushes `iptables` rules and connection tracking (`conntrack`). If you are connected via standard TCP (like an SSH session or VS Code Remote), this flush abruptly drops your active session state, triggering frozen terminals or "Reconnecting..." loops.

To immunize the host, you must manually instruct the Linux firewall to forcefully accept established SSH state, bypassing Docker's volatile chains.

### Why not UFW?

It is highly recommended **not** to use `ufw` (Uncomplicated Firewall) alongside heavy Docker host setups. `ufw` conflicts extensively with Docker logic. More dangerously, Docker explicitly injects rules into the `PREROUTING` chain, which completely bypasses `ufw` and exposes container ports to the public internet even if `ufw` says they are blocked.

Instead, standardize on `iptables-persistent`.

### The Fix

Run the following on your new host to completely protect remote connections:

```bash
# 1. Install iptables-persistent (this will also cleanly remove ufw if inactive)
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y iptables-persistent

# 2. Inject an explicit bypass rule at the absolute top of the system INPUT chain
sudo iptables -I INPUT 1 -p tcp --dport 22 -m state --state ESTABLISHED,RELATED -j ACCEPT

# 3. Save the live rule permanently so it survives server reboots
sudo netfilter-persistent save
```

This guarantees that VS Code or standard terminal sessions will survive infrastructure teardowns without dropping you.

## 2. Shield SSH and System Services via systemd

During extremely high memory-pressure events (like massive inference workloads triggering Linux Out-Of-Memory/OOM kills), the kernel may abruptly terminate the SSH daemon or remote connection handlers to free up RAM.

You can explicitly tell `systemd` to protect the SSH daemon so you never lose remote access, even during severe lockups. Systemd services have an `OOMScoreAdjust=` parameter that configures the kill priority (ranging from `-1000` for completely immune up to `1000` for primary target).

Run the following command:

```bash
sudo systemctl edit ssh.service
```

And add the drop-in override:

```ini
[Service]
OOMScoreAdjust=-1000
```

This ensures SSH remains completely immune. *(Note: Many modern distros already assign `sshd` a slight negative score for this reason, though a severe Out-Of-Memory cascade can still momentarily lock up the network stack until other services are killed).*

## 3. Environment Prerequisites

Ensure the following baseline tools are available on any fresh host:

- **Docker & Docker Compose V2**: For `openclaw` and `sparkrun` deployment.
- **uv**: Modern, ultra-fast Python package installer and runner. We use `uv run` to execute scripts in strict, reproducible environments.
- **tmux**: Essential for persisting local terminal sessions or testing orchestration commands locally.

### Python Environment (uv)

To ensure `uv` commands correctly find local modules and load project settings, add the following to your shell profile (`~/.bashrc` or `~/.zshrc`):

```bash
# Tell uv to automatically load the .env file in the current directory
export UV_ENV_FILE=.env
```

The project's `.env` file includes `PYTHONPATH=.`, which allows running scripts from the root without manual path prefixing.

## 4. Remote CLI Setup & Authentication

When authenticating with local CLIs in a remote or headless environment (e.g., connected over SSH), standard browser-based OAuth flows will fail entirely or hang.

### Spark Arena Leaderboard

If you need to authenticate with the Spark Arena to submit benchmarks from a remote host, you must force the OAuth 2.0 Device Code flow. This will provide a manual URL and code for you to enter on your local machine's web browser:

```bash
uv run sparkrun arena login --device
```

## 5. Increasing File Watcher Limits (Inotify)

When working with heavily nested projects, hot-reloading development tools, or extensive Docker bind mounts, you will likely exceed the default Linux file watcher limits (`inotify`). Exhausting these limits results in elusive "No space left on device" (ENOSPC) errors when tools attempt to initialize file tracking.

To fix this and permanently double the threshold on the workstation:

```bash
# 1. Write the new maximum watch limit to a persistent sysctl profile
echo "fs.inotify.max_user_watches=524288" | sudo tee /etc/sysctl.d/90-inotify.conf

# 2. Reload the sysctl settings to apply the new limit live
sudo sysctl -p /etc/sysctl.d/90-inotify.conf

# 3. Verify the updated configuration
cat /proc/sys/fs/inotify/max_user_watches
```

## 6. Maintenance and the "Zombie Protocol"

The service orchestration scripts (`update_services.py` and `update_openclaw.py`) include a specialized cleanup phase known as the **Zombie Protocol**. This is designed to prevent system hangs and session locks caused by ungraceful shutdowns or protocol mismatches.

### What it does:

1. **Stuck Task Clearing**: Automatically scans the OpenClaw task database (`~/.openclaw/tasks/runs.sqlite`) and resets any tasks stuck in the "running" state to "failed". This prevents session locks in Telegram and other channels.
1. **Container Pruning**: Runs `docker container prune` and `docker network prune` to remove orphaned resources that may cause port collisions.
1. **Telemetry Cache Flush**: Restarts the Alloy telemetry collector to flush stale caches and ensure clean metric ingestion for the new stack.

### When it runs:

The protocol executes automatically at the start of any `update_services.py` run or during the `OpenClawUpdater` lifecycle. You can manually trigger it by running:

```bash
uv run manager/update_services.py
```
