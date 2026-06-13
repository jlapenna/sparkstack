---

name: model-recommender
description: Specialized discovery, research, and configuration of frontier LLMs for NVIDIA Spark (GB10 Blackwell) using Spark Arena and internet sources.
category: infrastructure
risk: low
source: local
compatibility: claude-code
triggers:

- find new spark models
- recommend a model for spark
- check model VRAM fit
- identify frontier models
- what is the best model for spark
- recommend models
- are there any new models that I should consider trying
- recommend a new model

---

# model-recommender

## Purpose

To identify and evaluate frontier LLMs specifically for the **NVIDIA Spark (GB10 Blackwell)** workstation.

This skill makes you a pure **Research, Discovery, and Configuration Engine**. Your job is to hunt down the best new models on the internet, figure out their quirks, and formulate the ideal configurations and recipes for them. **You MUST activate and utilize the guidelines in this skill whenever the user asks for model recommendations or asks if there are new models to try.**

> [!WARNING]
> Once you have utilized this skill to identify the optimal model, formulated its configuration, and statically verified its VRAM math, you **MUST STOP**. Defer strictly to the `stack-manager` or `stack-verification` skills for all local deployment, container management, and live benchmarking workflows.

## Discovery Sources

When discovering new models, utilize your `search_web` capabilities across the following primary sources:

