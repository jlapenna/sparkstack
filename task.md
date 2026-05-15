# Service Update Task Checklist

## Phase 0: Quirk Invalidation
- [ ] Investigate quirks for current models in `qwen-3.6-20260511-01`
- [ ] Perform web research for engine optimizations
- [ ] Perform invalidation tests if necessary

## Phase 0.5: Rollback Escape Hatch
- [ ] Define rollback command to `qwen-3.6-20260511-01` (current stable)

## Phase 0.75: Source Dependency Verification
- [ ] Verify SparkRun branch is `local-dev` and clean
- [ ] Verify OpenClaw branch is `local-dev` and clean
- [ ] Ensure registry is synced
- [ ] Record SparkRun version

## Phase 1: Hardware & Resource Budget
- [ ] Profile VRAM for current models
- [ ] Verify aggregate totals are within limits (120GB Docker ceiling)
- [ ] Ensure VRAM utilization >= 85%

## Phase 2: Detailed Implementation Steps
- [ ] Verify model accessibility
- [ ] Run VRAM validation
- [ ] Execute `update_services.py` to rotate containers

## Phase 3: Mandatory E2E Verification Suite
- [ ] Run `uv run pytest -x tests/e2e/`
- [ ] Capture raw terminal output

## Phase 4: Formal Benchmarking
- [ ] Run `sparkrun benchmark` for main model
- [ ] Move results to stack directory
- [ ] Scrub API keys from results

## Phase 5: Failure Recovery Protocol
- [ ] Ready to halt on failure and report to user

## Phase 6: Mandatory Proof of Execution
- [ ] Provide raw terminal output of verification and benchmark

## Phase 7: Finalization
- [ ] Document learnings in `plan.md`
- [ ] Cleanup iterative stack directories (if any were created)
- [ ] Finalize name and symlinks
- [ ] Post-rename verification
- [ ] Commit finalized stack
