# Stack Manager Task Checklist

- [x] Phase 0: Quirk Invalidation
- [x] Phase 1: Model Registration (Registry Layer)
- [x] Phase 2: Infrastructure Patching (Tooling Layer)
- [x] Phase 3: Stack Orchestration (Building Layer)
- [x] Phase 4: Activation & Synchronization (Deployment Layer)
- [x] Phase 5: OpenClaw / Application Configuration
- [x] Phase 6: Mandatory Proof of Execution (Receipts)
- [x] Phase 7: Finalization (Cleanup)

## Phase 6 Receipts
VRAM Estimation:
- `cascade2-30b-nvfp4-vllm`: 84.70 GB
- `bge-m3`: 6.05 GB
Total VRAM Aggregate: 90.75 GB (Under 108GB limit)
Total RAM Aggregate: 10.97 GB (Under 120GB limit)
Note: Benchmark for embedding model skipped as `llama-benchy` does not support embedding endpoints.
