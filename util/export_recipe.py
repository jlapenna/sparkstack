#!/usr/bin/env -S uv run --env-file .env --frozen --offline python3
import argparse
import asyncio
import hashlib
import sys
from pathlib import Path

from sparkstack.core.env import REGISTRY_DIR, SPARKRUN_CMD
from sparkstack.core.utils import CommandError, async_run_command


async def main():
    parser = argparse.ArgumentParser(
        description="Export an upstream sparkrun recipe to a versioned local YAML file."
    )
    parser.add_argument("recipe", help="The upstream recipe name (e.g., @eugr/openai-gpt-oss-120b)")
    args = parser.parse_args()

    recipe = args.recipe
    base_name = recipe.split("/")[-1]

    try:
        result = await async_run_command([*SPARKRUN_CMD, "export", "recipe", recipe])
        content = result.stdout
    except CommandError as e:
        print(f"❌ Failed to export recipe {recipe}:\n{e.stderr}", file=sys.stderr)
        sys.exit(1)

    if not content.strip():
        print(f"❌ Exported content for {recipe} is empty.", file=sys.stderr)
        sys.exit(1)

    # Generate a short SHA256 hash of the recipe content
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:7]
    out_dir = REGISTRY_DIR / "sparkrun"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{base_name}-{content_hash}.yaml"

    out_file.write_text(content)

    print(f"✅ Exported {recipe} to {out_file.relative_to(Path.cwd())}")
    print("You can now edit this local copy with Blackwell optimizations before building a stack.")


if __name__ == "__main__":
    asyncio.run(main())
