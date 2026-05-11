# Token Budget Algorithm for OpenClaw Compaction

> **Status:** IMPLEMENTED (2026-05-10)
> **Author:** jlapenna
> **Enforced in:** `schemas.py`, `sync_registry.py`, `models.json`

## 1. Problem Statement

OpenClaw's auto-compactor uses two values from `openclaw.json` to manage
conversation memory:

- **`maxTokens`** — the per-turn *completion* budget (how many tokens the model
  may generate in a single response).
- **`reserveTokens`** — the compaction reserve (prompt budget is
  `contextWindow - reserveTokens`). When the estimated prompt exceeds this
  budget, OpenClaw proactively summarizes older history to free space.

If `reserveTokens` consumes too large a fraction of the context window, the
prompt budget shrinks to the point where multi-turn conversations become
impossible. The agent "forgets" — not because the model is bad, but because the
compactor is aggressively truncating history to satisfy an oversized reserve.

### The Poison Pill

The formula `reserveTokens = maxTokens + headroom` is correct in *structure*,
but produces poison values when `maxTokens` is misconfigured:

```
maxTokens = 131,072  (50% of 262k — way too high for a completion budget)
reserveTokens = 131,072 + 8,192 = 139,264  (53.2% of context)
prompt budget = 262,144 - 139,264 = 122,880  (only 46.8% for history)
```

No coding agent needs 131k tokens of output per turn. The industry standard for
tool-heavy agents is 16k-32k.

______________________________________________________________________

## 2. How OpenClaw Consumes These Values

### Source: `preemptive-compaction.ts`

```typescript
const contextTokenBudget = Math.max(1, Math.floor(params.contextTokenBudget));
const requestedReserveTokens = Math.max(0, Math.floor(params.reserveTokens));

const minPromptBudget = Math.min(
  MIN_PROMPT_BUDGET_TOKENS,                    // = 8,000
  Math.max(1, Math.floor(contextTokenBudget * MIN_PROMPT_BUDGET_RATIO)),  // = 0.5
);

const effectiveReserveTokens = Math.min(
  requestedReserveTokens,
  Math.max(0, contextTokenBudget - minPromptBudget),
);

const promptBudgetBeforeReserve = Math.max(1, contextTokenBudget - effectiveReserveTokens);
```

### Key Observations

1. **`MIN_PROMPT_BUDGET_TOKENS = 8,000`** — for large context windows (>16k),
   `Math.min(8000, ctx * 0.5)` always resolves to 8,000. This means the safety
   floor only guarantees 3% of a 262k context for the prompt — essentially
   useless as a guard.

1. **`reserveTokens` passes straight through** unless it would leave fewer than
   8,000 tokens for the prompt. For a 262k context, any reserve under 254,144
   will be accepted as-is.

1. **Compaction triggers** when `estimatedPromptTokens > promptBudgetBeforeReserve`.
   Lower prompt budget = earlier and more aggressive compaction = more history loss.

### Source: `pi-settings.ts` — Floor Application

```typescript
const maxReserve = Math.max(0, ctxBudget - minPromptBudget);
reserveTokensFloor = Math.min(reserveTokensFloor, maxReserve);
```

This caps the *floor* (`DEFAULT_PI_COMPACTION_RESERVE_TOKENS_FLOOR = 20,000`)
against the context budget. But the `reserveTokens` configured in
`openclaw.json` is applied as a direct override, not subject to this floor cap.

______________________________________________________________________

## 3. The Correct Algorithm

### Definitions

| Term            | Meaning                                               | Source                               |
| --------------- | ----------------------------------------------------- | ------------------------------------ |
| `contextWindow` | Total tokens the model can handle (input + output)    | Registry `models.json`               |
| `maxTokens`     | Per-turn completion budget — max output tokens        | Registry `models.json`               |
| `reserveTokens` | Compaction reserve — space held for output + overhead | `sync_registry.py` → `openclaw.json` |
| `promptBudget`  | `contextWindow - reserveTokens` — space for history   | Derived                              |

### Step 1: Set `maxTokens` as a Fixed Completion Budget

`maxTokens` should be a **fixed, task-appropriate value**, not derived from
context window size:

| Agent Type                | Recommended `maxTokens` |
| ------------------------- | ----------------------- |
| Coding agent (tool-heavy) | 16,384 - 32,768         |
| Chat/reasoning agent      | 8,192 - 16,384          |
| Embedding model           | `contextWindow // 2`    |

**Current setting:** `maxTokens = 32,768` for the main coding agent model.

### Step 2: Compute `reserveTokens`

```
reserveTokens = maxTokens + HEADROOM
```

Where `HEADROOM = 8,192` covers:

