import re
from pathlib import Path

ROOT = Path(__file__).parents[2]
MAX_CONTEXT_BYTES = 14 * 1024


def read(path: str) -> str:
    return (ROOT / path).read_text()


def test_always_loaded_agent_context_stays_compact() -> None:
    assert len((ROOT / "AGENTS.md").read_bytes()) <= MAX_CONTEXT_BYTES


def test_agent_router_points_to_rules_skills_architecture_and_proof() -> None:
    agents = read("AGENTS.md")
    for route in (
        ".agents/rules/",
        ".agents/skills/",
        "ARCHITECTURE.md",
        "docs/README.md",
        "tests/e2e/",
        "source-dependency-dev",
    ):
        assert route.lower() in agents.lower()


def test_router_does_not_duplicate_operational_commands() -> None:
    agents = read("AGENTS.md")
    assert not re.search(r"docker (compose|rm)|sparkstack (update|set-current)|git (pull|rebase)", agents)


def test_documentation_index_targets_exist() -> None:
    for path in (
        "ARCHITECTURE.md",
        "README.md",
        "DEVELOPMENT.md",
        ".agents/skills/stack-manager/SKILL.md",
        ".agents/skills/stack-knowledge/SKILL.md",
        ".agents/skills/stack-verification/SKILL.md",
        ".agents/skills/source-dependency-dev/SKILL.md",
        ".agents/skills/monitoring/SKILL.md",
    ):
        assert (ROOT / path).is_file(), path


def test_architecture_records_source_runtime_and_dependency_boundaries() -> None:
    architecture = read("ARCHITECTURE.md")
    for concept in (
        "Source and Runtime Boundaries",
        "sparkstack-registry",
        "sparkrun",
        "openclaw",
        "Proof Ladder",
    ):
        assert concept.lower() in architecture.lower()


def test_negative_fixtures_violate_contract() -> None:
    assert len(b"x" * (MAX_CONTEXT_BYTES + 1)) > MAX_CONTEXT_BYTES
    assert re.search(r"docker (compose|rm)", "docker compose down")
