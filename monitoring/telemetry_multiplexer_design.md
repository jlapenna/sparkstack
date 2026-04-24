title:	Design Proposal: Multi-Node Telemetry Architecture for SparkRun
state:	OPEN
author:	jlapenna (Joe LaPenna)
labels:	enhancement
comments:	0
assignees:	
projects:	
milestone:	
number:	2
--
# Design Document: Multi-Node Telemetry Architecture for SparkRun

## 1. Objective
Enable real-time, distributed deployment and status telemetry across DGX Spark clusters orchestrated by `sparkrun`. The telemetry must provide deep observability into the lifecycle of model loading, cluster provisioning, and orchestration progress without compromising the agentless, secure nature of the `sparkrun` framework.

## 2. Requirements

### 2.1 Functional Requirements
- **FR1:** `sparkrun` orchestrator clients must be able to transmit "phase" and "step" metrics (e.g., Progress %) to a central telemetry collector (Vector/Prometheus).
- **FR2:** Worker nodes executing distributed tasks (via bash scripts piped over SSH) must be able to push runtime metrics back to the central telemetry collector.
- **FR3:** Metrics must support the StatsD format (for gauges, counters, timers).
- **FR4:** The telemetry system must seamlessly map container and model identities (e.g., `#model_id`, `#node_id`).

### 2.2 Non-Functional Requirements
- **NFR1 (Agentless):** No persistent daemon installations (like Vector, Telegraf, or Promtail) are permitted on worker compute nodes.
- **NFR2 (Secure):** Telemetry ports (e.g., StatsD UDP/TCP 8125) must **not** be exposed over the public internet or open host firewalls.
- **NFR3 (Network Agnostic):** Worker scripts must not rely on discovering the dynamic, routable IP address of the head node.
- **NFR4 (Ephemeral State):** Metrics should not permanently "stick" in a stale state if a job crashes mid-flight.

---

## 3. Proposed Design: Centralized Fleet Telemetry via SSH Forward Tunnels

To maintain strict alignment with `sparkrun`'s agentless philosophy, telemetry will be orchestrated using a centralized **Fleet Multiplexer** combined with **SSH Local Port Forwarding**. 

Instead of running a sidecar container on the worker node to push metrics back, the head node will securely pull logs from the remote worker's Docker daemon. When `sparkrun` initiates an execution on a worker node, it establishes an SSH forward tunnel (`-L <random_port>:/var/run/docker.sock`), exposing the worker's Docker API locally on the head node. `sparkrun` then registers this local port with the centralized `vllm-progress-manager` Fleet Multiplexer.

### 3.1 Architecture Diagram

```mermaid
flowchart LR
    subgraph HeadNode ["Head Node"]
        Vector[Vector Aggregator\n:8125] --> Prom[Prometheus]
        Prom --> Grafana[Grafana Dashboards]
        
        Multiplexer[Fleet Multiplexer\nvllm-progress-manager]
        Multiplexer --> |TCP :8125| Vector
        
        subgraph Orchestrator ["SparkRun Orchestrator (Client/Runner)"]
            CLI[sparkrun CLI]
            StatsDClient_CLI[StatsD Client]
            CLI --> |State Updates| StatsDClient_CLI
            StatsDClient_CLI -.-> |TCP :8125| Vector
            CLI --> |Registers Port| Multiplexer
        end
    end

    subgraph Worker1 ["Worker Node 1"]
        DockerSocket1[/var/run/docker.sock]
    end

    subgraph WorkerN ["Worker Node N"]
        DockerSocketN[/var/run/docker.sock]
    end

    Multiplexer == "Polls via ssh -L 8001:/var/run/docker.sock" ==> DockerSocket1
    Multiplexer == "Polls via ssh -L 8002:/var/run/docker.sock" ==> DockerSocketN
```

