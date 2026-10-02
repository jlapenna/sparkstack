# Documentation Index

Use the smallest owner for the task.

| Need | Document |
| --- | --- |
| Understand control flow and ownership | [`../ARCHITECTURE.md`](../ARCHITECTURE.md) |
| Set up development and host tuning | [`../DEVELOPMENT.md`](../DEVELOPMENT.md) |
| See the product overview and CLI entry points | [`../README.md`](../README.md) |
| Follow mandatory repository rules | [`../.agents/rules/`](../.agents/rules/) |
| Build or rotate model stacks | [`../.agents/skills/stack-manager/SKILL.md`](../.agents/skills/stack-manager/SKILL.md) |
| Debug topology and consult incident knowledge | [`../.agents/skills/stack-knowledge/SKILL.md`](../.agents/skills/stack-knowledge/SKILL.md) |
| Verify a prepared running stack | [`../.agents/skills/stack-verification/SKILL.md`](../.agents/skills/stack-verification/SKILL.md) |
| Change sibling source dependencies | [`../.agents/skills/source-dependency-dev/SKILL.md`](../.agents/skills/source-dependency-dev/SKILL.md) |
| Change monitoring | [`../.agents/skills/monitoring/SKILL.md`](../.agents/skills/monitoring/SKILL.md) |

Implementation lives in `sparkstack/`; service definitions live in
`services/`; executable evidence lives in `tests/`. Domain skills are the
authoritative procedures. Link new durable documentation here rather than
expanding `AGENTS.md`.