- System prompt (~2k-4k tokens)
- Tool definitions (~2k-4k tokens)
- Tokenizer drift buffer (~15% of maxTokens ≈ 5k)
- Safety margin (~2k)

### Step 3: Validate Against Context Window

```
reserveTokens ≤ contextWindow × MAX_RESERVE_RATIO
```

Where `MAX_RESERVE_RATIO = 0.30` (30% — generous upper bound).

If the computed reserve exceeds this ratio, clamp it.

### Step 4: Verify Prompt Budget

```
promptBudget = contextWindow - reserveTokens
```

This should be ≥70% of `contextWindow` for healthy multi-turn operation.

______________________________________________________________________

## 4. Worked Example (262k Context)

| Step                                      | Value           | % of Context |
| ----------------------------------------- | --------------- | ------------ |
| `contextWindow`                           | 262,144         | 100%         |
| `maxTokens`                               | 32,768          | 12.5%        |
| `HEADROOM`                                | 8,192           | 3.1%         |
| `reserveTokens = 32768 + 8192`            | 40,960          | **15.6%**    |
| `MAX_RESERVE_RATIO × ctx = 0.30 × 262144` | 78,643          | 30%          |
| Reserve within limit?                     | 40,960 < 78,643 | ✓            |
| `promptBudget = 262144 - 40960`           | 221,184         | **84.4%**    |

### Compaction Behavior

OpenClaw's compactor fires at 84.4% context utilization (when
`estimatedPromptTokens > 221,184`), giving the agent a massive working buffer
for conversation history.

______________________________________________________________________

## 5. Three-Layer Enforcement

Each layer independently prevents the poison pill, so any single misconfiguration
is caught before reaching production:

### Layer 1: Source Values (`models.json`)

The registry `models.json` sets `maxTokens` to a fixed value appropriate for the
model's role. This is the authoritative source of truth.

```json
{
  "id": "main",
  "contextWindow": 262144,
  "maxTokens": 32768
}
```

### Layer 2: Schema Validator (`schemas.py` — `OpenClawModel`)

A Pydantic `model_validator` enforces a `MAX_COMPLETION_TOKENS = 32,768` ceiling:

```python
MAX_COMPLETION_TOKENS: ClassVar[int] = 32_768  # ⚠️ MUST be ClassVar!

# In _clamp_max_tokens validator:
ceiling = min(self.MAX_COMPLETION_TOKENS, self.context_window // 2)

# Guard 1: max_tokens >= context_window → hard clamp
if self.max_tokens >= self.context_window > 0:
    self.max_tokens = ceiling

# Guard 2: max_tokens > MAX_COMPLETION_TOKENS → soft clamp
elif self.max_tokens > self.MAX_COMPLETION_TOKENS and self.context_window > 0:
    self.max_tokens = ceiling
```

This catches both the "equal to context window" poison pill AND the "too
generous for a completion budget" misconfiguration.

> **⚠️ CRITICAL:** `MAX_COMPLETION_TOKENS` **must** be annotated as `ClassVar[int]`,
> not plain `int`. Without `ClassVar`, Pydantic treats it as a model field and
> `model_dump(by_alias=True)` serializes it as `"maxCompletionTokens"` into
> `openclaw.json`. OpenClaw's config parser rejects unrecognized keys, causing a
> gateway crash loop. See Failure Mode 5 below.

### Layer 3: Sync Guard (`sync_registry.py`)

An independent ratio check at sync time clamps `reserveTokens` to never exceed
30% of the smallest non-embedding context window:

```python
MAX_RESERVE_RATIO = 0.30
reserve = global_max_completion + HEADROOM
max_safe_reserve = int(min_context_window * MAX_RESERVE_RATIO)
if reserve > max_safe_reserve:
    reserve = max_safe_reserve
```

This is the last line of defense before the value hits `openclaw.json`.

______________________________________________________________________

## 6. Before vs After Comparison

| Metric               | Before (Broken)  | After (Fixed)    |
| -------------------- | ---------------- | ---------------- |
| `maxTokens`          | 131,072          | 32,768           |
| `reserveTokens`      | 139,264          | 40,960           |
| Reserve % of context | **53.2%**        | **15.6%**        |
| Prompt budget        | 122,880          | 221,184          |
| Prompt % of context  | 46.8%            | **84.4%**        |
| Compaction trigger   | ~47% utilization | ~84% utilization |
| Effective history    | ~30k messages    | ~55k messages    |

______________________________________________________________________

## 7. Constants Reference

