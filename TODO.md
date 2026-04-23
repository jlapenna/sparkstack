# Project TODO & Technical Debt

This file tracks unexpected behaviors, upstream bugs, and system-specific quirks discovered during stack management.

## vLLM / SparkRun Orchestration

*All Q1/Q2 2026 orchestration hardening items (Python-native log polling, Automated Context Window Sync, Dynamic Nightly Resolution, Memory Law Scaling, Sparkrun Recipe Refactoring, and eugr-vllm image migration) have been successfully completed and integrated into the `build_stack.py` pipeline.*

### Backlog / Monitoring

- Monitor SGLang upstream for a fix to the Mamba layers (`Pattern char 'M'`) issue to re-enable speculative decoding (`EAGLE3`) on Nemotron-3 Super.
- Monitor SGLang upstream for FlashInfer JIT memory allocation crashes on Blackwell to re-enable `--cuda-graph` and `--piecewise-cuda-graph`.
- Expand dynamic VRAM scaling in `build_stack.py` to auto-calculate required cache dimensions for non-SGLang runtimes if we pivot back to vLLM.

### Reasoning & Protocol Correctness (2026.04)

- **Standardized Thinking Formats**: Standardized the use of `thinking_format` in model recipes. Ensure all new reasoning-enabled models explicitly define `openai` or `qwen-chat-template` in `litellm_overrides` to avoid builder-side guessing and protocol mismatches (e.g., sending Qwen params to Gemma).
- **Zombie Protocol**: Integrated automated stuck-task and stale-container cleanup into the `update_services.py` lifecycle.
