import requests
import json
import os

url = "http://localhost:4000/v1/chat/completions"
# The gateway token in OpenClaw .env is needed, let me extract it from OpenClaw's .env!
env_path = "/home/jlapenna/.openclaw/.env"
gateway_token = None
if os.path.exists(env_path):
    with open(env_path, "r") as f:
        for line in f:
            if line.startswith("OPENCLAW_GATEWAY_AUTH_TOKEN="):
                gateway_token = line.split("=")[1].strip()

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {gateway_token}"
}
data = {
    "model": "main",
    "messages": [
        {"role": "user", "content": "Explain step by step why 2+2=4."}
    ]
}

response = requests.post(url, headers=headers, json=data)
print(json.dumps(response.json(), indent=2))
