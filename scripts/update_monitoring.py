#!/usr/bin/env -S uv run --env-file .env --frozen --offline python3

import os
import re

import httpx

print("🔍 Checking for latest monitoring container versions...\n")


def get_latest_github_release(repo):
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    try:
        with httpx.Client() as client:
            response = client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            response.raise_for_status()
            return response.json()["tag_name"]
    except Exception as e:
        print(f"Error fetching {repo}: {e}")
        return None


def get_latest_gcr_tag(repo):
    url = f"https://gcr.io/v2/{repo}/tags/list"
    try:
        with httpx.Client() as client:
            response = client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            response.raise_for_status()
            data = response.json()
            tags = [
                t
                for t in data["tags"]
                if t.startswith("v0.") and "test" not in t and "containerd" not in t
            ]
            tags.sort(key=lambda s: [int(x) for x in re.findall(r"\d+", s)], reverse=True)
            return tags[0] if tags else None
    except Exception as e:
        print(f"Error fetching GCR {repo}: {e}")
        return None


def get_latest_dockerhub_tag(namespace, repo, suffix=""):
    url = f"https://hub.docker.com/v2/repositories/{namespace}/{repo}/tags/?page_size=50"
    try:
        with httpx.Client() as client:
            response = client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            response.raise_for_status()
            data = response.json()
            tags = [t["name"] for t in data["results"]]

            valid_tags = []
            for t in tags:
                if any(x in t.lower() for x in ["rc", "beta", "alpha", "test"]):
                    continue
                if suffix and not t.endswith(suffix):
                    continue

                base_t = t.replace(suffix, "") if suffix else t
                if re.match(r"^v?\d+\.\d+\.\d+$", base_t):
                    valid_tags.append(t)

            valid_tags.sort(key=lambda s: [int(x) for x in re.findall(r"\d+", s)], reverse=True)
            if valid_tags:
                return valid_tags[0]
    except Exception as e:
        print(f"Error fetching {namespace}/{repo}: {e}")
    return None


UPDATES = {
    "quay.io/prometheus/prometheus": lambda: (
        f"quay.io/prometheus/prometheus:{get_latest_github_release('prometheus/prometheus')}"
    ),
    "grafana/grafana": lambda: f"grafana/grafana:{get_latest_dockerhub_tag('grafana', 'grafana')}",
    "grafana/alloy": lambda: f"grafana/alloy:{get_latest_github_release('grafana/alloy')}",
}

COMPOSE_FILE = "services/monitoring/docker-compose.yml"
if not os.path.exists(COMPOSE_FILE):
    print(f"❌ Error: {COMPOSE_FILE} not found.")
    exit(1)

with open(COMPOSE_FILE) as f:
    content = f.read()

# We need to swap out docker hub images for quay.io versions where applicable before processing
content = content.replace("image: prom/prometheus", "image: quay.io/prometheus/prometheus")

changes = 0
for image_base, fetcher in UPDATES.items():
    print(f"Checking {image_base}...")
    new_image = fetcher()
    if not new_image or "None" in new_image:
        print("  ❌ Failed to resolve latest version.")
        continue

    pattern = rf"(image:\s*){image_base}:[a-zA-Z0-9_.-]+"
    match = re.search(pattern, content)

    if match:
        current_image = match.group(0).split(":", 1)[1].strip()
        if current_image != new_image.split(":", 1)[1]:
            print(f"  🚀 Updating: {current_image} -> {new_image.split(':', 1)[1]}")
            content = re.sub(pattern, rf"\g<1>{new_image}", content)
            changes += 1
        else:
            print(f"  ✅ Already up to date: {current_image}")
    else:
        print("  ⚠️ Not found in compose file.")

# Force write if we just swapped to quay.io, even if versions didn't change
if changes > 0 or "quay.io" in content:
    with open(COMPOSE_FILE, "w") as f:
        f.write(content)
    print(f"\n🎉 Updated dependencies and registries in {COMPOSE_FILE}.")
    print("👉 Run 'cd services/monitoring && docker compose up -d' to apply the updates.")
else:
    print("\n✨ Everything is up to date! No updates needed.")
