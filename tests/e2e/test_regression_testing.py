import os
import string

import httpx
import pytest
from dotenv import load_dotenv
from loguru import logger

from tests.e2e.context import E2EContext


@pytest.mark.order(13)
@pytest.mark.asyncio
async def test_regression_testing(ctx: E2EContext):
    load_dotenv(ctx.root_dir / ".env")
    api_key = os.getenv("VLLM_SPARK_API_KEY", "")

    if not api_key:
        logger.error("❌ VLLM_SPARK_API_KEY not found in .env")
        raise AssertionError()

    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    payload = {
        "model": "main",
        "messages": [
            {
                "role": "user",
                "content": "Write a 3 paragraph story about a knight. Use the words 'and' and 'or' quite frequently.",
            }
        ],
        "max_tokens": 200,
        "temperature": 0.0,  # Greedy decoding often triggers the exact repetition loop fast if penalty is present
    }

    async with httpx.AsyncClient() as client:
        res = await client.post(
            f"{ctx.gateway_url}/chat/completions", headers=headers, json=payload, timeout=300
        )
        if res.status_code == 200:
            data = res.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            content = content or ""

            # Check for "or-or-or-or" or word repeated 5+ times consecutively

            clean_content = content.translate(str.maketrans("", "", string.punctuation)).lower()
            words = clean_content.split()
            repetition_count = 0
            for i in range(1, len(words)):
                if words[i] == words[i - 1]:
                    repetition_count += 1
                    if repetition_count >= 5:
                        logger.error(
                            f"❌ Failure: Detected infinite text repetition loop (Word '{words[i]}' repeated consecutively).\nText: {content[:200]}"
                        )
                        raise AssertionError()
                else:
                    repetition_count = 0

            logger.info("✅ Pass: Anti-Repetition Regression Test (Output is natural)")
            return
        else:
            logger.error(f"❌ Failure: Chat completions returned {res.status_code}: {res.text}")
            raise AssertionError()
