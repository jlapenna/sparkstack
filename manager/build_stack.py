#!/usr/bin/env -S uv run --env-file .env --frozen --offline python3
import argparse
import asyncio

from core.builders.stack import StackBuilder

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build an AI service stack for NVIDIA Blackwell.")
    parser.add_argument("stack_name", help="Unique name for the stack")
    parser.add_argument("models", nargs="+", help="List of models/aliases")
    parser.add_argument(
        "--allow-no-embedding",
        action="store_true",
        help="Allow building a stack without an embedding model",
    )
    args = parser.parse_args()
    asyncio.run(
        StackBuilder(
            args.stack_name, args.models, allow_no_embedding=args.allow_no_embedding
        ).build()
    )
