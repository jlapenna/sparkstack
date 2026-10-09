---
trigger: always_on
---

# Sparkstack registry source workflow

The registry uses normal reviewed source delivery. Make changes in an isolated
feature worktree from the current configured upstream base and land them through
a pull request with required checks and review. Use the shared
[worktree-hygiene](https://github.com/jlapenna/repo-tools/blob/main/plugins/repo-tools/skills/worktree-hygiene/SKILL.md)
and [land-pr](https://github.com/jlapenna/repo-tools/blob/main/plugins/repo-tools/skills/land-pr/SKILL.md)
workflows; never bypass hooks or protected-branch gates.

Follow the registry's local agent guide for recipe, lane and benchmark ownership.
Source delivery does not authorize model deployment or host operations. Keep
runtime verification within the explicitly requested operational scope.