1. **Spark Arena**: [spark-arena.com](https://spark-arena.com/) - A valuable community leaderboard and repository for Blackwell-native performance metrics and deployment recipes. Check here alongside other hubs.
1. **HuggingFace & Model Hubs**: Search for newly trending models, NVFP4 checkpoints, or fine-tunes that fit the user's specific use case. Read the model cards closely.
1. **Community Pulse**: Search the **NVIDIA Developer Forums** (e.g. [Running a full LLM stack on DGX Spark GB10](https://forums.developer.nvidia.com/t/running-a-full-llm-stack-on-dgx-spark-gb10-your-application-litellm-llama-swap-vllm-llama-cpp-ollama/367580/9)), Reddit (e.g., r/LocalLLaMA), or Twitter for discussions on the latest model quirks. Review specific vLLM backend optimizations on GitHub (e.g. [vLLM PR 40082](https://github.com/vllm-project/vllm/pull/40082#issuecomment-4314643705)).
1. **SparkRun Registry**: Check public recipes at [sparkrun.dev](https://sparkrun.dev/recipes/registries/).

## Formulating Configurations & Recipes (Model Quirks)

When you find a new model on the internet, your primary job is to figure out **how to configure it correctly** before handing off to the deployment stage. You must research the model card and community findings to identify:

1. **Sampling Constraints (Anti-Looping)**: Some architectures (especially Qwen models) are highly susceptible to infinite repetition loops. You must research and define the correct `min_p` (over `top_p`), `presence_penalty`, and `frequency_penalty` required for stability.
1. **Stop Tokens**: Accurately mapping internal stop tokens (e.g., `<|eot_id|>` vs `<|im_end|>`) is critical to preventing run-on generations. Do not guess; read the tokenizer config or generation documentation.
1. **Reasoning / Chat Templates**: If the model is a modern reasoning variant (e.g., DeepSeek-R1 derivatives), explicitly identify the required `<think>` tags or tool-calling schema. You must define the necessary `litellm_overrides` needed to parse these reasoning tokens properly.
1. **Context Length**: Determine the maximum safe RoPE scaled context length. Formulate the exact `max_model_len` limit dynamically based on the leftover VRAM budget after weights are loaded.
1. **Draft Models**: If the user wants speculative decoding, research which smaller parameter model pairs best with the target architecture (e.g., Llama-3.2-1B for Llama-3.3-70B).

### Speculative Decoding Compatibility (MANDATORY PRE-DEPLOYMENT GATE)

> [!CAUTION]
> Before recommending ANY speculative decoding configuration, you MUST complete ALL of the following verification steps. Skipping this gate leads to multi-hour debugging cycles with cryptic weight-loading assertion errors.

When a model advertises speculative decoding support (EAGLE, MTP, draft-model, etc.), you MUST verify:

1. **Draft Model Architecture Match**: Confirm the draft model uses the **exact same architecture class** as the target model. A `NemotronHForCausalLM` base model requires a draft model that is also `NemotronHForCausalLM` — not just "similar". Check `config.json` → `architectures` for both models.
1. **Weight Tensor Shape Compatibility**: The draft model's QKV projection, embedding, and LM head dimensions must be compatible with the base model's weight-loading code path. If the base model uses a hybrid Mamba/Transformer architecture, the draft model must share that hybrid structure.
1. **Parallel Drafting Token Requirements**: If `parallel_drafting: true` is set, the draft model's `config.json` MUST contain either `pard_token` or `ptd_token_id`. If these fields are absent, parallel drafting will crash at init. Default to `parallel_drafting: false` unless explicitly verified.
1. **Integrated vs. External Drafting**: Some models (e.g., those with built-in MTP heads) support *integrated* speculation where no separate draft model is needed. Others require a dedicated external draft checkpoint. Do NOT assume one implies the other.
1. **Fallback Strategy**: If no verified-compatible draft model exists, recommend `ngram` speculative decoding as a safe zero-dependency alternative. `ngram` works with ANY model architecture and provides modest speedup (~1.2-1.5x) without risking initialization failures.

**Verification Command** (run inside the vLLM container or locally):

```bash
# Check draft model config for required fields
python3 -c "
import json, pathlib, sys
cfg = json.loads(pathlib.Path(sys.argv[1]).read_text())
arch = cfg.get('architectures', ['UNKNOWN'])[0]
has_pard = 'pard_token' in cfg or 'ptd_token_id' in cfg
print(f'Architecture: {arch}')
print(f'Parallel drafting tokens: {\"YES\" if has_pard else \"NO - parallel_drafting must be false\"}')
" /path/to/draft/model/config.json
```

## Selection Logic (The "Spark Fit" Test)

Even if a model is amazing on the internet, it still needs to run on the workstation.

### 1. Mandatory Availability Check

- **Rule**: You MUST explicitly verify that the model's physical weights are published and publicly downloadable (e.g., legitimately accessible on the HuggingFace Hub) before recommending it. Ensure you locate a valid `repo_id`. API-only models, closed-source stealth models, or vaporware must be disqualified immediately. You do not need to download the weights ahead of time during the recommendation phase, but you MUST establish that the files actually exist and are available for local invocation.
- **Official & Popularity Preference**: When multiple repositories exist for the same model and quantization, you MUST default to the official repository (e.g., `nvidia/`, `google/`, `Qwen/`). If no official version exists, prioritize the repository with higher community trust and higher download counts, as reported by the `verify_hf_model.py` script.

### 2. Mandatory VRAM Profiling (STRICT)

Never rely on theoretical parameter math (e.g., 0.5 GB/B). Many mixed-precision models maintain high-precision layers that significantly increase the weight floor.

- **Rule**: If a SparkRun recipe exists or can be simulated, you MUST determine the actual weight footprint and KV cache overhead before recommending. You MUST explicitly write out your math calculation as a codeblock step in your response before formulating the comparison table. (Use `uv run python -m sparkrun.scripts.recipe vram <recipe> --tp 1` if available locally).
- **Mandatory Quantization Hunting**: You MUST search for an `NVFP4` or heavily optimized quantization (e.g., `AWQ`) variant of the model FIRST. Do not recommend a massive FP16/FP8 base model if an NVFP4 variant exists that fits natively within the workstation's compute budget.
- **VRAM Ceiling**: The aggregate `gpu-memory-utilization` across all models should be tuned within the **0.80–0.95** range (see `stack-manager` Memory Law for guidance). Use **0.80** when co-locating multiple models for maximum headroom, up to the **0.95** hard limit for single-model stacks. The Docker memory ceiling is **120GB**.

#### Logical Math Checkpoints

To prevent fatal infrastructure configurations, you MUST actively enforce these logical checkpoints when discussing context limits or VRAM topologies:

1. **Always verify changes with math**: For example, If the user suggests a larger context window or parameter tweak, you MUST physically calculate the exact boundary (Weights + KV Cache * Context Length) before agreeing. Do not blind-apply assumptions.
1. **Explore Optimization Levers First**: Before restricting a capability (like capping `max_model_len` to avoid OOM), comprehensively evaluate secondary parameters (such as `kv-cache-dtype=nvfp4`) to see if the capability can be safely unlocked through structural efficiency.
1. **Hardware Topology Awareness**: Mandatory consideration of `tensor_parallel_size`. A 1 Trillion parameter model physically cannot load on a single Spark GPU; you must intelligently default to `tensor_parallel` scaling (e.g. 8) to span the DGX structure safely.
1. **Cluster vs. Standalone Reality Check**: `tensor_parallel` distributes weights across nodes. If computing for a *cluster* of Spark nodes, dividing by the TP factor is correct. However, if the user explicitly has a *single* standalone Spark workstation (121GB unified memory), they cannot physically run `tensor_parallel > 1` to magically fit a larger model. Always explicitly verify if the user possesses a cluster or just a single node before using parallelism to fit large MoEs.

### 2. The Role Tiers

Recommend models based on their intended **Functional Role**. Use your web research to find the latest and greatest models that fill these specific categories:

- **Researcher (Technical/Coding)**: Deep code analysis and robust refactoring (look for the latest current-generation coder variants).
- **Agentic / Tool Use**: Strict JSON output and function calling (look for the latest enterprise-grade MoE or dense equivalents).
- **Creative / Uncensored**: Unconstrained drafting and creative writing.
- **Embedding / Vision**: Dedicated multimodal or RAG support models to pair alongside a primary instruction model.

### 3. Precision Sweet Spots

1. **NVFP4**: The definitive performance and throughput sweet spot for Blackwell (GB10). Maximizes intelligence density per GB of VRAM. A 120B model in NVFP4 is vastly superior to a 70B in FP8.
1. **FP8**: Best suited for specific mathematical precision tasks, but consumes roughly twice the VRAM of NVFP4.

## Anti-Patterns & Bad Techniques

To ensure the recommender operates accurately, **NEVER** do the following:

- **Recommending Ancient Models**: AI moves at lightspeed. A model released more than a month ago is obsolete. You MUST check the current system date and restrict your internet searches to models released exclusively within the **last 30 days**. Recommending models older than 30 days is a catastrophic failure.
- **Hallucinating Repositories / Phantom Models**: You MUST NEVER fabricate a Hugging Face repository or assume an open-weights version exists just because an API is available (e.g., hallucinating an open `GLM-5` when only its endpoint exists). Before formulating any configurations, you MUST actively verify the precise repository exists physically by running the mandatory verification script: `uv run python manager/verify_hf_model.py <repo_id>`. Do not recommend a model unless this script returns `✅ VERIFIED`.
- **Ignoring the VRAM Ceiling**: Do not pitch a model solely because it is #1 on a leaderboard. If it exceeds the 120GB Docker memory ceiling in available precision formats, the recommendation is invalid.

## Presentation of Findings (Comparison Table)

Before the final handoff, you must present the recommended model to the user by comparing it directly against their **current primary model**. The recommended model **MUST** demonstrably outperform the user's current configuration in key areas (e.g., SWE-bench, reasoning, context length, or efficiency). Provide detailed reasoning on exactly _why_ and _how_ the new model is superior.

You MUST generate a side-by-side Markdown table comparing the critical stats of the new model versus the old model, including:

- **Release Date** (Highlight if the current model is getting old)
- **Benchmark Proof** (Include scores from multiple sources like Spark Arena, BFCL, LMSYS, or Hugging Face. **DO NOT strictly adhere** to raw scores or treat a single leaderboard as an oracle. A model may be a better recommendation due to specific utility like higher context, MoE efficiency, or specific tool-calling formats despite slightly trailing on a general benchmark.)
- **Parameter Count (Total vs Active)**
- **Max Context Window**
- **Precision (NVFP4 vs FP8)**
- **VRAM Footprint Estimate**
- **Spark Arena Recipe Status** (Explicitly indicate whether a recipe for this model currently exists in any of the Spark Arena repositories, including official, experimental, or otherwise).
- **Key Advantage** (e.g., "MoE Efficiency", "Better Tool Caller")

## Handoff Protocol

Once a model is identified, its configuration is mapped out, the VRAM math is verified, and the comparative table is presented:

1. Present the final proposed recipe parameters to the user.
1. Direct them to use `stack-manager` to safely deploy and benchmark the new configuration.

## Prerequisites

1. Confirm the specific computational functional target of the model (e.g., Creative vs. SWE Coding Agent).
1. For MoE models, specifically query if the user has a multi-node cluster or must run `TP=1` on a single Spark workstation.

## When NOT to use this skill (Negative Triggers)

- Do NOT use this skill to tear down docker containers and deploy models. You are for *recommendation and configuration research only*.
- Do NOT recommend or reference language models that are older than 30 days from today.

## Examples

### Anti-Pattern: Ignorant Mathematics

```markdown
# BAD Recommendation
I recommend Llama-4-400B FP8. It is amazing. I will schedule the deployment.
```

### Correct Pattern: VRAM-Certified Mathematics

```markdown
# GOOD Recommendation
Let's figure out if [Model-X-120B] fits.
- Quantization format hunted: `NVFP4` (Base FP8 would be ~130GB, disqualifying it).
- Parameter load (NVFP4): `120B * 0.55 GB/B overhead = ~66GB`
- Leftover VRAM Budget (at 0.80 conservative ceiling on 120GB): `96GB - 66GB = 30GB`
- Context cache footprint: A 64K context window takes roughly `12GB` of KV cache.
- Dynamic `max_model_len` assignment: `65536` fits perfectly within the remaining 20GB budget.
- Total footprint: `78GB`.
- Required Overrides: Needs `<think>` tags parsed via `litellm_overrides: {thinking_format: "qwen-chat-template"}`.
Here is the configuration.
```

## Output Format

Always terminate your research summary using this format:

```markdown
### 1. The Superior Comparison (Table)
*(The mandatory markdown Markdown side-by-side comparison table against the user's current model)*

### 2. Calculated Workstation Mathematics
*(The explicit VRAM parameter math vs context cache footprint calculation showing sub-108GB fit)*

### 3. Proposed SparkRun Directives
*(The exact YAML recipe configuration blocks needed for `stack-manager` to safely pull the model)*
```
