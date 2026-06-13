# vLLM Deployment Gotchas

Cross-model lessons learned from production deployments on Blackwell. **Read this before configuring any new vLLM stack.**

## Flag Incompatibilities

### `--disable-log-stats` + OTel Tracing → CRASH

> [!CAUTION]
> **Never use `--disable-log-stats` when `--otlp-traces-endpoint` is set.**

When `--disable-log-stats` is active, vLLM creates `RequestState` with `stats = None`. But OTel tracing's `do_tracing()` (in `output_processor.py`) asserts `req_state.stats is not None`. This causes an `AssertionError` on the **first completed inference request**.

**Symptoms**: Server starts, reports healthy, loads model fully, but crashes instantly when you send the first real request. Extremely misleading because health checks pass.

**Since our `build_stack.py` auto-injects `--otlp-traces-endpoint` into every backend, `--disable-log-stats` must NEVER appear in any model recipe.**

### `--enforce-eager` for Hybrid Architectures on Blackwell

Hybrid Mamba/Transformer models (Nemotron-H, Jamba, etc.) **require** `--enforce-eager` on Blackwell GPUs. Without it, the Triton JIT compiler crashes during CUDA graph capture of the Mamba mixer2 `selective_state_update` kernel:

```
RuntimeError: Triton Error [CUDA]: an illegal memory access was encountered
```

**Symptoms**: Model loads weights successfully (72GB+ consumed), then crashes during the "Capturing CUDA graphs" or "Compiling" phase — wasting 7+ minutes per attempt.

**Rule**: If the model architecture contains Mamba layers, always add `--enforce-eager`.

## Speculative Decoding

### Draft Model Compatibility

Before using a draft model for speculative decoding:

1. **Verify architecture class match** — draft and target must use the same architecture (e.g., both `NemotronHForCausalLM`). Different-size models of the same family may NOT be compatible if QKV projection dimensions differ.
1. **Check for `pard_token` / `ptd_token_id`** in the draft model's `config.json` — required for `parallel_drafting: true`.
1. **Test weight loading** before committing to a full deploy.

### Safe Fallback: `[ngram]`

When in doubt, use `ngram` speculative decoding:

```
--speculative-config '{"model":"[ngram]","num_speculative_tokens":5}'
```

This requires no external draft model, works with any architecture, and provides modest throughput improvement. Note: ngram disables async scheduling (`WARNING: Async scheduling not supported with ngram-based speculative decoding`).

## Observability Pipeline

### StatsD Transport

The progress manager and orchestration scripts send metrics via **UDP** StatsD to Alloy on port 8125. Key points:

- **Must use UDP**, not TCP. Alloy's `prometheus.exporter.statsd` may bind TCP to IPv6 only, causing IPv4 TCP connections to hang silently.
- The metric name is `vllm_model_load_progress` with tags: `name` (container), `model_id`, `host`.
- The push interval is 10 seconds from the progress manager's `push_worker`.

### Health Check Limitations

The progress manager's readiness check only verifies `/v1/models` responds with HTTP 200. This does **not** guarantee the model can actually serve inference. A model that passes health checks may still crash on the first real request (see `--disable-log-stats` above).

### Smoke Test Routing (Embeddings vs Completions)

When orchestrating or verifying backend readiness (e.g., via `wait_for_backends.py`), be aware that different model architectures require different endpoints:

- **Completion/Chat Models (e.g., Nemotron, Llama)**: Respond to `/v1/chat/completions`.
- **Embedding Models (e.g., BGE-M3)**: Respond to `/v1/embeddings` and will return `HTTP 404` if queried at the chat endpoint.

If your readiness smoke-tests fail with `404 Not Found` against an embedding model, ensure the diagnostic payload is correctly formatted and routed to `/v1/embeddings` instead.

## Container Lifecycle

- `update_services.py` auto-removes stale containers (`docker rm -f`) for `litellm` and `main_solo` during deploys.
- The progress manager must be rebuilt (`docker compose up --build vllm-progress-manager`) after code changes — it copies `model_progress_manager.py` into the image at build time.
