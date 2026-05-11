# Host Setup Guide

This document outlines system-level configurations and tweaks necessary for setting up a new host for the `sparkstack` ecosystem. Because this project relies heavily on Docker and `docker-compose` routing, a vanilla Linux host configuration will experience networking conflicts and remote connection drops if not tuned properly.

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

# 2. Inject an explicit bypass rule at the absolute top of the system INPUT chain.
# IMPORTANT: Replace <YOUR_SSH_PORT> with your actual SSH port (e.g., 222, 8234). 
# If you use multiple ports, run this command for each port.
sudo iptables -I INPUT 1 -p tcp --dport <YOUR_SSH_PORT> -m state --state ESTABLISHED,RELATED -j ACCEPT

# 3. Save the live rule permanently so it survives server reboots
sudo netfilter-persistent save

# 4. Remove ufw
sudo apt-get purge -y ufw
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

When working with heavily nested projects, hot-reloading development tools, or extensive Docker bind mounts, you will likely exceed the default Linux file watcher limits (`inotify`). There are **two** limits that must be raised:

- **`max_user_watches`** (default: 65536): Total number of individual files/dirs that can be watched. Exhausting this causes `ENOSPC` ("No space left on device") errors.
- **`max_user_instances`** (default: 128-1024): Total number of inotify file descriptors a user can create. Exhausting this causes `EMFILE` ("Too many open files") errors, which crash VS Code Remote connections and prevent `accept()` on server sockets.

Both limits must be raised permanently:

```bash
# 1. Write both limits to a persistent sysctl profile
cat <<EOF | sudo tee /etc/sysctl.d/90-inotify.conf
fs.inotify.max_user_watches=524288
fs.inotify.max_user_instances=8192
EOF

# 2. Reload the sysctl settings to apply live
sudo sysctl -p /etc/sysctl.d/90-inotify.conf

# 3. Verify both values
cat /proc/sys/fs/inotify/max_user_watches    # Should show 524288
cat /proc/sys/fs/inotify/max_user_instances   # Should show 8192
```

> **Symptom:** If you see `accept: Too many open files` in VS Code trace logs and your remote connection keeps disconnecting, the `max_user_instances` limit is almost certainly exhausted. Kill any stale file-watching processes (`nx graph --watch`, orphaned `tsc --watch`, etc.) and apply the fix above.

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
