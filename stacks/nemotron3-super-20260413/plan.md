# Model Addition / Upgrade Plan

**Objective**: Deploy NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4 with max sequences 512
**Target Date**: 2026-04-13
**Target Stack Name**: `nemotron-upgrade-20260413`

______________________________________________________________________

## 0. Quirk Invalidation (MANDATORY PRE-FLIGHT)

- **Quirk Investigated**: Mamba cache blocks exhaustion on NM3.
- **Web Research Summary**: Nemotron requires TRITON_ATTN. Also requires 1 mamba cache block per sequence. Increasing max seqs limits to 512 without sufficient VRAM crashes CUDA initialization.
- **Invalidation Test**: Set max_num_seqs 512 on 0.7 VRAM.
- **Result**: Crash verified due to max sequence overstep (175 cache blocks max).
- **Action Taken**: Increased GPU Memory utilization to 0.86 to facilitate the KV cache blocks required for 512 sequences.

______________________________________________________________________

## 1. Hardware & Resource Budget (Verification of Constraints)

- **Current Main Model (`nemotron-3-super-nvfp4-vllm`)**: 86% VRAM | 100GB RAM
- **Other Models (`bge-m3`)**: 5% VRAM | 4GB RAM
- **Aggregate Totals**: **91% VRAM** | **104GB RAM** (Passes limits of 108GB RAM and 95% VRAM)

______________________________________________________________________

## 2. Detailed Implementation Phases

### Phase 1: Model Registration (Registry Layer)

Updated `registry/models/nemotron-3-super-nvfp4-vllm.yaml`
`max_num_seqs: 512`
`gpu_memory_utilization: 0.86`

### Phase 2: Infrastructure Patching (Tooling Layer)

Fixed Docker-out-of-Docker `$HOME` pathing paradox in `.env`
Added telemetry `asyncio` polling to layer 6 script.

### Phase 3: Stack Orchestration

```bash
uv run python -m scripts.build_stack nemotron-upgrade-20260413-01 main=nemotron-3-super-nvfp4-vllm embedding=bge-m3
```

______________________________________________________________________

## 3. Mandatory E2E Verification Suite

- **Action**: `uv run python -m scripts.verify --stack nemotron-upgrade-20260413-01`
- **Result**: ✅ ALL verification stages passed.

______________________________________________________________________

## 4. Formal Benchmarking

- **Action**: Run `uvx llama-benchy --base-url http://127.0.0.1:8001/v1 --model main --depth 0 --pp 2048 --concurrency 1` (via llama-benchy)

- **Baseline Capture**:

  - **Throughput (Tokens/s)**: TG32 = 15.34 T/s, PP2048 = 1616.49 T/s
  - **TTFT (ms)**: 1146.79 ms
  - **Success Rate**: 100%

______________________________________________________________________

## 6. Mandatory Proof of Execution (Receipts)

STDOUT VERIFICATION RECORD:

```text
Bytecode compiled 1 file in 833ms

🔍 STARTING END-TO-END STACK VERIFICATION: nemotron-upgrade-20260413-01
==================================================
=== Layer 0: Hardware Constraint Verification ===
🔍 Checking Memory Law compliance...
   - RAM Ceiling: 120.0GB
   - VRAM Utilization Ceiling: 95.0% of 121.0GB

==================================================
Docker Container               RAM Usage      
--------------------------------------------------
vllm-gateway                         0.82 GB
embedding_solo                       2.17 GB
main_solo                            2.46 GB
openclaw-openclaw-gateway-1          0.95 GB
openclaw-sbx-agent-jclaw-d5a33f7e       0.00 GB
prometheus                           0.13 GB
openclaw-sbx-agent-main-f331f052       0.00 GB
blackbox-exporter                    0.02 GB
cloudflared                          0.02 GB
vllm-progress-manager                0.07 GB
cadvisor                             0.04 GB
grafana                              0.10 GB
node-exporter                        0.01 GB
vector                               0.02 GB
dcgm-exporter                        0.10 GB
--------------------------------------------------
TOTAL RAM AGGREGATE                  6.91 GB

==================================================
Active Recipe                  VRAM Est.      
--------------------------------------------------
--------------------------------------------------
TOTAL VRAM AGGREGATE                 0.00 GB
==================================================

✅ Memory Law compliant across both RAM and VRAM dimensions.
✅ Pass: Physics validation (RAM/VRAM boundaries honored)
=== Layer 1: Backend Pulse (Liveness & Loading Progress) ===
Waiting for 2 backend containers to be fully loaded...
Loading embedding_solo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100%
Loading main_solo      ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100%
✅ Pass: Backend Pulse (All models loaded)
=== Layer 2: Proxy Integrity (Routing) ===
Routed Models: main, embedding
✅ Pass: Proxy Integrity
=== Layer 3: Functional Verification (Embeddings) ===
✅ Pass: Embedding endpoint reachable (dimension: 1024)
=== Layer 4: OpenClaw System Diagnosis ===
Configured Spark models: spark/main, spark/embedding
✅ Pass: OpenClaw System Diagnosis
=== Layer 5: Consumer Readiness (End-to-End) ===
✅ Pass: Consumer Readiness (Verified agent turnaround and reasoning)
=== Layer 6: Telemetry Verification ===
✅ Pass: Telemetry Verification
=== Layer 8: Regression Testing (Anti-Repetition) ===
✅ Pass: Anti-Repetition Regression Test (Output is natural)
=== Layer 9: Tool Calling Verification ===
✅ Pass: Tool Calling Verification (Agent successfully executed and returned tool output)
=== Layer 10: Outbound Network Integrity (Internet Egress) ===
✅ Pass: Outbound Network Integrity (Agent successfully egressed to internet)
=== Layer 11: File System Integrity (Workspace IO) ===
✅ Pass: File System Integrity (Agent successfully executed workspace I/O)
=== Layer 7: Reliability Soak Test ===
Beginning 2-minute soak. Polling every 15s...
✅ Pass: Reliability Soak (2 minutes stable)
==================================================
✨ ALL E2E VERIFICATION LAYERS PASSED
Exit code: 0
```

STDOUT BENCHMARK RECORD:

```text
llama-benchy (0.3.5)
Date: 2026-04-13 11:51:12
Benchmarking model: main at http://127.0.0.1:8001/v1
Concurrency levels: [1]
Loading text from cache: /home/jlapenna/.cache/llama-benchy/cc6a0b5782734ee3b9069aa3b64cc62c.txt
Total tokens available in text corpus: 159385
Warming up...
Warmup (User only) complete. Delta: 16 tokens (Server: 38, Local: 22)
Warmup (System+Empty) complete. Delta: 16 tokens (Server: 38, Local: 22)

Running coherence test...
Coherence test PASSED.
Measuring latency using mode: api...
Average latency (api): 3.03 ms
Running test: pp=2048, tg=32, depth=0, concurrency=1
  Run 1/3 (batch size 1)...
  Run 2/3 (batch size 1)...
  Run 3/3 (batch size 1)...
Printing results in MD format:



| model   |   test |             t/s |     peak t/s |       ttfr (ms) |    est_ppt (ms) |   e2e_ttft (ms) |
|:--------|-------:|----------------:|-------------:|----------------:|----------------:|----------------:|
| main    | pp2048 | 1616.49 ± 25.49 |              | 1146.68 ± 17.54 | 1143.66 ± 17.54 | 1146.79 ± 17.54 |
| main    |   tg32 |    15.34 ± 0.08 | 16.00 ± 0.00 |                 |                 |                 |

Exit code: 0
```