| Constant                   | Location                            | Value  | Purpose                                            |
| -------------------------- | ----------------------------------- | ------ | -------------------------------------------------- |
| `MAX_COMPLETION_TOKENS`    | `schemas.py`                        | 32,768 | Schema-level ceiling for `maxTokens`               |
| `HEADROOM`                 | `sync_registry.py`                  | 8,192  | Buffer for system prompt + tools + tokenizer drift |
| `MAX_RESERVE_RATIO`        | `sync_registry.py`                  | 0.30   | Maximum fraction of context for reserve            |
| `MIN_PROMPT_BUDGET_TOKENS` | OpenClaw `preemptive-compaction.ts` | 8,000  | Absolute floor (insufficient for large ctx)        |
| `MIN_PROMPT_BUDGET_RATIO`  | OpenClaw `preemptive-compaction.ts` | 0.50   | Ratio floor (capped by `MIN_PROMPT_BUDGET_TOKENS`) |

______________________________________________________________________

## 8. Industry Best Practices

| Source                    | Recommendation                                                    |
| ------------------------- | ----------------------------------------------------------------- |
| General LLM best practice | Reserve 25-50% of context for output tokens                       |
| Anthropic/Claude guidance | `input + output ≤ context_window`; compact at 70-80% utilization  |
| OpenAI guidance           | Define a fixed reserve buffer (10-30% of window) as safety margin |
| Agent framework patterns  | Proactive compaction at 70-80% fill; hierarchical summarization   |
| Tool-heavy agents         | Clear tool results after processing; keep only action records     |

### Key Insight

`maxTokens ≠ reserveTokens`. The industry consensus is:

- **`maxTokens`** = completion/output budget per turn. A **fixed value** (8k-64k)
  based on task complexity, never scaled to context window size.
- **`reserveTokens`** = buffer for output + tool overhead + system prompt
  overhead. Should be `maxTokens + fixed_headroom`.

______________________________________________________________________

## 9. Failure Modes and Mitigations

### Failure: `maxTokens` set to `contextWindow`

- **Symptom:** Silent forgetfulness — agent loses recent context
- **Mechanism:** `reserveTokens` exceeds context window, compaction runs
  continuously
- **Mitigation:** Schema clamp (Layer 2) auto-corrects to ceiling

### Failure: `maxTokens` set to `contextWindow // 2`

- **Symptom:** Premature compaction — agent forgets after ~15 turns
- **Mechanism:** `reserveTokens` consumes >50% of context
- **Mitigation:** Schema ceiling clamp (Layer 2) reduces to 32k

### Failure: Large `maxTokens` on a small context model

- **Symptom:** `reserveTokens` exceeds 30% of context
- **Mechanism:** Headroom formula breaks down for small windows
- **Mitigation:** Sync ratio guard (Layer 3) independently clamps

### Failure: Agent-level `models.json` overrides

- **Symptom:** Specific agent forgets while others work fine
- **Mechanism:** OpenClaw auto-generates per-agent configs that bypass global
  `openclaw.json`
- **Mitigation:** `sync_registry.py` purges agent-level `models.json` files on
  every sync

### Failure: Schema constant leaks into serialized config

- **Symptom:** Gateway crash loop — `"Unrecognized key: maxCompletionTokens"`
- **Mechanism:** `MAX_COMPLETION_TOKENS` annotated as `int` instead of
  `ClassVar[int]`. Pydantic includes it in `model_dump()` output, and
  `by_alias=True` converts it to camelCase (`maxCompletionTokens`).
  OpenClaw's config parser uses strict validation and rejects unknown keys.
- **Mitigation:** Always annotate class-level constants as `ClassVar[T]`.
  Verify with: `rg 'maxCompletionTokens' ~/.openclaw/openclaw.json` (should
  return empty).

______________________________________________________________________

## 10. Modifying These Values

When changing the token budget:

1. Update `maxTokens` in the source `models.json` (under the registry stack dir)
1. Run `sparkstack sync-registry` to propagate to `openclaw.json`
1. Restart the OpenClaw gateway (`docker restart openclaw-openclaw-gateway-1`)
1. Verify: `rg 'reserveTokens' ~/.openclaw/openclaw.json` — should be ≤30% of
   smallest context window
1. Verify no unrecognized keys leaked from Pydantic serialization:
   `rg 'maxCompletionTokens' ~/.openclaw/openclaw.json` — must return empty
1. Verify no agent-level overrides exist:
   `find ~/.openclaw/agents/ -name 'models.json' -type f`

If adjusting `MAX_COMPLETION_TOKENS` in `schemas.py`:

- Keep it between 16,384 and 65,536 for coding agents
- Ensure `MAX_COMPLETION_TOKENS + HEADROOM < contextWindow × MAX_RESERVE_RATIO`
  for all models
