import json
import sys
import urllib.error
import urllib.request


def verify_model(repo_id):
    url = f"https://huggingface.co/api/models/{repo_id}"
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "SparkStack-Verification-Agent/1.0"}
        )
        with urllib.request.urlopen(req) as response:
            if response.status == 200:
                data = json.loads(response.read().decode("utf-8"))
                print(f"✅ VERIFIED: Repository '{repo_id}' physically exists on Hugging Face.")
                print(f"   Model Pipeline Tag: {data.get('pipeline_tag', 'N/A')}")
                print(f"   Downloads: {data.get('downloads', 'N/A')}")
                sys.exit(0)
    except urllib.error.HTTPError as e:
        print(
            f"❌ ERROR: Repository '{repo_id}' not found or access denied (HTTP {e.code}). DO NOT RECOMMEND THIS MODEL.",
            file=sys.stderr,
        )
        sys.exit(1)
    except Exception as e:
        print(f"❌ ERROR: Failed to verify '{repo_id}': {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: uv run python manager/verify_hf_model.py <repo_id>")
        sys.exit(1)
    verify_model(sys.argv[1])