### 3.2 Execution Flow
1. **Connection Initialization:** When `sparkrun` connects to a remote host, it appends the flag `-L <random_port>:/var/run/docker.sock` to the SSH command.
2. **Registration:** `sparkrun` makes a REST call to the head node's `vllm-progress-manager` (the Fleet Multiplexer) to register the newly established local port mapped to the worker.
3. **Remote Polling:** The Fleet Multiplexer instantiates an isolated `DockerHostMonitor` task. This task connects to the forwarded local port, querying the worker's Docker API to parse logs and track phase progressions for containers labelled `sparkrun.monitoring=true`.
4. **Local Pushing:** The Fleet Multiplexer pushes parsed metrics to its local Vector ingestion port (`127.0.0.1:8125`), tagging the metrics with the appropriate `host` and `model_id`.
5. **Clean Teardown:** Once the bash script finishes, `sparkrun` unregisters the worker from the Multiplexer. The SSH connection closes, instantly tearing down the socket tunnel and preventing any lingering external access to the worker's Docker daemon.

---

## 4. Rejected Alternatives

### 4.1 Option 2: Distributed Vector/Telegraf Daemons
**Design:** Deploy a lightweight `vector` daemon on every worker node in the cluster. Workers push to `localhost:8125`, and the local daemon forwards the metrics to the head node.
**Why it was rejected:**
- **Violates NFR1 (Agentless):** `sparkrun` is designed to orchestrate raw nodes. Forcing a DaemonSet installation creates heavy prerequisite requirements for compute nodes.
- **Lifecycle Management:** Requires handling daemon upgrades, configuration drift, and crash loop backoffs on workers.

### 4.2 Option 3: Centralized Prometheus Pushgateway
**Design:** Expose an HTTP Prometheus Pushgateway on the head node (`http://head-node-ip:9091`). Worker scripts use `curl` to push metrics.
**Why it was rejected:**
- **Violates NFR3 (Network Agnostic):** Worker nodes in DGX clusters often have complex topologies (InfiniBand vs. Management interfaces). Dynamically injecting a guaranteed-routable IP into the script is highly brittle.
- **Violates NFR4 (Ephemeral State):** Pushgateway never expires metrics. If a `sparkrun` job crashes before sending an HTTP `DELETE`, the dashboard will be permanently polluted with stale "50% loaded" metrics.
- **Violates NFR2 (Secure):** Requires opening an unauthenticated HTTP port on the head node's firewall.
- **Performance Risk:** HTTP handshakes block the execution script. If the Pushgateway is slow, the actual deployment pipeline is artificially delayed.


### 3.3 Implementation Details

The `sparkrun` orchestrator will wrap its deployment logic using a context manager (`TelemetryTunnel`) to safely negotiate port selection, establish the `-L` forward tunnel in the background, register the endpoint via REST, and tear it all down deterministically upon exit:

```python
import socket
import subprocess
import time
import urllib.request
import json

class TelemetryTunnel:
    """Context manager to establish a forward tunnel for remote Docker telemetry."""

    def __init__(self, host: str, ssh_user: str | None = None, ssh_key: str | None = None, ssh_options: list[str] | None = None):
        self.host = host
        self.ssh_user = ssh_user
        self.ssh_key = ssh_key
        self.ssh_options = ssh_options
        self.local_port: int | None = None
        self.tunnel_proc: subprocess.Popen | None = None

    def __enter__(self):
        # 1. Find an open ephemeral port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            self.local_port = s.getsockname()[1]

        # 2. Start SSH forward tunnel: ssh -f -N -L local_port:/var/run/docker.sock host
        cmd = build_ssh_cmd(self.host, self.ssh_user, self.ssh_key, self.ssh_options)
        cmd.extend(["-N", "-L", f"{self.local_port}:/var/run/docker.sock"])
        self.tunnel_proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1)

        # 3. Register with Fleet Multiplexer API
        req = urllib.request.Request("http://127.0.0.1:8126/api/nodes", method="POST")
        req.add_header("Content-Type", "application/json")
        data = json.dumps({"host_id": self.host, "docker_url": f"tcp://127.0.0.1:{self.local_port}"}).encode()
        try:
            urllib.request.urlopen(req, data=data, timeout=2.0)
        except Exception:
            pass

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # 1. Deregister from Fleet Multiplexer
        req = urllib.request.Request(f"http://127.0.0.1:8126/api/nodes/{self.host}", method="DELETE")
        try:
            urllib.request.urlopen(req, timeout=2.0)
        except Exception:
            pass

        # 2. Kill the SSH tunnel
        if self.tunnel_proc:
            self.tunnel_proc.terminate()
            try:
                self.tunnel_proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.tunnel_proc.kill()
```
